@echo off
echo Stopping the dashboard (Python programs listening on ports 8000 to 8020)...
for /l %%p in (8000,1,8020) do (
  for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%p " ^| findstr "LISTENING"') do (
    for /f %%n in ('tasklist /FI "PID eq %%a" /NH ^| findstr /i "python"') do (
      echo Stopping python process %%a on port %%p
      taskkill /F /PID %%a >nul
    )
  )
)
echo Done. You can also close the start.bat window or press Ctrl+C in it.
pause
