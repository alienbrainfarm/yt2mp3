from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
WORK = ROOT / "build"
BIN = ROOT / "build_assets" / "bin"
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
FFMPEG_NAME = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"


def app_version() -> str:
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION = "([^"]+)"', text)
    if not match:
        raise SystemExit("Could not find APP_VERSION in app.py")
    return match.group(1)


def machine_label() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "arm64"
    if machine in {"x86_64", "amd64"}:
        return "x86_64"
    if machine in {"i386", "i686", "x86"}:
        return "x86"
    return machine or "unknown"


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def copy_docs(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "LICENSE", target / "LICENSE.txt")
    shutil.copy2(ROOT / "README.md", target / "README.md")
    shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", target / "THIRD_PARTY_NOTICES.md")
    licenses = target / "licenses"
    if licenses.exists():
        shutil.rmtree(licenses)
    shutil.copytree(ROOT / "licenses", licenses)


def remove_runtime_folders(target: Path) -> None:
    for name in ("data", "downloads"):
        candidate = target / name
        if candidate.exists():
            shutil.rmtree(candidate)


def zip_tree(source: Path, archive: Path, root_name: str) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                handle.write(path, Path(root_name) / path.relative_to(source))


def make_archive(source: Path, root_name: str) -> Path:
    arch = machine_label()
    if IS_WINDOWS:
        if arch == "x86_64":
            arch = "x64"
        archive = DIST / f"yt2mp3-windows-{arch}.zip"
        zip_tree(source, archive, root_name)
    elif IS_MACOS:
        archive = DIST / f"yt2mp3-macos-{arch}.zip"
        ditto = shutil.which("ditto")
        if ditto:
            if archive.exists():
                archive.unlink()
            run([ditto, "-c", "-k", "--sequesterRsrc", "--keepParent", str(source), str(archive)])
        else:
            zip_tree(source, archive, root_name)
    else:
        archive = DIST / f"yt2mp3-linux-{arch}.tar.gz"
        with tarfile.open(archive, "w:gz") as handle:
            handle.add(source, arcname=root_name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (DIST / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"archive: {archive}")
    print(f"sha256:  {digest}")
    return archive


def main() -> None:
    print(f"Building yt2mp3 {app_version()} on {sys.platform}/{machine_label()}")
    DIST.mkdir(parents=True, exist_ok=True)
    BIN.mkdir(parents=True, exist_ok=True)

    run([sys.executable, str(ROOT / "tools" / "make_icon.py")])

    import imageio_ffmpeg

    shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), BIN / FFMPEG_NAME)
    if not IS_WINDOWS:
        os.chmod(BIN / FFMPEG_NAME, 0o755)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            str(ROOT / "yt2mp3.spec"),
        ]
    )

    if IS_MACOS:
        source = DIST / "yt2mp3.app"
        if not source.is_dir():
            raise SystemExit(f"Expected app bundle not found: {source}")
        remove_runtime_folders(source)
        stage = DIST / f"yt2mp3-macos-{machine_label()}"
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)
        shutil.copytree(source, stage / "yt2mp3.app", symlinks=True)
        copy_docs(stage)
        make_archive(stage, stage.name)
    else:
        source = DIST / "yt2mp3"
        if not source.is_dir():
            raise SystemExit(f"Expected app folder not found: {source}")
        remove_runtime_folders(source)
        copy_docs(source)
        make_archive(source, "yt2mp3")


if __name__ == "__main__":
    main()
