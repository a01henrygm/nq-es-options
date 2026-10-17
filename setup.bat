@echo off
cd /d "%~dp0"
if not exist "backend\main.py" (
  echo The project files are missing. Extract the whole zip first ^(right-click the zip, Extract All^), then run this again.
  exit /b 1
)

rem ---- Find a Python that really runs. The Microsoft Store "python" shortcut does not count. ----
set "PY="
for %%v in (3.13 3.12 3.11 3.14 3.10) do (
  if not defined PY (
    set "CAND=py -%%v"
    call :test
  )
)
if not defined PY (
  set "CAND=py -3"
  call :test
)
if not defined PY (
  set "CAND=python"
  call :test
)
if not defined PY (
  for /d %%d in ("%LocalAppData%\Programs\Python\Python3*" "%ProgramFiles%\Python3*" "%ProgramFiles(x86)%\Python3*") do (
    if not defined PY (
      if exist "%%~d\python.exe" (
        set CAND="%%~d\python.exe"
        call :test
      )
    )
  )
)
if not defined PY (
  echo.
  echo No working Python was found on this PC.
  echo ^(Windows includes a Microsoft Store shortcut named "python", but that is not Python itself.^)
  echo.
  echo   1. If you downloaded the installer ^(python-3.x.x-amd64.exe^), double-click it now.
  echo      Otherwise get it from https://www.python.org/downloads/
  echo   2. On the FIRST installer screen tick "Add python.exe to PATH", then click "Install Now".
  echo   3. Wait for "Setup was successful", close this window, and double-click this file again.
  echo.
  exit /b 1
)
echo Using Python: %PY%

if not exist ".venv\Scripts\python.exe" (
  echo Creating the virtual environment ^(first run only^)...
  %PY% -m venv .venv
  if errorlevel 1 ( echo Could not create the virtual environment. & exit /b 1 )
)
call ".venv\Scripts\activate.bat"
fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if errorlevel 1 (
  echo Installing packages ^(first run, or requirements changed^)...
  if not exist logs mkdir logs
  python -m pip install --quiet --upgrade pip > logs\setup.log 2>&1
  python -m pip install --only-binary=:all: -r requirements.txt >> logs\setup.log 2>&1
  if errorlevel 1 (
    echo.
    echo Package installation failed. The last lines of logs\setup.log:
    powershell -NoProfile -Command "Get-Content logs\setup.log -Tail 12"
    echo.
    python --version
    echo If a package has "no matching distribution", your Python is too new for it.
    echo Install Python 3.12 or 3.13 from https://www.python.org/downloads/ ^(keep the current one^),
    echo delete the .venv folder inside this project, and run this file again.
    exit /b 1
  )
  copy /y requirements.txt .venv\requirements.installed >nul
)
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Created a default .env file ^(Cboe data, no key needed^).
)
exit /b 0

:test
rem Runs a tiny program and checks that it really printed PYOK, so the Store shortcut cannot pass.
del "%TEMP%\pyok.txt" >nul 2>nul
%CAND% -c "import sys; print('PYOK' if sys.version_info>=(3,9) else 'OLD')" > "%TEMP%\pyok.txt" 2>nul
findstr /x "PYOK" "%TEMP%\pyok.txt" >nul 2>nul && set "PY=%CAND%"
goto :eof
