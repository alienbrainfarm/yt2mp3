@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title yt2mp3 - build Windows exe

echo.
echo   yt2mp3 - Windows build
echo   ----------------------
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)

echo Installing build tools...
where uv >nul 2>nul
if %errorlevel%==0 (
  set "UV_CACHE_DIR=%CD%\.uv-cache"
  uv pip install --python ".venv\Scripts\python.exe" -r requirements-build.txt
) else (
  ".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
)
if errorlevel 1 goto failed

echo Preparing bundled ffmpeg and icon...
if not exist "build_assets\bin" mkdir "build_assets\bin"
".venv\Scripts\python.exe" tools\make_icon.py
if errorlevel 1 goto failed

".venv\Scripts\python.exe" -c "import imageio_ffmpeg, pathlib, shutil; dst=pathlib.Path(r'build_assets/bin/ffmpeg.exe'); shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), dst); print('ffmpeg:', dst, dst.stat().st_size)"
if errorlevel 1 goto failed

echo Building yt2mp3.exe...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath dist --workpath build yt2mp3.spec
if errorlevel 1 goto failed

echo Adding licenses and docs...
if exist "dist\yt2mp3\data" rmdir /s /q "dist\yt2mp3\data"
if exist "dist\yt2mp3\downloads" rmdir /s /q "dist\yt2mp3\downloads"
copy /Y "LICENSE" "dist\yt2mp3\LICENSE.txt" >nul
copy /Y "README.md" "dist\yt2mp3\README.md" >nul
copy /Y "THIRD_PARTY_NOTICES.md" "dist\yt2mp3\THIRD_PARTY_NOTICES.md" >nul
if exist "dist\yt2mp3\licenses" rmdir /s /q "dist\yt2mp3\licenses"
xcopy "licenses" "dist\yt2mp3\licenses" /E /I /Y >nul

echo Creating release zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path 'dist\yt2mp3-windows-x64.zip') { Remove-Item 'dist\yt2mp3-windows-x64.zip' -Force }; Compress-Archive -Path 'dist\yt2mp3' -DestinationPath 'dist\yt2mp3-windows-x64.zip' -CompressionLevel Optimal"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import hashlib, pathlib; p = pathlib.Path(r'dist/yt2mp3-windows-x64.zip'); print(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name)" > "dist\SHA256SUMS.txt"
if errorlevel 1 goto failed

echo.
echo   Build complete.
echo   Folder: dist\yt2mp3\
echo   Exe:    dist\yt2mp3\yt2mp3.exe
echo   Zip:    dist\yt2mp3-windows-x64.zip
echo.
pause
exit /b 0

:failed
echo.
echo   Build failed. Check the messages above.
echo.
pause
exit /b 1
