@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow Watchdog (5분 간격)
:: PID 파일 기반 프로세스 감지 (Window title 사용 안 함)
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set SERVICE=C:\bitman_service
set PYTHON=%SERVICE%\.venv\Scripts\python.exe
set LOG=%PROJECT%\logs\watchdog_scheduler.log
set PIDFILE=%PROJECT%\logs\scheduler.pid

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

:: === 1. 스케줄러 프로세스 체크 (PID 파일 기반) ===
set SCHED_OK=0
if exist "%PIDFILE%" (
    set /p SCHED_PID=<"%PIDFILE%"
    wmic process where "processid='%SCHED_PID%'" get commandline 2>nul | findstr /I "scheduler" >nul
    if not errorlevel 1 set SCHED_OK=1
)

if %SCHED_OK%==0 (
    :: PID 파일 없거나 프로세스 죽음 → wmic로 직접 검색
    wmic process where "commandline like '%%scheduler.py%%'" get processid 2>nul | findstr /r "[0-9]" >nul
    if not errorlevel 1 (
        set SCHED_OK=1
    ) else (
        echo [%TODAY% %NOW%] Scheduler DOWN - restarting >> "%LOG%"
        call "%PROJECT%\start_scheduler.bat"
        echo [%TODAY% %NOW%] Scheduler restarted >> "%LOG%"
    )
)

:: === 2. Flask 서버 체크 (포트 5001) ===
netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [%TODAY% %NOW%] Flask DOWN - restarting >> "%LOG%"
    cd /d %SERVICE%
    start /MIN "" cmd /c "set PYTHONIOENCODING=utf-8 && "%PYTHON%" flask_app.py"
    timeout /t 8 /nobreak >nul
    echo [%TODAY% %NOW%] Flask restarted >> "%LOG%"
)

:: === 3. ngrok 체크 ===
tasklist /FI "IMAGENAME eq ngrok.exe" 2>nul | findstr /I "ngrok" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] ngrok DOWN - restarting >> "%LOG%"
    start /MIN "" cmd /c "ngrok http 5001 --domain=nonalliterated-sunshine-unaffiliated.ngrok-free.dev"
    timeout /t 5 /nobreak >nul
    echo [%TODAY% %NOW%] ngrok restarted >> "%LOG%"
)

exit /b 0
