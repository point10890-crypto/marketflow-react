@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow 스케줄러 데몬 시작
:: Windows Task Scheduler에서 "PC 시작 시" 또는 "로그온 시" 실행
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=C:\bitman_marketfloww\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=%PROJECT%\logs\scheduler_start.log

:: 로그 디렉토리 생성
if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 현재 시각
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

:: 이미 실행 중인지 확인
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] Scheduler already running, skip >> "%LOG%"
    exit /b 0
)

echo [%TODAY% %NOW%] Starting scheduler daemon... >> "%LOG%"

:: 스케줄러 시작 (최소화 창)
start "Scheduler-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" scheduler.py --daemon"

:: 시작 확인 대기
timeout /t 5 /nobreak >nul

tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] Scheduler started successfully >> "%LOG%"
) else (
    echo [%TODAY% %NOW%] Scheduler failed to start! >> "%LOG%"
)

exit /b 0
