@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow 전체 서비스 자동 시작 (단일 경로: C:\bitman_marketfloww)
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=%PROJECT%\logs\auto_start.log

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

echo [%TODAY% %NOW%] === AUTO START BEGIN === >> "%LOG%"

:: 1. Flask 서버 (포트 5001)
netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [%TODAY% %NOW%] Starting Flask... >> "%LOG%"
    cd /d %PROJECT%
    start /MIN "" cmd /c "set PYTHONIOENCODING=utf-8 && "%PYTHON%" flask_app.py"
    timeout /t 10 /nobreak >nul
    netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
    if errorlevel 1 (
        echo [%TODAY% %NOW%] Flask FAILED >> "%LOG%"
    ) else (
        echo [%TODAY% %NOW%] Flask OK >> "%LOG%"
    )
) else (
    echo [%TODAY% %NOW%] Flask already running >> "%LOG%"
)

:: 2. Cloudflare Tunnel (localhost:5001 → 외부 접속)
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | findstr /I "cloudflared" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] Starting cloudflared tunnel... >> "%LOG%"
    start /MIN "" cmd /c "cloudflared tunnel --url http://localhost:5001 2>>"%LOG%""
    timeout /t 5 /nobreak >nul
    echo [%TODAY% %NOW%] cloudflared started >> "%LOG%"
) else (
    echo [%TODAY% %NOW%] cloudflared already running >> "%LOG%"
)

:: 3. 스케줄러
call "%PROJECT%\start_scheduler.bat"

echo [%TODAY% %NOW%] === AUTO START END === >> "%LOG%"
exit /b 0
