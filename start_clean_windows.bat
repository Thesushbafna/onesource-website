@echo off
setlocal
cd /d "%~dp0"
echo ONE SOURCE OS - EMPTY PILOT WORKSPACE
echo Read README.md before entering actual business records.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py --db data\onesource-pilot.sqlite3 --open
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from python.org.
    echo Enable the PATH option, then reopen this file.
  ) else (
    python app.py --db data\onesource-pilot.sqlite3 --open
  )
)
pause
