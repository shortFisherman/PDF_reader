@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".\venv\Scripts\python.exe" (
    echo [start.bat] ERROR: virtual environment not found at .\venv\Scripts\python.exe
    echo [start.bat] Create it first:
    echo [start.bat]   python -m venv venv
    echo [start.bat]   .\venv\Scripts\python.exe -m pip install -r requirements.lock
    exit /b 1
)

set "PORT5000_PIDS="
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr "LISTENING" ^| findstr ":5000 "') do (
    set "PORT5000_PIDS=!PORT5000_PIDS! %%a"
)

if defined PORT5000_PIDS (
    echo [start.bat] ERROR: port 5000 is already in use by PID^(s^):!PORT5000_PIDS!
    echo [start.bat] start.bat will NOT terminate any process.
    echo [start.bat] Inspect the listener before deciding how to proceed:
    echo [start.bat]   netstat -ano -p tcp ^| findstr ":5000 "
    echo [start.bat]   tasklist /FI "PID eq ^<pid^>"
    echo [start.bat] If the process is not this app, close it safely or start this app
    echo [start.bat] on another port; see README for commands, then retry.
    exit /b 1
)

call ".\venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [start.bat] ERROR: failed to activate virtual environment at .\venv\Scripts\activate.bat
    exit /b 1
)

python app.py
exit /b %errorlevel%
