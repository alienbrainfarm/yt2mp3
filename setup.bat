@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title yt2mp3 - setup

echo.
echo   yt2mp3 - local setup
echo   -------------------
echo.

where uv >nul 2>nul
if %errorlevel%==0 goto use_uv

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3.12"
) else (
  set "PYTHON_CMD=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating the local Python environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto failed
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
goto done

:use_uv
set "UV_CACHE_DIR=%CD%\.uv-cache"
if not exist ".venv\Scripts\python.exe" (
  echo Creating the local Python environment...
  uv venv .venv --python 3.12
  if errorlevel 1 goto failed
)

echo Installing dependencies...
uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
if errorlevel 1 goto failed
goto done

:done
echo.
echo   Setup complete. Double-click start.bat to launch yt2mp3.
echo.
pause
exit /b 0

:failed
echo.
echo   Setup failed. Check the messages above, then try again.
echo   If Python is missing, install Python 3.12 from python.org.
echo.
pause
exit /b 1
