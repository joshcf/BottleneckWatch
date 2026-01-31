@echo off
echo ========================================
echo BottleneckWatch Installation
echo ========================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python 3.10 or higher from https://python.org
    pause
    exit /b 1
)

echo Python found:
python --version
echo.

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)
echo.

REM Activate virtual environment and install dependencies
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.

echo ========================================
echo Installation complete!
echo ========================================
echo.
echo To run BottleneckWatch:
echo   - Double-click run.bat (with console window)
echo   - Double-click run_silent.bat (without console window)
echo.
echo To enable auto-start with Windows:
echo   - Right-click the tray icon ^> Settings ^> Startup
echo.
pause
