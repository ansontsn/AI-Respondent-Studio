@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start.bat first to install the Python environment.
  pause
  exit /b 1
)
set PLAYWRIGHT_BROWSERS_PATH=%~dp0data\browsers
set PYTHONUTF8=1
".venv\Scripts\python.exe" -m playwright install chromium
pause
