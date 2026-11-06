@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Start.cmd once to prepare the Python environment.
  pause
  exit /b 1
)
echo Stop the local Start.cmd server first. APP_PASSWORD is required.
".venv\Scripts\python.exe" scripts\network.py
if errorlevel 1 pause
