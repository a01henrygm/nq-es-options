@echo off
set "TASK=NQ-ES Options Analytics"
schtasks /Delete /TN "%TASK%" /F
if errorlevel 1 ( echo There was no autostart task to remove. ) else ( echo Autostart removed. The app will no longer start by itself. )
pause
