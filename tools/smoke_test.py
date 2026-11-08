from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PORT = "8899"
TOKEN = "smoke-test-token"


def executable() -> Path:
    if sys.platform == "win32":
        return ROOT / "dist" / "yt2mp3" / "yt2mp3.exe"
    if sys.platform == "darwin":
        return ROOT / "dist" / "yt2mp3.app" / "Contents" / "MacOS" / "yt2mp3"
    return ROOT / "dist" / "yt2mp3" / "yt2mp3"


def fetch(path: str) -> bytes:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}")
    request.add_header("X-App-Token", TOKEN)
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.read()


def main() -> None:
    app = executable()
    if not app.is_file():
        raise SystemExit(f"Packaged app not found: {app}")

    env = os.environ.copy()
    env["YT2MP3_NO_BROWSER"] = "1"
    env["YT2MP3_TOKEN"] = TOKEN
    env["YT2MP3_PORT"] = PORT
    process = subprocess.Popen(
        [str(app)],
        cwd=str(app.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        last_error = None
        for _ in range(30):
            if process.poll() is not None:
                raise SystemExit(f"Packaged app exited early with code {process.returncode}")
            try:
                health = json.loads(fetch("/api/health"))
                state = json.loads(fetch("/api/state"))
                page = fetch("/")
                if health.get("name") != "yt2mp3":
                    raise SystemExit(f"Unexpected health response: {health}")
                if not state.get("ffmpeg", {}).get("ready"):
                    raise SystemExit("Bundled ffmpeg is not available")
                if b"<title>yt2mp3" not in page:
                    raise SystemExit("Packaged UI did not render")
                print(f"smoke test passed: {app}")
                print(f"ffmpeg: {state['ffmpeg']['ready']}")
                return
            except Exception as exc:  # Retry while the server starts.
                last_error = exc
                time.sleep(1)
        raise SystemExit(f"Packaged app did not become healthy: {last_error}")
    finally:
        if process.poll() is None:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    main()
