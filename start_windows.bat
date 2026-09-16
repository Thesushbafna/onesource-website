@echo off
setlocal
cd /d "%~dp0"
echo ONE SOURCE OS - FICTIONAL DEMO
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 app.py --demo --db data\onesource-demo.sqlite3 --open
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from python.org.
    echo Enable the PATH option, then reopen this file.
  ) else (
    python app.py --demo --db data\onesource-demo.sqlite3 --open
  )
)
pause
