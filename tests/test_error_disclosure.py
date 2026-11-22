"""Exercise public error responses without downloads or desktop dialogs."""

import importlib.util
import io
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SECRET = "private-test-token /private/test-user/cookies.txt"


class ErrorDisclosureTests(unittest.TestCase):
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

    def assert_safe_error(self, response, status):
        self.assertEqual(response.status_code, status)
        body = response.get_json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])
        self.assertNotIn(SECRET, json.dumps(body))
        self.assertNotIn("Traceback", json.dumps(body))

    def test_unexpected_inspect_exception_is_private_and_logged(self):
        with patch.object(self.module, "probe_url", side_effect=RuntimeError(SECRET)):
            with self.assertLogs("yt2mp3_test_app", level="ERROR") as logs:
                self.assert_safe_error(
                    self.post("/api/inspect", {"url": "https://youtube.com/watch?v=test"}), 500
                )
            self.assertIn(SECRET, "\n".join(logs.output))

    def test_filesystem_errors_do_not_leak_through_user_errors(self):
        for route in ("/api/settings", "/api/inspect", "/api/jobs"):
            with self.subTest(route=route):
                with patch.object(Path, "mkdir", side_effect=OSError(SECRET)):
                    self.assert_safe_error(self.post(route, {
                        "output_dir": str(Path(self.temp.name) / "blocked"),
                        "url": "https://youtube.com/watch?v=test",
                    }), 400)

    def test_open_and_reveal_errors_are_private(self):
        output = self.module.DEFAULT_OUTPUT_DIR
        for route in ("/api/open", "/api/reveal", "/api/open-output"):
            with self.subTest(route=route):
                with patch.object(self.module, "IS_WINDOWS", False), \
                     patch.object(sys, "platform", "linux"), \
                     patch.object(subprocess, "Popen", side_effect=OSError(SECRET)):
                    response = self.post(route, {"path": str(output)})
                    self.assert_safe_error(response, 400 if route == "/api/open-output" else 500)

    def test_folder_picker_errors_are_private_on_all_platforms(self):
        for platform in ("darwin", "linux"):
            with self.subTest(platform=platform):
                with patch.object(self.module, "IS_WINDOWS", False), \
                     patch.object(sys, "platform", platform), \
                     patch.object(shutil, "which", return_value="/usr/bin/zenity"), \
                     patch.object(subprocess, "run", side_effect=OSError(SECRET)):
                    self.assert_safe_error(self.post("/api/pick-folder"), 500)
        def fail_dialog():
            raise RuntimeError(SECRET)

        fake_tk = SimpleNamespace(Tk=fail_dialog, filedialog=SimpleNamespace())
        with patch.object(self.module, "IS_WINDOWS", True), \
             patch.dict(sys.modules, {"tkinter": fake_tk}):
            self.assert_safe_error(self.post("/api/pick-folder"), 500)

    def test_unknown_downloader_errors_are_private_but_known_advice_survives(self):
        result = subprocess.CompletedProcess([], 1, stdout="", stderr=SECRET)
        with patch.object(subprocess, "run", return_value=result):
            self.assert_safe_error(self.post("/api/inspect", {
                "url": "https://youtube.com/watch?v=test",
            }), 400)
        with patch.object(subprocess, "run", side_effect=OSError(SECRET)):
            self.assert_safe_error(self.post("/api/inspect", {
                "url": "https://youtube.com/watch?v=test",
            }), 400)
        self.assertNotIn(SECRET, self.module.friendly_error(SECRET))
        advice = self.module.friendly_error("ERROR: Sign in to confirm you're not a bot " + SECRET)
        self.assertIn("Use my account", advice)
        self.assertNotIn(SECRET, advice)

    def test_failed_job_state_does_not_expose_raw_downloader_output(self):
        manager = self.module.manager
        job = manager.create_job({"url": "https://youtube.com/watch?v=test"})
        manager.jobs[job["id"]]["_last_error"] = SECRET
        manager._fail(job["id"], self.module.friendly_error(SECRET))
        response = self.client.get("/api/state", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["jobs"][0]["status"], "failed")

    def test_worker_exception_does_not_expose_diagnostics(self):
        manager = self.module.manager
        manager.create_job({"url": "https://youtube.com/watch?v=test"})
        manager.queue.put(None)
        with patch.object(manager, "_run_job", side_effect=RuntimeError(SECRET)):
            manager._worker_loop()
        response = self.client.get("/api/state", headers=self.headers)
        self.assertNotIn(SECRET, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["jobs"][0]["status"], "failed")

    def test_validation_messages_and_status_codes_remain_useful(self):
        response = self.post("/api/settings", {"quality": "invalid"})
        self.assert_safe_error(response, 400)
        self.assertIn("quality", response.get_json()["error"])
        response = self.post("/api/jobs/missing/cancel")
        self.assert_safe_error(response, 404)
        self.assertIn("no longer exists", response.get_json()["error"])
        response = self.post("/api/jobs/missing/retry")
        self.assert_safe_error(response, 400)
        response = self.post("/api/open", {"path": str(Path(self.temp.name) / "outside")})
        self.assert_safe_error(response, 400)
        self.assertIn("outside", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
