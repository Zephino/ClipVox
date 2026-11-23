@echo off
cd /d "%~dp0"
echo Updating the YouTube downloader...
".venv\Scripts\python.exe" -m pip install --upgrade yt-dlp
pause
