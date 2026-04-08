@echo off
REM ============================================================================
REM  MarketFlow Flask auto-restart launcher
REM  Registered as Windows Task Scheduler task "MarketFlow-V1-Flask"
REM
REM  - Binds Flask to port 5001 (per INFRASTRUCTURE.md SSOT, port 5002 banned)
REM  - Cloudflare tunnel marketflow-api.bit-man.net -> http://localhost:5001
REM  - Infinite restart loop with 5s cooldown
REM  - Kills any stale process holding port 5001 before each start
REM  - All output appended to logs\v1-flask.log
REM ============================================================================

setlocal EnableDelayedExpansion

set "V1_ROOT=C:\bitman_marketfloww"
set "PYTHON=%V1_ROOT%\.venv\Scripts\python.exe"
set "LOG_DIR=%V1_ROOT%\logs"
set "LOG_FILE=%LOG_DIR%\v1-flask.log"
set "FLASK_PORT=5001"
set "PORT=5001"
set "PYTHONIOENCODING=utf-8"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

cd /d "%V1_ROOT%"

:restart_loop
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%FLASK_PORT% .*LISTENING"') do (
    echo [%date% %time%] Killing stale PID %%p on port %FLASK_PORT% >> "%LOG_FILE%"
    taskkill /F /PID %%p >nul 2>&1
)

echo [%date% %time%] Starting Flask on port %FLASK_PORT% >> "%LOG_FILE%"
"%PYTHON%" flask_app.py >> "%LOG_FILE%" 2>&1

echo [%date% %time%] flask_app.py exited with code %ERRORLEVEL% - restarting in 5s >> "%LOG_FILE%"
timeout /t 5 /nobreak >nul
goto restart_loop
