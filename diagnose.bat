@echo off
cd /d "%~dp0"
if not exist "%~dp0setup.bat" (
  echo.
  echo This file is not inside the full project folder.
  echo If you opened it from inside the zip file, Windows only copied this one file.
  echo.
  echo   1. Close this window.
  echo   2. Right-click the zip file and choose "Extract All..." then click Extract.
  echo   3. Open the NEW extracted folder and double-click the file there.
  echo.
  pause
  exit /b 1
)
call setup.bat
if errorlevel 1 ( pause & exit /b 1 )
call ".venv\Scripts\activate.bat"
python -m backend.diagnose
pause
