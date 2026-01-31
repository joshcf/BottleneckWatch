@echo off
echo ========================================
echo BottleneckWatch Uninstallation
echo ========================================
echo.

REM Check if BottleneckWatch is running
tasklist /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I "pythonw.exe" >NUL
if not errorlevel 1 (
    echo WARNING: BottleneckWatch may be running.
    echo Please exit it from the system tray before uninstalling.
    echo.
)

echo This script will:
echo   1. Remove BottleneckWatch from Windows startup (if enabled)
echo   2. Delete the virtual environment
echo.
echo Your settings and historical data in %%APPDATA%%\BottleneckWatch
echo will NOT be deleted. Delete that folder manually if desired.
echo.

set /p confirm="Continue with uninstall? (y/N): "
if /i not "%confirm%"=="y" (
    echo Uninstall cancelled.
    pause
    exit /b 0
)

echo.

REM Remove from startup registry
echo Removing from Windows startup...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "BottleneckWatch" /f >nul 2>&1
if errorlevel 1 (
    echo   Auto-start was not enabled (nothing to remove)
) else (
    echo   Removed from startup
)
echo.

REM Remove virtual environment
if exist "venv" (
    echo Removing virtual environment...
    rmdir /s /q venv
    echo   Virtual environment removed
) else (
    echo   No virtual environment found
)
echo.

echo ========================================
echo Uninstallation complete!
echo ========================================
echo.
echo You can now delete the BottleneckWatch folder.
echo.
echo To also remove settings and data, delete:
echo   %%APPDATA%%\BottleneckWatch
echo.
pause
