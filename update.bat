@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title yt2mp3 - update yt-dlp

if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)

echo.
echo   Updating yt-dlp. This is the part that keeps YouTube working.
echo.

where uv >nul 2>nul
if %errorlevel%==0 (
  set "UV_CACHE_DIR=%CD%\.uv-cache"
  uv pip install --upgrade --python ".venv\Scripts\python.exe" yt-dlp
) else (
  ".venv\Scripts\python.exe" -m pip install --upgrade yt-dlp
)

if errorlevel 1 (
  echo.
  echo   Update failed. Check the messages above.
) else (
  echo.
  echo   yt-dlp is up to date.
)

echo.
pause
