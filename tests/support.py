"""Isolated Flask application fixture shared by security regressions."""

import importlib.util
import io
import logging
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch


class AppTestCase(unittest.TestCase):
    def setUp(self):
        # Startup creates data directories and a worker. Isolate both from the
        # user's installation while loading the actual application source.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        source = Path(__file__).resolve().parents[1] / "app.py"
        target = Path(self.temp.name) / "app.py"
        shutil.copyfile(source, target)
        spec = importlib.util.spec_from_file_location("yt2mp3_test_app", target)
        self.module = importlib.util.module_from_spec(spec)
        with patch.object(threading.Thread, "start"):
            spec.loader.exec_module(self.module)
        # Retain local diagnostics without printing synthetic tracebacks during
        # a successful test run. assertLogs can still inspect specific failures.
        logger = logging.getLogger("yt2mp3_test_app")
        self.log_output = io.StringIO()
        handlers = patch.object(logger, "handlers", [logging.StreamHandler(self.log_output)])
        propagation = patch.object(logger, "propagate", False)
        handlers.start()
        propagation.start()
        self.addCleanup(handlers.stop)
        self.addCleanup(propagation.stop)
        self.client = self.module.app.test_client()
        self.headers = {"X-App-Token": self.module.APP_TOKEN}

    def post(self, route, data=None):
        return self.client.post(route, json=data or {}, headers=self.headers)

