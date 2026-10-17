@echo off
rem Starts the app without opening a browser or a visible window. Used by the autostart task.
cd /d "%~dp0"
call setup.bat >nul 2>&1
if errorlevel 1 exit /b 1
call ".venv\Scripts\activate.bat"
if not exist logs mkdir logs
python -m backend.main --no-browser >> logs\background.log 2>&1
