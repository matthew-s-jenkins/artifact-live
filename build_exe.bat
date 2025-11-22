@echo off
echo ========================================
echo Building Artifact Live Executable
echo ========================================
echo.

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

echo.
echo Building executable...
pyinstaller build_exe.spec --clean

echo.
if exist "dist\ArtifactLive.exe" (
    echo ========================================
    echo BUILD SUCCESSFUL!
    echo ========================================
    echo.
    echo Executable location: dist\ArtifactLive.exe
    echo.
    echo IMPORTANT: Don't forget to:
    echo 1. Copy your .env file to the dist folder
    echo 2. Make sure MySQL is installed and running
    echo 3. Run init_db.sql to create the database
    echo.
) else (
    echo ========================================
    echo BUILD FAILED
    echo ========================================
    echo Check the output above for errors
)

pause
