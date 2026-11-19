@echo off
chcp 65001 >nul
cd /d "%~dp0program"
where python >nul 2>nul
if errorlevel 1 (
  echo [!] Python not found. Install Python 3.10+ from https://www.python.org/downloads/
  echo     and check "Add python.exe to PATH" during install. Then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo First run: installing... this takes a few minutes.
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 ( echo [!] Install failed. Check your internet connection. & pause & exit /b 1 )
)
echo Starting... the browser opens at http://127.0.0.1:5000
echo Keep this window open while you use the program. Close it to stop.
".venv\Scripts\python.exe" run.py
pause
