@echo off
echo ============================================================
echo Artifact Live v2 - Starting Server
echo ============================================================
cd /d "%~dp0backend"
call venv\Scripts\activate
python app.py
pause
