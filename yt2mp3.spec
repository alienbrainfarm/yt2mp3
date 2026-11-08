# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH)
IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
FFMPEG_NAME = "ffmpeg.exe" if IS_WINDOWS else "ffmpeg"

datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
]
binaries = [
    (str(ROOT / "build_assets" / "bin" / FFMPEG_NAME), "bin"),
]
hiddenimports = []

# yt-dlp discovers extractors dynamically; collect its modules and data.
for package in ("yt_dlp",):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

excludes = [
    "imageio_ffmpeg",
    "PIL",
    "numpy",
    "pandas",
    "matplotlib",
    "scipy",
]
if not IS_WINDOWS:
    # Windows uses the tkinter folder dialog; macOS/Linux use native dialogs.
    excludes += ["tkinter", "_tkinter", "Tkinter"]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

icon_file = ROOT / "assets" / ("icon.ico" if IS_WINDOWS else "icon.icns")
exe_options = {}
if icon_file.exists():
    exe_options["icon"] = str(icon_file)
if IS_WINDOWS:
    exe_options["version"] = str(ROOT / "version_info.txt")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="yt2mp3",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    **exe_options,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="yt2mp3",
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="yt2mp3.app",
        icon=str(icon_file) if icon_file.exists() else None,
        bundle_identifier="com.alienbrainfarm.yt2mp3",
        info_plist={
            "CFBundleShortVersionString": "1.0.1",
            "CFBundleVersion": "1.0.1",
            "NSHighResolutionCapable": True,
        },
    )
