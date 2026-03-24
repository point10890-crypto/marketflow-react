@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow 전체 서비스 자동 시작 (PC 로그인 시)
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set SERVICE=C:\bitman_service
set PYTHON=%SERVICE%\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=%PROJECT%\logs\auto_start.log
set NGROK_DOMAIN=nonalliterated-sunshine-unaffiliated.ngrok-free.dev

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

echo [%TODAY% %NOW%] === AUTO START BEGIN === >> "%LOG%"

:: 1. Flask 서버 (포트 5001)
netstat -ano | findstr ":5001.*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [%TODAY% %NOW%] Starting Flask... >> "%LOG%"
    cd /d %SERVICE%
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

:: 2. ngrok 터널
tasklist /FI "IMAGENAME eq ngrok.exe" 2>nul | findstr /I "ngrok" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] Starting ngrok... >> "%LOG%"
    start /MIN "" cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
    timeout /t 5 /nobreak >nul
    echo [%TODAY% %NOW%] ngrok started >> "%LOG%"
) else (
    echo [%TODAY% %NOW%] ngrok already running >> "%LOG%"
)

:: 3. 스케줄러
call "%PROJECT%\start_scheduler.bat"

echo [%TODAY% %NOW%] === AUTO START END === >> "%LOG%"
exit /b 0
