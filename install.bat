@echo off
title ClipVox setup
cd /d "%~dp0"
echo === ClipVox setup ===
where py >nul 2>nul || (echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
if not exist .venv (
  echo Creating private Python environment...
  py -3 -m venv .venv || (echo Could not create the environment. & pause & exit /b 1)
)
echo Installing parts (first time is about 1 GB, be patient)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Install failed - see messages above. & pause & exit /b 1)
echo.
echo Setup done. Double-click run.bat to start ClipVox.
pause
