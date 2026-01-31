@echo off
REM Run BottleneckWatch without console window (normal usage)
cd /d "%~dp0"
start "" /B venv\Scripts\pythonw.exe main.py
