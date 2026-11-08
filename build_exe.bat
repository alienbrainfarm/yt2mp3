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

echo Building...
".venv\Scripts\python.exe" build.py
if errorlevel 1 goto failed

echo.
echo   Build complete.
echo   Output is in dist\.
echo.
pause
exit /b 0

:failed
echo.
echo   Build failed. Check the messages above.
echo.
pause
exit /b 1
