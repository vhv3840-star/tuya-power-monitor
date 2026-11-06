@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\launch.py
  goto done
)
where python >nul 2>nul
if not errorlevel 1 (
  python scripts\launch.py
  goto done
)
echo Python not found. Install Python 3.11+ from https://www.python.org/downloads/
echo Select 'Add python.exe to PATH', then run Start.cmd again.
:done
if errorlevel 1 pause
