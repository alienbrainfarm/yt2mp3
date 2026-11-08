@echo off
setlocal
cd /d "%~dp0"
title yt2mp3 - YouTube to MP3

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo   yt2mp3 is not set up yet.
  echo   Double-click setup.bat once, then run start.bat.
  echo.
  pause
  exit /b 1
)

set "PYTHONUTF8=1"
".venv\Scripts\python.exe" app.py

if errorlevel 1 (
  echo.
  echo   yt2mp3 stopped with an error. The message above has the details.
  echo.
  pause
)
