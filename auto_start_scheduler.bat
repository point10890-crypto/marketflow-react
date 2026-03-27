@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul
:: ============================================================
:: MarketFlow 전체 서비스 시작
:: Flask(5001) + Cloudflare Tunnel + Scheduler + Watchdog
:: 단일 경로: C:\bitman_marketfloww
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=%PROJECT%\logs\auto_start.log

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 타임스탬프
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%:%DT:~12,2%

echo [%TS%] ========== AUTO START BEGIN ========== >> "%LOG%"

:: Pre-check
if not exist "%PYTHON%" (
    echo [%TS%] ERROR: Python not found: %PYTHON% >> "%LOG%"
    echo [ERROR] Python not found: %PYTHON%
    exit /b 1
)

:: ──────────────────────────────────────────
:: 1. Flask API (port 5001)
:: ──────────────────────────────────────────
echo [%TS%] Checking Flask... >> "%LOG%"
netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [%TS%] Flask already running >> "%LOG%"
    goto :flask_end
)

:: 포트 5001 점유 프로세스 정리
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":5001 "') do (
    taskkill /F /PID %%A >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [%TS%] Starting Flask... >> "%LOG%"
start /MIN "Flask-5001" cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" flask_app.py"

:: 포트 오픈 대기 (최대 30초)
set FLASK_OK=0
for /L %%i in (1,1,10) do (
    timeout /t 3 /nobreak >nul
    netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
    if not errorlevel 1 (
        set FLASK_OK=1
        goto :flask_check
    )
)

:flask_check
if "!FLASK_OK!"=="1" (
    echo [%TS%] Flask OK (port 5001) >> "%LOG%"
) else (
    echo [%TS%] Flask FAILED to start >> "%LOG%"
)

:flask_end

:: ──────────────────────────────────────────
:: 2. Cloudflare Named Tunnel (api.bit-man.net)
:: ──────────────────────────────────────────
echo [%TS%] Checking cloudflared... >> "%LOG%"
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | findstr /I "cloudflared" >nul
if not errorlevel 1 (
    echo [%TS%] cloudflared already running >> "%LOG%"
    goto :tunnel_end
)

echo [%TS%] Starting cloudflared Named Tunnel (bitman-api)... >> "%LOG%"
start /MIN "Cloudflared" cmd /c "cd /d %PROJECT% && cloudflared.exe tunnel run bitman-api"
timeout /t 8 /nobreak >nul
echo [%TS%] cloudflared Named Tunnel started >> "%LOG%"

:tunnel_end

:: ──────────────────────────────────────────
:: 3. Scheduler daemon — PID 파일 기반 중복 방지
:: ──────────────────────────────────────────
echo [%TS%] Checking scheduler... >> "%LOG%"
set SCHED_PID_FILE=%PROJECT%\logs\scheduler.pid
set SCHED_RUNNING=0

if exist "%SCHED_PID_FILE%" (
    set /p SC_PID=<"%SCHED_PID_FILE%"
    tasklist /FI "PID eq !SC_PID!" 2>nul | findstr /I "python" >nul
    if not errorlevel 1 (
        set SCHED_RUNNING=1
    )
)

if "!SCHED_RUNNING!"=="1" (
    echo [%TS%] Scheduler already running (PID !SC_PID!) >> "%LOG%"
    goto :sched_end
)

:: 좀비 PID 파일 정리
if exist "%SCHED_PID_FILE%" del "%SCHED_PID_FILE%" >nul 2>&1
echo [%TS%] Starting scheduler daemon... >> "%LOG%"
start /MIN "Scheduler" cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" scheduler.py --daemon"
timeout /t 8 /nobreak >nul
echo [%TS%] Scheduler started >> "%LOG%"

:sched_end

:: ──────────────────────────────────────────
:: 4. Watchdog (서비스 감시자) — PID 파일 기반 중복 방지
:: ──────────────────────────────────────────
echo [%TS%] Checking watchdog... >> "%LOG%"
set WATCHDOG_PID_FILE=%PROJECT%\logs\watchdog.pid
set WATCHDOG_RUNNING=0

if exist "%WATCHDOG_PID_FILE%" (
    set /p WD_PID=<"%WATCHDOG_PID_FILE%"
    tasklist /FI "PID eq !WD_PID!" 2>nul | findstr /I "python" >nul
    if not errorlevel 1 (
        set WATCHDOG_RUNNING=1
    )
)

if "!WATCHDOG_RUNNING!"=="1" (
    echo [%TS%] Watchdog already running (PID !WD_PID!) >> "%LOG%"
    goto :watchdog_end
)

:: PID 파일이 남아있으면 삭제 (좀비 PID)
if exist "%WATCHDOG_PID_FILE%" del "%WATCHDOG_PID_FILE%" >nul 2>&1
echo [%TS%] Starting watchdog... >> "%LOG%"
start /MIN "Watchdog" cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" watchdog.py"
echo [%TS%] Watchdog started >> "%LOG%"

:watchdog_end

echo [%TS%] ========== AUTO START END ========== >> "%LOG%"
echo.
echo [MarketFlow] All services started. Check logs\auto_start.log
exit /b 0
