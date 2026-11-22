"""Regression tests for filesystem boundaries and downloader arguments."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from unittest.mock import patch

from yt_dlp import parse_options
from yt_dlp.options import parseOpts

from support import AppTestCase


class InputBoundaryTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.root = self.module.BASE_DIR.resolve()
        self.outside_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside_temp.cleanup)
        self.outside = Path(self.outside_temp.name).resolve()
        roots = patch.object(self.module, "ALLOWED_PATH_ROOTS", (str(self.root),), create=True)
        roots.start()
        self.addCleanup(roots.stop)

    def test_output_rejects_outside_paths_without_creating_directories(self):
        for target in (self.outside / "new", self.root / ".." / self.outside.name / "new"):
            with self.subTest(target=target):
                response = self.post("/api/settings", {"output_dir": str(target)})
                self.assertEqual(response.status_code, 400)
                self.assertFalse(target.exists())

    def test_sibling_prefix_and_symlink_do_not_expand_access(self):
        sibling = self.root.parent / (self.root.name + "-sibling")
        self.addCleanup(shutil.rmtree, sibling, ignore_errors=True)
        link = self.root / "escape"
        link.symlink_to(self.outside, target_is_directory=True)
        for target in (sibling / "new", link / "new"):
            with self.subTest(target=target):
                with self.assertRaises(self.module.UserError):
                    self.module.ensure_output_dir(str(target))
                self.assertFalse(target.exists())

    def test_relative_and_unicode_paths_inside_root_work(self):
        folder = self.module.ensure_output_dir("music/日本語 and spaces")
        self.assertEqual(folder, self.root / "music/日本語 and spaces")
        self.assertTrue(folder.is_dir())

    def test_extra_trusted_root_allows_external_location(self):
        with patch.object(self.module, "ALLOWED_PATH_ROOTS", (str(self.root), str(self.outside)), create=True):
            folder = self.module.ensure_output_dir(str(self.outside / "music"))
        self.assertTrue(folder.is_dir())

    def test_extra_roots_are_read_from_startup_environment(self):
        with patch.dict(os.environ, {"YT2MP3_ALLOWED_ROOTS": str(self.outside)}):
            self.assertIn(str(self.outside), self.module.configured_path_roots())
        with patch.dict(os.environ, {"YT2MP3_ALLOWED_ROOTS": "relative/folder"}):
            with self.assertRaises(ValueError):
                self.module.configured_path_roots()

    def test_settings_cannot_change_the_root_allowlist(self):
        response = self.post("/api/settings", {"YT2MP3_ALLOWED_ROOTS": str(self.outside)})
        self.assertEqual(response.status_code, 200)
        with self.assertRaises(self.module.UserError):
            self.module.ensure_output_dir(str(self.outside / "forbidden"))

    def test_cookie_file_must_be_inside_a_trusted_root(self):
        cookies = self.outside / "cookies.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        link = self.root / "cookies.txt"
        link.symlink_to(cookies)
        for path in (cookies, link):
            with self.subTest(path=path):
                with self.assertRaises(self.module.UserError):
                    self.module.auth_args(False, "chrome", "", str(path))

    def test_cookie_path_is_an_absolute_option_value(self):
        cookies = self.root / "--exec=test.txt"
        cookies.write_text("# Netscape HTTP Cookie File\n")
        args = self.module.auth_args(False, "chrome", "", str(cookies))
        self.assertEqual(args, ["--cookies=" + str(cookies)])
        parsed = parse_options(["--ignore-config", *args, "--", "https://youtube.com/watch?v=test"])
        self.assertEqual(parsed.ydl_opts["cookiefile"], str(cookies))
        self.assertFalse(parsed.ydl_opts.get("exec_cmd"))

    def test_browser_profile_cannot_escape_allowed_roots_or_change_spec(self):
        for profile in (str(self.outside), "../../outside", "Profile 1::container", "Profile 1\n--exec=bad"):
            with self.subTest(profile=profile):
                with self.assertRaises(self.module.UserError):
                    self.module.auth_args(True, "chrome", profile, "")
        args = self.module.auth_args(True, "chrome", "Profile 1", "")
        parsed = parse_options(["--ignore-config", *args, "--", "https://youtube.com/watch?v=test"])
        self.assertEqual(parsed.ydl_opts["cookiesfrombrowser"], ("chrome", "Profile 1", None, None))

    def test_open_paths_stay_within_download_roots(self):
        output = self.module.DEFAULT_OUTPUT_DIR
        inside = output / "song.mp3"
        inside.write_bytes(b"test")
        self.assertEqual(self.module.allowed_path(str(inside)), inside.resolve())
        (output / "escape").symlink_to(self.outside, target_is_directory=True)
        # A poisoned history entry must not authorize a location beyond the
        # startup allowlist, even when its parent matches the requested path.
        self.module.manager.history.append({"path": str(self.outside / "song.mp3")})
        for path in (self.outside, output / "escape", output / ".." / "data"):
            with self.subTest(path=path):
                with self.assertRaises(self.module.UserError):
                    self.module.allowed_path(str(path))

    def test_existing_temp_symlink_cannot_redirect_job_work(self):
        manager = self.module.manager
        job = manager.create_job({"url": "https://youtube.com/watch?v=test"})
        (self.module.DEFAULT_OUTPUT_DIR / ".yt2mp3-tmp").symlink_to(self.outside, target_is_directory=True)
        info = {"title": "test", "uploader": "test", "thumbnail": None,
                "duration": 1, "is_playlist": False, "playlist_count": 1}
        with patch.object(self.module, "probe_url", return_value=info), \
             patch.object(subprocess, "Popen", side_effect=OSError("stop before download")) as spawn:
            manager._run_job(job["id"])
        self.assertFalse((self.outside / job["id"]).exists())
        spawn.assert_not_called()
        self.assertEqual(manager.public_job(manager.jobs[job["id"]])["status"], "failed")

    def test_cleanup_does_not_follow_an_existing_temp_symlink(self):
        link = self.module.DEFAULT_OUTPUT_DIR / ".yt2mp3-tmp"
        link.symlink_to(self.outside, target_is_directory=True)
        stale = self.outside / "old-job"
        stale.mkdir()
        sentinel = stale / "keep.txt"
        sentinel.write_text("keep")
        old = time.time() - 172800
        os.utime(stale, (old, old))
        self.module.manager._cleanup_stale_temp_dirs()
        self.assertTrue(sentinel.is_file())
        self.assertEqual(sentinel.read_text(), "keep")

    def test_default_output_symlink_is_validated_at_startup(self):
        link = self.root / "default-output"
        link.symlink_to(self.outside, target_is_directory=True)
        with patch.object(self.module, "DEFAULT_OUTPUT_DIR", link), \
             patch.object(self.module.threading.Thread, "start"):
            with self.assertRaises(self.module.UserError):
                self.module.JobManager()

    def test_completion_preserves_external_symlink_targets_and_the_download(self):
        manager = self.module.manager
        job = manager.create_job({"url": "https://youtube.com/watch?v=test"})
        output = self.module.DEFAULT_OUTPUT_DIR
        temp = output / ".yt2mp3-tmp" / job["id"]
        temp.mkdir(parents=True)
        manager.jobs[job["id"]]["_temp_dir"] = str(temp)
        source = temp / "song.mp3"
        source.write_bytes(b"download")
        external = self.outside / "original.mp3"
        external.write_bytes(b"original")  # Same size must not count as a duplicate.
        (output / "song.mp3").symlink_to(external)
        (output / "song (2).mp3").symlink_to(self.outside / "missing.mp3")
        manager._complete(job["id"], [str(source)], partial=False)
        self.assertEqual(external.read_bytes(), b"original")
        self.assertTrue((output / "song.mp3").is_symlink())
        self.assertTrue((output / "song (2).mp3").is_symlink())
        completed = Path(manager.jobs[job["id"]]["path"])
        self.assertEqual(completed, output / "song (3).mp3")
        self.assertEqual(completed.read_bytes(), b"download")
        self.assertEqual(manager.history[0]["path"], str(completed))

    def test_completion_rejects_sources_outside_the_job_temp_directory(self):
        manager = self.module.manager
        for directory in (self.outside, self.root):
            with self.subTest(directory=directory):
                job = manager.create_job({"url": "https://youtube.com/watch?v=test"})
                temp = self.module.DEFAULT_OUTPUT_DIR / ".yt2mp3-tmp" / job["id"]
                temp.mkdir(parents=True)
                manager.jobs[job["id"]]["_temp_dir"] = str(temp)
                external = directory / "keep.mp3"
                external.write_bytes(b"keep")
                source_link = temp / "link.mp3"
                source_link.symlink_to(external)
                manager._complete(job["id"], [str(source_link)], partial=False)
                self.assertEqual(external.read_bytes(), b"keep")
                self.assertEqual(manager.jobs[job["id"]]["status"], "failed")
                self.assertEqual(manager.history, [])

    def test_empty_and_nul_paths_return_validation_errors(self):
        for value in ("", "\x00bad"):
            with self.subTest(value=value):
                self.assertEqual(self.post("/api/open", {"path": value}).status_code, 400)

    def test_probe_and_download_end_options_before_url(self):
        url = "https://youtube.com/watch?v=test&title=--exec=bad"
        result = subprocess.CompletedProcess([], 0, stdout='{"id":"test","title":"test"}', stderr="")
        with patch.object(subprocess, "run", return_value=result) as run:
            self.module.probe_url(url, False, False, "chrome", "", "")
        probe_command = run.call_args.args[0]
        manager = self.module.manager
        job = manager.create_job({"url": url})
        download_command = manager._build_command(job["id"])
        for command in (probe_command, download_command):
            with self.subTest(command=command):
                self.assertEqual(command[-2:], ["--", url])
                self.assertIn("--ignore-config", command)
                parsed = parse_options(command[3:])
                self.assertEqual(parsed.urls, [url])
                self.assertFalse(parsed.ydl_opts.get("exec_cmd"))

    def test_direct_probe_rejects_option_like_url_before_spawning(self):
        with patch.object(subprocess, "run") as run:
            with self.assertRaises(self.module.UserError):
                self.module.probe_url("--exec=bad", False, False, "chrome", "", "")
        run.assert_not_called()

    def test_downloader_ignores_config_files(self):
        config = self.root / "yt-dlp.conf"
        config.write_text("--exec=echo-config-command\n")
        command = self.module.ytdlp_command()
        # The subprocess CLI loads configs by default. parse_options(argv)
        # disables them implicitly, so use the real CLI parser mode here.
        old_cwd = os.getcwd()
        try:
            os.chdir(self.root)
            _, unsafe, _ = parseOpts(["--", "https://youtube.com/watch?v=test"], ignore_config_files=False)
            self.assertTrue(unsafe.exec_cmd)
            _, safe, _ = parseOpts([*command[3:], "--", "https://youtube.com/watch?v=test"], ignore_config_files=False)
        finally:
            os.chdir(old_cwd)
        self.assertFalse(safe.exec_cmd)
