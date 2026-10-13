@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
set TEMP=%~dp0.tmp
set TMP=%TEMP%
if not exist "%TEMP%" mkdir "%TEMP%"
".venv\Scripts\python.exe" -m pytest --basetemp=".tmp\pytest" %*
pause
