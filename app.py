from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from typing import Any
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request


APP_NAME = "yt2mp3"
APP_VERSION = "1.0.0"
IS_WINDOWS = os.name == "nt"
IS_FROZEN = bool(getattr(sys, "frozen", False))

if IS_FROZEN:
    BASE_DIR = Path(sys.executable).resolve().parent
    RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent
    RESOURCE_DIR = BASE_DIR

DATA_DIR = BASE_DIR / "data"
DEFAULT_OUTPUT_DIR = BASE_DIR / "downloads"
SETTINGS_FILE = DATA_DIR / "settings.json"
HISTORY_FILE = DATA_DIR / "history.json"
PORT = int(os.environ.get("YT2MP3_PORT", "8765"))
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0
APP_TOKEN = os.environ.get("YT2MP3_TOKEN") or secrets.token_urlsafe(24)


def resource_path(*parts: str) -> Path:
    return RESOURCE_DIR.joinpath(*parts)


def resolve_ffmpeg() -> str:
    if IS_FROZEN:
        return str(resource_path("bin", "ffmpeg.exe"))
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


FFMPEG_PATH = resolve_ffmpeg()

QUALITY_CHOICES = {"320K", "256K", "192K", "128K", "0"}
BROWSER_CHOICES = {"chrome", "edge", "firefox", "brave", "chromium", "opera", "vivaldi"}

DEFAULT_SETTINGS: dict[str, Any] = {
    "output_dir": str(DEFAULT_OUTPUT_DIR),
    "quality": "320K",
    "embed_metadata": True,
    "embed_thumbnail": True,
    "playlist": False,
    "use_account": False,
    "browser": "chrome",
    "browser_profile": "",
    "cookies_file": "",
}

PROGRESS_RE = re.compile(r"^__PROGRESS__(.*)$")
DONE_PREFIX = "__DONE__"


class UserError(Exception):
    """An error that is safe and useful to show in the UI."""


def ytdlp_command() -> list[str]:
    if IS_FROZEN:
        return [sys.executable, "--ytdlp"]
    return [sys.executable, "-m", "yt_dlp"]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def friendly_error(text: str) -> str:
    raw = clean_text(text, 1200)
    raw = re.sub(r"^ERROR:\s*", "", raw)
    raw = re.sub(r"^\[[^\]]+\]\s*[^:]+:\s*", "", raw)
    lower = raw.lower()

    if "sign in to confirm" in lower or "not a bot" in lower:
        return "YouTube wants a signed-in session for this request. Turn on 'Use my account' and pick your browser, then try again."
    if "age-restricted" in lower or "confirm your age" in lower:
        return "This video is age-restricted. Turn on 'Use my account' so yt-dlp can use your browser session."
    if "private video" in lower:
        return "This is a private video. Make sure the account selected in 'Use my account' can access it."
    if "members-only" in lower or "members only" in lower:
        return "This is a members-only video. Use an account with access to that channel."
    if "video unavailable" in lower or "video is unavailable" in lower or "this video is not available" in lower:
        return "YouTube says this video is unavailable in your region or has been removed."
    if "unsupported url" in lower:
        return "That link is not a supported video or playlist."
    if "http error 429" in lower or "too many requests" in lower:
        return "YouTube is rate-limiting this connection. Wait a few minutes, then try one item at a time."
    if "failed to decrypt" in lower or "could not copy" in lower or "cookie" in lower and "database" in lower:
        return "The browser cookie database could not be read. Close the browser completely and retry, or export a cookies.txt file and point the app at it."
    if "cookies" in lower and ("not found" in lower or "does not exist" in lower):
        return "The cookies file could not be found. Check the path in Account settings."
    if "ffmpeg" in lower:
        return "The bundled ffmpeg could not run. Re-run setup.bat to repair the app."
    if "requested format is not available" in lower:
        return "No audio-only stream was available. Try updating yt-dlp from the app folder."
    if "unable to download" in lower and "webpage" in lower:
        return "YouTube did not return the video page. Check the link, or turn on 'Use my account'."
    if not raw:
        return "yt-dlp failed without an error message."
    return raw


def normalize_url(value: str) -> str:
    url = (value or "").strip()
    if not url:
        raise UserError("Paste a YouTube link first.")
    if len(url) > 2000:
        raise UserError("That link is too long.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        if re.match(r"^(www\.|m\.|music\.)?(youtube\.com|youtu\.be)/", url, re.IGNORECASE):
            url = "https://" + url
        else:
            raise UserError("Enter a full link, for example https://youtube.com/watch?v=...")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise UserError("That does not look like a valid web link.")
    return url


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def ensure_output_dir(value: str) -> Path:
    raw = (value or "").strip()
    if not raw:
        raise UserError("Choose an output folder.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise UserError(f"Could not create the output folder: {exc}") from exc
    if not path.is_dir():
        raise UserError("The output path is not a folder.")
    probe = path / f".yt2mp3-write-test-{uuid.uuid4().hex[:8]}"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise UserError(f"The output folder is not writable: {exc}") from exc
    return path.resolve()


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def auth_args(use_account: bool, browser: str, profile: str, cookies_file: str) -> list[str]:
    cookie_path = (cookies_file or "").strip()
    if cookie_path:
        path = Path(cookie_path).expanduser()
        if not path.is_file():
            raise UserError("The cookies file could not be found. Check the path in Account settings.")
        return ["--cookies", str(path)]
    if use_account:
        selected = (browser or "chrome").strip().lower()
        if selected not in BROWSER_CHOICES:
            raise UserError("Choose a supported browser for account access.")
        spec = selected
        profile_name = (profile or "").strip()
        if profile_name:
            spec += ":" + profile_name
        return ["--cookies-from-browser", spec]
    return []


def probe_url(url: str, playlist: bool, use_account: bool, browser: str, profile: str, cookies_file: str) -> dict[str, Any]:
    command = ytdlp_command() + [
        "--no-warnings",
        "--no-color",
        "--dump-single-json",
        "--skip-download",
        "--ffmpeg-location",
        FFMPEG_PATH,
    ]
    if playlist:
        command += ["--yes-playlist", "--flat-playlist", "--playlist-end", "100"]
    else:
        command += ["--no-playlist"]
    command += auth_args(use_account, browser, profile, cookies_file)
    command.append(url)

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=75,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise UserError("YouTube took too long to answer. Check the link and try again.") from exc
    except OSError as exc:
        raise UserError(f"Could not start yt-dlp: {exc}") from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip()
        raise UserError(friendly_error(message))

    try:
        info = json.loads(result.stdout)
    except ValueError as exc:
        raise UserError("yt-dlp returned an unexpected response. Try updating it.") from exc

    entries = info.get("entries") or []
    if not isinstance(entries, list):
        entries = []
    is_playlist = info.get("_type") == "playlist" or bool(entries and info.get("_type") != "url")
    count = info.get("playlist_count")
    if not isinstance(count, int) or count < 1:
        count = len(entries) if entries else 0

    thumbnail = info.get("thumbnail")
    if not thumbnail and entries:
        thumbnail = entries[0].get("thumbnail") if isinstance(entries[0], dict) else None
    if thumbnail and not re.match(r"^https?://", str(thumbnail), re.IGNORECASE):
        thumbnail = None

    duration = info.get("duration")
    if not isinstance(duration, (int, float)):
        duration = None

    preview_entries = []
    for entry in entries[:5]:
        if not isinstance(entry, dict):
            continue
        preview_entries.append(
            {
                "title": clean_text(entry.get("title") or "Untitled", 180),
                "duration": entry.get("duration") if isinstance(entry.get("duration"), (int, float)) else None,
            }
        )

    return {
        "url": info.get("webpage_url") or url,
        "id": info.get("id") or "",
        "title": clean_text(info.get("title") or "Untitled", 240),
        "uploader": clean_text(info.get("uploader") or info.get("channel") or "", 160),
        "duration": duration,
        "thumbnail": thumbnail,
        "is_playlist": is_playlist,
        "playlist_count": count if is_playlist else 1,
        "entries": preview_entries,
        "extractor": clean_text(info.get("extractor_key") or info.get("extractor") or "", 80),
    }


class JobManager:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.order: list[str] = []
        self.queue: Queue[str | None] = Queue()
        self.settings = self._load_settings()
        self.history = self._load_history()
        self._cleanup_stale_temp_dirs()
        self._stop = False
        self.worker = threading.Thread(target=self._worker_loop, name="yt2mp3-worker", daemon=True)
        self.worker.start()

    def _load_settings(self) -> dict[str, Any]:
        loaded = load_json(SETTINGS_FILE, {})
        settings = dict(DEFAULT_SETTINGS)
        if isinstance(loaded, dict):
            for key in settings:
                if key in loaded:
                    settings[key] = loaded[key]
        try:
            settings["output_dir"] = str(ensure_output_dir(str(settings["output_dir"])))
        except UserError:
            settings["output_dir"] = str(DEFAULT_OUTPUT_DIR)
        if settings.get("quality") not in QUALITY_CHOICES:
            settings["quality"] = "320K"
        if settings.get("browser") not in BROWSER_CHOICES:
            settings["browser"] = "chrome"
        for key in ("embed_metadata", "embed_thumbnail", "playlist", "use_account"):
            settings[key] = as_bool(settings.get(key), DEFAULT_SETTINGS[key])
        for key in ("browser_profile", "cookies_file"):
            settings[key] = str(settings.get(key) or "").strip()
        return settings

    def _load_history(self) -> list[dict[str, Any]]:
        loaded = load_json(HISTORY_FILE, [])
        if not isinstance(loaded, list):
            return []
        history = []
        for item in loaded[:200]:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path:
                continue
            history.append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex[:10]),
                    "path": path,
                    "title": clean_text(item.get("title") or Path(path).stem, 240),
                    "uploader": clean_text(item.get("uploader") or "", 160),
                    "size": int(item.get("size") or 0),
                    "completed_at": str(item.get("completed_at") or now_iso()),
                    "url": str(item.get("url") or ""),
                    "quality": str(item.get("quality") or ""),
                    "thumbnail": item.get("thumbnail") if isinstance(item.get("thumbnail"), str) else "",
                }
            )
        return history

    def save_settings(self) -> None:
        save_json(SETTINGS_FILE, self.settings)

    def save_history(self) -> None:
        save_json(HISTORY_FILE, self.history[:200])

    def update_settings(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            next_settings = dict(self.settings)
            if "output_dir" in data:
                next_settings["output_dir"] = str(ensure_output_dir(str(data.get("output_dir") or "")))
            if "quality" in data:
                quality = str(data.get("quality") or "").upper()
                if quality not in QUALITY_CHOICES:
                    raise UserError("Choose a valid MP3 quality.")
                next_settings["quality"] = quality
            if "browser" in data:
                browser = str(data.get("browser") or "").lower()
                if browser not in BROWSER_CHOICES:
                    raise UserError("Choose a supported browser.")
                next_settings["browser"] = browser
            if "browser_profile" in data:
                next_settings["browser_profile"] = str(data.get("browser_profile") or "").strip()[:120]
            if "cookies_file" in data:
                next_settings["cookies_file"] = str(data.get("cookies_file") or "").strip()[:1000]
            if "playlist" in data:
                next_settings["playlist"] = as_bool(data.get("playlist"))
            if "use_account" in data:
                next_settings["use_account"] = as_bool(data.get("use_account"))
            if "embed_metadata" in data:
                next_settings["embed_metadata"] = as_bool(data.get("embed_metadata"))
            if "embed_thumbnail" in data:
                next_settings["embed_thumbnail"] = as_bool(data.get("embed_thumbnail"))
            self.settings = next_settings
            self.save_settings()
            return dict(self.settings)

    def options_from(self, data: dict[str, Any]) -> dict[str, Any]:
        settings = self.settings
        quality = str(data.get("quality") or settings["quality"]).upper()
        if quality not in QUALITY_CHOICES:
            raise UserError("Choose a valid MP3 quality.")
        output_dir = str(data.get("output_dir") or settings["output_dir"])
        return {
            "quality": quality,
            "output_dir": str(ensure_output_dir(output_dir)),
            "embed_metadata": as_bool(data.get("embed_metadata"), settings["embed_metadata"]),
            "embed_thumbnail": as_bool(data.get("embed_thumbnail"), settings["embed_thumbnail"]),
            "playlist": as_bool(data.get("playlist"), settings["playlist"]),
            "use_account": as_bool(data.get("use_account"), settings["use_account"]),
            "browser": str(data.get("browser") or settings["browser"]).lower(),
            "browser_profile": str(data.get("browser_profile") or settings["browser_profile"]).strip(),
            "cookies_file": str(data.get("cookies_file") or settings["cookies_file"]).strip(),
        }

    def create_job(self, data: dict[str, Any]) -> dict[str, Any]:
        url = normalize_url(str(data.get("url") or ""))
        options = self.options_from(data)
        job_id = uuid.uuid4().hex[:10]
        job: dict[str, Any] = {
            "id": job_id,
            "url": url,
            "title": "Preparing...",
            "uploader": "",
            "duration": None,
            "thumbnail": "",
            "status": "queued",
            "stage": "Queued",
            "progress": 0.0,
            "message": "",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "started_at": None,
            "finished_at": None,
            "quality": options["quality"],
            "output_dir": options["output_dir"],
            "playlist": options["playlist"],
            "item_index": 0,
            "item_count": 0,
            "path": "",
            "error_detail": "",
            "cancel_requested": False,
            "use_account": options["use_account"],
            "browser": options["browser"],
            "browser_profile": options["browser_profile"],
            "cookies_file": options["cookies_file"],
            "embed_metadata": options["embed_metadata"],
            "embed_thumbnail": options["embed_thumbnail"],
            "_proc": None,
            "_last_error": "",
            "_done_paths": [],
        }
        with self.lock:
            self.jobs[job_id] = job
            self.order.append(job_id)
            self.queue.put(job_id)
        return self.public_job(job)

    def public_job(self, job: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            result = {key: value for key, value in job.items() if not key.startswith("_")}
            result["file_count"] = len(job.get("_done_paths") or [])
            return json.loads(json.dumps(result, ensure_ascii=False))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            jobs = [self.public_job(self.jobs[job_id]) for job_id in self.order if job_id in self.jobs]
            history = []
            for item in self.history[:60]:
                entry = dict(item)
                entry["exists"] = Path(entry["path"]).is_file()
                history.append(entry)
            total_bytes = sum(int(item.get("size") or 0) for item in self.history)
            today = datetime.now().astimezone().date()
            today_count = 0
            for item in self.history:
                try:
                    stamp = str(item.get("completed_at") or "").replace("Z", "+00:00")
                    if datetime.fromisoformat(stamp).astimezone().date() == today:
                        today_count += 1
                except (ValueError, TypeError):
                    continue
            return {
                "settings": dict(self.settings),
                "jobs": jobs,
                "history": history,
                "stats": {
                    "completed": len(self.history),
                    "total_bytes": total_bytes,
                    "today": today_count,
                    "active": sum(1 for job in jobs if job["status"] in {"queued", "running"}),
                },
                "app": {"name": APP_NAME, "version": APP_VERSION, "port": PORT},
                "ffmpeg": {"ready": Path(FFMPEG_PATH).is_file(), "version": "9.0.2"},
            }

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                raise UserError("That job no longer exists.")
            if job["status"] in {"completed", "failed", "canceled", "partial"}:
                return self.public_job(job)
            job["cancel_requested"] = True
            job["stage"] = "Canceling..."
            job["updated_at"] = now_iso()
            process = job.get("_proc")
        if process is not None:
            self._kill_process(process)
        else:
            with self.lock:
                if job["status"] == "queued":
                    job["status"] = "canceled"
                    job["stage"] = "Canceled"
                    job["finished_at"] = now_iso()
        return self.public_job(job)

    def retry_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            old = self.jobs.get(job_id)
            if not old:
                raise UserError("That job no longer exists.")
            payload = {
                "url": old["url"],
                "quality": old["quality"],
                "output_dir": old["output_dir"],
                "embed_metadata": old["embed_metadata"],
                "embed_thumbnail": old["embed_thumbnail"],
                "playlist": old["playlist"],
                "use_account": old.get("use_account", False),
                "browser": old.get("browser", "chrome"),
                "browser_profile": old.get("browser_profile", ""),
                "cookies_file": old.get("cookies_file", ""),
            }
        return self.create_job(payload)

    def clear_finished(self) -> None:
        with self.lock:
            keep_ids = [
                job_id
                for job_id in self.order
                if self.jobs[job_id]["status"] in {"queued", "running"}
            ]
            self.order = keep_ids
            self.jobs = {job_id: self.jobs[job_id] for job_id in keep_ids}

    def clear_history(self) -> None:
        with self.lock:
            self.history = []
            self.save_history()

    def _worker_loop(self) -> None:
        while not self._stop:
            job_id = self.queue.get()
            if job_id is None:
                return
            with self.lock:
                job = self.jobs.get(job_id)
                if not job or job.get("cancel_requested"):
                    if job:
                        job["status"] = "canceled"
                        job["stage"] = "Canceled"
                        job["finished_at"] = now_iso()
                    continue
            try:
                self._run_job(job_id)
            except Exception as exc:  # Keep the worker alive even if a job explodes.
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job:
                        job["status"] = "failed"
                        job["stage"] = "Failed"
                        job["message"] = friendly_error(str(exc))
                        job["finished_at"] = now_iso()
                        job["updated_at"] = now_iso()
                self._cleanup_temp(job_id)
            finally:
                self.queue.task_done()

    def _update(self, job_id: str, **fields: Any) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job.update(fields)
            job["updated_at"] = now_iso()

    def _run_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            if job.get("cancel_requested"):
                job["status"] = "canceled"
                job["stage"] = "Canceled"
                job["finished_at"] = now_iso()
                return
            job["status"] = "running"
            job["stage"] = "Reading video info"
            job["started_at"] = now_iso()
            job["updated_at"] = now_iso()
            url = job["url"]
            output_dir = Path(job["output_dir"])
            playlist = bool(job["playlist"])
            use_account = bool(job["use_account"])
            browser = job["browser"]
            profile = job["browser_profile"]
            cookies_file = job["cookies_file"]

        try:
            info = probe_url(url, playlist, use_account, browser, profile, cookies_file)
        except UserError as exc:
            self._fail(job_id, str(exc))
            return

        self._update(
            job_id,
            title=info["title"],
            uploader=info["uploader"],
            duration=info["duration"],
            thumbnail=info["thumbnail"],
            playlist=bool(info["is_playlist"]),
            item_count=info["playlist_count"] if info["is_playlist"] else 1,
            stage="Preparing download",
        )

        with self.lock:
            job = self.jobs.get(job_id)
            if job and job.get("cancel_requested"):
                job["status"] = "canceled"
                job["stage"] = "Canceled"
                job["finished_at"] = now_iso()
                return

        temp_dir = output_dir / ".yt2mp3-tmp" / job_id
        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._fail(job_id, f"Could not create a temporary download folder: {exc}")
            return
        with self.lock:
            self.jobs[job_id]["_temp_dir"] = str(temp_dir)

        command = self._build_command(job_id)
        started = time.time()
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except OSError as exc:
            self._fail(job_id, f"Could not start yt-dlp: {exc}")
            return

        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                job["_proc"] = process
                if job.get("cancel_requested"):
                    self._kill_process(process)

        tail: list[str] = []
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)
            self._handle_line(job_id, line)

        return_code = process.wait()
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["_proc"] = None
            cancel_requested = bool(job.get("cancel_requested"))
            last_error = str(job.get("_last_error") or "")
            done_paths = list(job.get("_done_paths") or [])

        if cancel_requested:
            self._cleanup_temp(job_id)
            self._update(job_id, status="canceled", stage="Canceled", finished_at=now_iso())
            return

        if not done_paths:
            done_paths = self._find_recent_mp3s(temp_dir, started)
            with self.lock:
                job = self.jobs.get(job_id)
                if job:
                    job["_done_paths"] = done_paths

        if return_code != 0:
            message = friendly_error(last_error or "\n".join(tail[-8:]))
            if done_paths:
                self._complete(job_id, done_paths, partial=True, message=message)
            else:
                self._fail(job_id, message)
            return

        if not done_paths:
            self._fail(job_id, "The download finished, but no MP3 file was produced.")
            return

        self._complete(job_id, done_paths, partial=False)

    def _build_command(self, job_id: str) -> list[str]:
        with self.lock:
            job = self.jobs[job_id]
            args = ytdlp_command() + [
                "--no-color",
                "--newline",
                "--progress",
                "--ffmpeg-location",
                FFMPEG_PATH,
                "--windows-filenames",
                "--trim-filenames",
                "180",
                "--concurrent-fragments",
                "4",
                "--retries",
                "3",
                "--fragment-retries",
                "3",
                "--socket-timeout",
                "20",
                "-f",
                "bestaudio/best",
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                job["quality"],
                "--no-overwrites",
                "-o",
                str(Path(job.get("_temp_dir") or job["output_dir"]) / "%(title)s.%(ext)s"),
                "--print",
                f"after_move:{DONE_PREFIX}%(filepath)s",
                "--progress-template",
                "download:__PROGRESS__%(progress._percent_str)s|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.speed)s|%(progress.eta)s",
            ]
            if job["embed_metadata"]:
                args.append("--embed-metadata")
            if job["embed_thumbnail"]:
                args += ["--embed-thumbnail", "--convert-thumbnails", "jpg"]
            if job["playlist"]:
                args += ["--yes-playlist", "--sleep-requests", "0.6"]
            else:
                args.append("--no-playlist")
            args += auth_args(
                bool(job["use_account"]),
                str(job["browser"]),
                str(job["browser_profile"]),
                str(job["cookies_file"]),
            )
            args.append(job["url"])
            return args

    def _handle_line(self, job_id: str, line: str) -> None:
        progress_match = PROGRESS_RE.match(line)
        if progress_match:
            self._apply_progress(job_id, progress_match.group(1))
            return

        if line.startswith(DONE_PREFIX):
            path = line[len(DONE_PREFIX):].strip().strip('"')
            if path:
                with self.lock:
                    job = self.jobs.get(job_id)
                    if job is not None:
                        paths = job.setdefault("_done_paths", [])
                        if path not in paths:
                            paths.append(path)
                        job["path"] = path
            return

        if line.startswith("ERROR:") or line.startswith("ERROR "):
            with self.lock:
                job = self.jobs.get(job_id)
                if job is not None:
                    job["_last_error"] = line
            return

        item_match = re.search(r"\[download\] Downloading item (\d+) of (\d+)", line)
        if item_match:
            with self.lock:
                job = self.jobs.get(job_id)
                if job is not None:
                    job["item_index"] = int(item_match.group(1))
                    job["item_count"] = int(item_match.group(2))
                    job["stage"] = f"Downloading {job['item_index']} of {job['item_count']}"
            return

        if line.startswith("[download] Destination:"):
            self._update(job_id, stage="Downloading audio")
            return
        if line.startswith("[ExtractAudio]"):
            self._update(job_id, stage="Converting to MP3", progress=99.0)
            return
        if line.startswith("[Metadata]"):
            self._update(job_id, stage="Writing tags")
            return
        if line.startswith("[EmbedThumbnail]"):
            self._update(job_id, stage="Embedding cover art")
            return
        if line.startswith("[ThumbnailsConvertor]"):
            self._update(job_id, stage="Preparing cover art")
            return
        if line.startswith("[youtube]") and "Downloading" in line:
            self._update(job_id, stage="Fetching audio stream")

    def _apply_progress(self, job_id: str, payload: str) -> None:
        parts = payload.split("|")
        percent: float | None = None
        if parts:
            token = parts[0].strip().replace("%", "")
            try:
                percent = float(token)
            except ValueError:
                percent = None
        if percent is None and len(parts) >= 3:
            try:
                downloaded = float(parts[1])
                total = float(parts[2])
                if total > 0:
                    percent = downloaded / total * 100
            except (ValueError, TypeError):
                percent = None
        if percent is None:
            return

        speed = None
        eta = ""
        if len(parts) >= 4:
            try:
                speed = float(parts[3])
            except (TypeError, ValueError):
                speed = None
        if len(parts) >= 5:
            eta = parts[4].strip()
            if eta.upper() in {"NA", "N/A", "UNKNOWN", "NONE"}:
                eta = ""

        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            index = max(1, int(job.get("item_index") or 1))
            count = max(1, int(job.get("item_count") or 1))
            overall = ((index - 1) + max(0.0, min(100.0, percent)) / 100.0) / count * 100.0
            job["progress"] = round(min(99.4, overall), 1)
            job["stage"] = f"Downloading {index} of {count}" if count > 1 else "Downloading audio"
            if speed and speed > 0:
                job["speed"] = speed
            if eta:
                job["eta"] = eta
            else:
                job.pop("eta", None)
            job["updated_at"] = now_iso()

    def _find_recent_mp3s(self, output_dir: Path, started: float) -> list[str]:
        try:
            candidates = [
                path
                for path in output_dir.glob("*.mp3")
                if path.is_file() and path.stat().st_mtime >= started - 5
            ]
        except OSError:
            return []
        candidates.sort(key=lambda path: path.stat().st_mtime)
        return [str(path.resolve()) for path in candidates]

    def _unique_target(self, output_dir: Path, name: str) -> Path:
        target = output_dir / name
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        for index in range(2, 1000):
            candidate = output_dir / f"{stem} ({index}){suffix}"
            if not candidate.exists():
                return candidate
        return output_dir / f"{stem} ({uuid.uuid4().hex[:6]}){suffix}"

    def _cleanup_stale_temp_dirs(self) -> None:
        root = Path(self.settings["output_dir"]) / ".yt2mp3-tmp"
        if not root.is_dir():
            return
        cutoff = time.time() - 86400
        try:
            children = list(root.iterdir())
        except OSError:
            return
        for child in children:
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue
        try:
            root.rmdir()
        except OSError:
            pass

    def _remove_temp_tree(self, temp_dir: str) -> None:
        if not temp_dir:
            return
        path = Path(temp_dir)
        shutil.rmtree(path, ignore_errors=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def _cleanup_temp(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            temp_dir = str(job.get("_temp_dir") or "") if job else ""
        self._remove_temp_tree(temp_dir)

    def _complete(self, job_id: str, paths: list[str], partial: bool, message: str = "") -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            output_dir = Path(job["output_dir"])
            temp_dir = job.get("_temp_dir") or ""
            uploader = job.get("uploader") or ""
            thumbnail = job.get("thumbnail") or ""
            url = job.get("url") or ""
            quality = job.get("quality") or ""
            duration = job.get("duration")
            title = job.get("title") or ""

        resolved: list[Path] = []
        for raw in paths:
            source = Path(raw)
            if not source.is_file():
                continue
            target = output_dir / source.name
            try:
                if target.exists() and target.stat().st_size == source.stat().st_size:
                    source.unlink(missing_ok=True)
                else:
                    if target.exists():
                        target = self._unique_target(output_dir, source.name)
                    shutil.move(str(source), str(target))
                resolved.append(target.resolve())
            except OSError:
                continue

        self._remove_temp_tree(str(temp_dir or ""))
        if not resolved:
            self._fail(job_id, message or "No MP3 file was produced.")
            return

        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["status"] = "partial" if partial else "completed"
            job["stage"] = "Finished with warnings" if partial else "Done"
            job["progress"] = 100.0
            job["message"] = message
            job["finished_at"] = now_iso()
            job["updated_at"] = now_iso()
            job["path"] = str(resolved[-1])
            job["_done_paths"] = [str(path) for path in resolved]

        completed_at = now_iso()
        entries = []
        for path in resolved:
            try:
                size = path.stat().st_size
            except OSError:
                continue
            entry = {
                "id": uuid.uuid4().hex[:10],
                "path": str(path),
                "title": title if len(resolved) == 1 and title else path.stem,
                "uploader": uploader,
                "size": size,
                "completed_at": completed_at,
                "url": url,
                "quality": quality,
                "thumbnail": thumbnail if len(resolved) == 1 else "",
                "duration": duration if len(resolved) == 1 else None,
            }
            entries.append(entry)

        with self.lock:
            existing = {entry["path"] for entry in entries}
            self.history = entries + [item for item in self.history if item.get("path") not in existing]
            self.history = self.history[:200]
            self.save_history()

    def _fail(self, job_id: str, message: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return
            job["status"] = "failed"
            job["stage"] = "Failed"
            job["message"] = clean_text(message, 700)
            job["error_detail"] = clean_text(job.get("_last_error") or "", 700)
            job["finished_at"] = now_iso()
            job["updated_at"] = now_iso()
        self._cleanup_temp(job_id)

    def _kill_process(self, process: subprocess.Popen[str]) -> None:
        try:
            if IS_WINDOWS:
                result = subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=CREATE_NO_WINDOW,
                    timeout=10,
                )
                if result.returncode != 0:
                    process.terminate()
            else:
                process.terminate()
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            pass

    def stop(self) -> None:
        self._stop = True
        self.queue.put(None)


manager = JobManager()
app = Flask(
    __name__,
    static_folder=str(RESOURCE_DIR / "static"),
    template_folder=str(RESOURCE_DIR / "templates"),
)
app.config["JSON_SORT_KEYS"] = False


@app.before_request
def check_token():
    if not request.path.startswith("/api/"):
        return None
    if request.path == "/api/health":
        return None
    if request.headers.get("X-App-Token") != APP_TOKEN:
        return jsonify({"ok": False, "error": "This request did not come from the app."}), 403
    return None


@app.after_request
def add_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return render_template("index.html", token=APP_TOKEN, version=APP_VERSION)


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "name": APP_NAME, "version": APP_VERSION})


@app.post("/api/quit")
def quit_app():
    with manager.lock:
        active = [
            job["id"]
            for job in manager.jobs.values()
            if job.get("status") in {"queued", "running"}
        ]
    if active:
        return jsonify({"ok": False, "error": "Cancel active downloads before quitting."}), 409

    def stop() -> None:
        time.sleep(0.4)
        os._exit(0)

    threading.Thread(target=stop, name="yt2mp3-quit", daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/state")
def state():
    return jsonify({"ok": True, **manager.snapshot()})


@app.post("/api/settings")
def update_settings():
    data = request.get_json(silent=True) or {}
    try:
        settings = manager.update_settings(data)
        return jsonify({"ok": True, "settings": settings})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/inspect")
def inspect():
    data = request.get_json(silent=True) or {}
    try:
        url = normalize_url(str(data.get("url") or ""))
        options = manager.options_from(data)
        info = probe_url(
            url,
            options["playlist"],
            options["use_account"],
            options["browser"],
            options["browser_profile"],
            options["cookies_file"],
        )
        return jsonify({"ok": True, "info": info})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": friendly_error(str(exc))}), 500


@app.post("/api/jobs")
def create_job():
    data = request.get_json(silent=True) or {}
    try:
        job = manager.create_job(data)
        return jsonify({"ok": True, "job": job})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    try:
        return jsonify({"ok": True, "job": manager.cancel_job(job_id)})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 404


@app.post("/api/jobs/<job_id>/retry")
def retry_job(job_id: str):
    try:
        return jsonify({"ok": True, "job": manager.retry_job(job_id)})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.post("/api/jobs/clear-finished")
def clear_finished():
    manager.clear_finished()
    return jsonify({"ok": True})


@app.post("/api/history/clear")
def clear_history():
    manager.clear_history()
    return jsonify({"ok": True})


def allowed_path(raw_path: str) -> Path:
    path = Path(str(raw_path or "")).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    try:
        path = path.resolve()
    except OSError as exc:
        raise UserError("That path could not be resolved.") from exc

    roots = []
    try:
        roots.append(Path(manager.settings["output_dir"]).resolve())
    except OSError:
        pass
    for item in manager.history:
        try:
            roots.append(Path(item["path"]).resolve().parent)
        except OSError:
            continue
    if not any(path == root or root in path.parents for root in roots):
        raise UserError("That path is outside the app's download folders.")
    return path


@app.post("/api/open")
def open_path():
    data = request.get_json(silent=True) or {}
    try:
        path = allowed_path(str(data.get("path") or ""))
        if not path.exists():
            raise UserError("That file is no longer there.")
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return jsonify({"ok": True})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Could not open that path: {exc}"}), 500


@app.post("/api/reveal")
def reveal_path():
    data = request.get_json(silent=True) or {}
    try:
        path = allowed_path(str(data.get("path") or ""))
        if not path.exists():
            raise UserError("That path is no longer there.")
        if IS_WINDOWS:
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
        return jsonify({"ok": True})
    except UserError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except OSError as exc:
        return jsonify({"ok": False, "error": f"Could not reveal that path: {exc}"}), 500


@app.post("/api/open-output")
def open_output():
    try:
        path = ensure_output_dir(manager.settings["output_dir"])
        if IS_WINDOWS:
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return jsonify({"ok": True})
    except (OSError, UserError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


_dialog_lock = threading.Lock()


@app.post("/api/pick-folder")
def pick_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return jsonify({"ok": False, "error": "The folder picker is not available. Type a path instead."}), 400

    initial = manager.settings["output_dir"]
    if not Path(initial).is_dir():
        initial = str(BASE_DIR)
    try:
        with _dialog_lock:
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(parent=root, initialdir=initial, title="Choose where MP3s are saved")
            root.destroy()
        if not selected:
            return jsonify({"ok": False, "canceled": True})
        return jsonify({"ok": True, "path": selected})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"The folder picker could not open: {exc}"}), 500


def setup_frozen_logging() -> Path | None:
    if not IS_FROZEN:
        return None
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_path = DATA_DIR / "yt2mp3.log"
        stream = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = stream
        sys.stderr = stream
        return log_path
    except OSError:
        return None


def show_startup_error(message: str) -> None:
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def main() -> None:
    setup_frozen_logging()
    url = f"http://127.0.0.1:{PORT}"
    print()
    print(f"  {APP_NAME} {APP_VERSION}")
    print("  YouTube -> MP3, running locally.")
    print(f"  Open: {url}")
    print("  Press Ctrl+C to stop.")
    print()
    if os.environ.get("YT2MP3_NO_BROWSER") != "1":
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve

        serve(app, host="127.0.0.1", port=PORT, threads=8, channel_timeout=180)
    except ImportError:
        app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ytdlp":
        from yt_dlp import main as ytdlp_main

        sys.argv = [sys.argv[0]] + sys.argv[2:]
        ytdlp_main()
        raise SystemExit(0)

    try:
        main()
    except Exception:
        details = traceback.format_exc()
        log_file = setup_frozen_logging()
        if log_file:
            try:
                with open(log_file, "a", encoding="utf-8") as handle:
                    handle.write(details + "\n")
            except OSError:
                pass
        summary = details.strip().splitlines()[-1] if details.strip() else "Unknown error"
        where = f"\n\nLog: {log_file}" if log_file else ""
        show_startup_error(f"{APP_NAME} could not start.\n\n{summary}{where}")
        raise
