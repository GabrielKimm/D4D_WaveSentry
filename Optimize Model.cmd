@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" tools\optimize_model.py
pause
