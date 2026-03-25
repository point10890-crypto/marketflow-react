@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow 스케줄러 데몬 시작 (단일 경로: C:\bitman_marketfloww)
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=%PROJECT%\logs\scheduler_start.log

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

:: PID 파일로 중복 실행 방지
set PIDFILE=%PROJECT%\logs\scheduler.pid
if exist "%PIDFILE%" (
    set /p OLD_PID=<"%PIDFILE%"
    tasklist /FI "PID eq %OLD_PID%" 2>nul | findstr /I "python" >nul
    if not errorlevel 1 (
        echo [%TODAY% %NOW%] Scheduler already running (PID %OLD_PID%), skip >> "%LOG%"
        exit /b 0
    )
)

echo [%TODAY% %NOW%] Starting scheduler daemon... >> "%LOG%"

cd /d %PROJECT%
start /MIN "" cmd /c "set PYTHONIOENCODING=utf-8 && "%PYTHON%" scheduler.py --daemon"

timeout /t 8 /nobreak >nul

:: PID 찾기 (scheduler.py를 실행 중인 python 프로세스)
for /f "tokens=2" %%P in ('wmic process where "commandline like '%%scheduler.py%%'" get processid 2^>nul ^| findstr /r "[0-9]"') do (
    echo %%P> "%PIDFILE%"
    echo [%TODAY% %NOW%] Scheduler started (PID %%P) >> "%LOG%"
    exit /b 0
)

echo [%TODAY% %NOW%] Scheduler failed to start! >> "%LOG%"
exit /b 1
