@echo off
cd /d "%~dp0"
call .\venv\Scripts\activate.bat
for /f "tokens=5" %%a in ('netstat -ano -p tcp ^| findstr "LISTENING" ^| findstr ":5000 "') do taskkill /F /PID %%a 2>nul
python app.py
pause
