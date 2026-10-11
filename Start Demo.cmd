@echo off
cd /d "%~dp0"
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
  echo Run Setup.ps1 first.
  pause
  exit /b 1
)
start "WaveSentry Monitoring" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" --demo
