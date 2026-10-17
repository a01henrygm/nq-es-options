@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0start_hidden.vbs" (
  echo Run this from inside the extracted project folder, not from inside the zip.
  pause
  exit /b 1
)
set "TASK=NQ-ES Options Analytics"
schtasks /Create /TN "%TASK%" /SC ONLOGON /TR "wscript.exe \"%~dp0start_hidden.vbs\"" /F >nul
if errorlevel 1 (
  echo Could not create the scheduled task. Try right-clicking this file and choosing "Run as administrator".
  pause
  exit /b 1
)
echo.
echo Done. The app will now start by itself, with no window, every time you sign in to Windows.
echo The dashboard is then at http://127.0.0.1:8000 whenever you want to look.
echo.
echo Notes:
echo   - Your PC must be on and signed in during market hours for data to be collected.
echo   - If the PC sleeps, collection pauses and resumes when it wakes.
echo   - To stop it right now run stop.bat. To remove autostart run remove_autostart.bat.
echo.
choice /m "Start it now as well"
if errorlevel 2 goto end
schtasks /Run /TN "%TASK%" >nul
echo Started. Give it a minute, then open http://127.0.0.1:8000
:end
pause
