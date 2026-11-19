@echo off
chcp 65001 >nul
cd /d "%~dp0program"
if not exist ".venv\Scripts\python.exe" ( echo Run START.bat once first. & pause & exit /b 1 )
".venv\Scripts\python.exe" run.py --set-password
pause
