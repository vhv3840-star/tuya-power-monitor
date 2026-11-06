@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\build_frontend.py
) else (
  python scripts\build_frontend.py
)
if errorlevel 1 pause
