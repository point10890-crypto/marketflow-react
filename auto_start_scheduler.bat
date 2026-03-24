@echo off
chcp 65001 >nul

:: ====================================
:: MarketFlow Auto-Start on Login
:: Flask(5001) + ngrok + Scheduler daemon
:: ====================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=C:\bitman_service\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set NGROK_DOMAIN=nonalliterated-sunshine-unaffiliated.ngrok-free.dev
set LOG=%PROJECT%\logs\auto_start.log

:: 로그 디렉토리 생성
if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 현재 시각
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=:. " %%a in ('time /t') do set NOW=%%a:%%b

echo. >> "%LOG%"
echo ============================================ >> "%LOG%"
echo [%TODAY% %NOW%] === AUTO-START BEGIN === >> "%LOG%"
echo ============================================ >> "%LOG%"

:: ── Pre-check: Python 존재 확인 ──
if not exist "%PYTHON%" (
    echo [%TODAY% %NOW%] [ERROR] Python not found: %PYTHON% >> "%LOG%"
    exit /b 1
)

:: ── 1. Scheduler 중복 실행 방지 ──
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] Scheduler already running - skip >> "%LOG%"
    goto :check_flask
)

:: ── 2. Flask 서버 시작 (포트 5001) ──
:check_flask
netstat -ano 2>nul | findstr ":5001 " | findstr "LISTENING" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] Flask already running on port 5001 - skip >> "%LOG%"
    goto :check_ngrok
)

echo [%TODAY% %NOW%] Starting Flask API (port 5001)... >> "%LOG%"
start "Flask-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" flask_app.py"
timeout /t 12 /nobreak >nul

:: Flask 헬스체크
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\auto_flask.txt 2>nul
set /p FLASK_STATUS=<%TEMP%\auto_flask.txt
if "%FLASK_STATUS%"=="200" (
    echo [%TODAY% %NOW%] Flask started OK [HTTP 200] >> "%LOG%"
) else (
    echo [%TODAY% %NOW%] Flask start FAILED (status=%FLASK_STATUS%) >> "%LOG%"
)

:: ── 3. ngrok 터널 시작 ──
:check_ngrok
tasklist /FI "IMAGENAME eq ngrok.exe" 2>nul | findstr /I "ngrok" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] ngrok already running - skip >> "%LOG%"
    goto :start_scheduler
)

echo [%TODAY% %NOW%] Starting ngrok tunnel (%NGROK_DOMAIN%)... >> "%LOG%"
start "ngrok-MarketFlow" /MIN cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
timeout /t 6 /nobreak >nul
echo [%TODAY% %NOW%] ngrok started >> "%LOG%"

:: ── 4. Scheduler 데몬 시작 ──
:start_scheduler
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if not errorlevel 1 (
    echo [%TODAY% %NOW%] Scheduler already running - skip >> "%LOG%"
    goto :done
)

echo [%TODAY% %NOW%] Starting Scheduler daemon... >> "%LOG%"
start "Scheduler-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" scheduler.py --daemon"
timeout /t 3 /nobreak >nul
echo [%TODAY% %NOW%] Scheduler started >> "%LOG%"

:done
echo [%TODAY% %NOW%] === AUTO-START COMPLETE === >> "%LOG%"
exit /b 0
