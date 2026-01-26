@echo off
echo ============================================================
echo Artifact Live v2 - Starting Server
echo ============================================================
cd /d "%~dp0backend"
call venv\Scripts\activate

:: Launch browser after short delay (gives server time to start)
start "" cmd /c "timeout /t 2 /nobreak >nul && start chrome http://localhost:5000"

python app.py
pause
