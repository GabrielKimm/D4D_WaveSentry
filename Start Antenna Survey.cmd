@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment missing. Run Setup.ps1 first.
  pause
  exit /b 1
)
start "D4D Antenna Survey" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py" --survey --survey-profile antenna_24_5 --survey-channel-mhz 20
