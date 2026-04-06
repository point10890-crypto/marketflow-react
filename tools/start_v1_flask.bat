@echo off
REM ============================================================================
REM  MarketFlow v1 Flask auto-restart launcher
REM  Registered as Windows Task Scheduler task "MarketFlow-V1-Flask"
REM  - Runs an infinite loop that restarts flask_app.py whenever it exits
REM  - 5-second cooldown between restarts
REM  - Kills stale port-5002 processes before each start
REM  - All output appended to logs\v1-flask.log
REM  Task Scheduler only needs to start this batch once at logon.
REM ============================================================================

setlocal

set "V1_ROOT=C:\bitman_marketfloww"
set "PYTHON=%V1_ROOT%\.venv\Scripts\python.exe"
set "LOG_DIR=%V1_ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\v1-flask.log"
set "PORT=5002"
set "PYTHONIOENCODING=utf-8"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%V1_ROOT%"

:restart_loop
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
    echo [%date% %time%] Killing stale PID %%p on port %PORT% >> "%LOG_FILE%"
    taskkill /F /PID %%p >nul 2>&1
)

echo [%date% %time%] Starting v1 Flask on port %PORT% >> "%LOG_FILE%"
"%PYTHON%" flask_app.py >> "%LOG_FILE%" 2>&1

echo [%date% %time%] flask_app.py exited with code %ERRORLEVEL% - restarting in 5s >> "%LOG_FILE%"
timeout /t 5 /nobreak >nul
goto restart_loop
