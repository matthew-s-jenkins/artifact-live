@echo off
title Artifact Live - Inventory Management System

REM Check if .env exists
if not exist ".env" (
    echo ERROR: .env file not found!
    echo Please copy .env.example to .env and configure your database settings.
    echo.
    pause
    exit /b 1
)

echo ========================================
echo   ARTIFACT LIVE
echo   Inventory Management System
echo ========================================
echo.
echo Starting server...
echo.
echo Backend API: http://localhost:5000
echo Frontend UI: http://localhost:8000
echo.
echo Press Ctrl+C to stop the server
echo ========================================
echo.

REM Start Flask backend
start "Artifact Live - Backend" /B python app.py

REM Wait a moment for backend to start
timeout /t 2 /nobreak >nul

REM Start frontend server
start "Artifact Live - Frontend" /B python -m http.server 8000

REM Open browser
timeout /t 1 /nobreak >nul
start http://localhost:8000

REM Keep window open
echo.
echo Servers are running. Close this window to stop both servers.
pause >nul
