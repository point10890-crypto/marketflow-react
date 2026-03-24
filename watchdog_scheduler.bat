@echo off
chcp 65001 >nul

:: ====================================
:: MarketFlow Watchdog (5-minute interval)
:: Monitors: Scheduler + Flask + ngrok
:: ====================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=C:\bitman_service\.venv\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set NGROK_DOMAIN=nonalliterated-sunshine-unaffiliated.ngrok-free.dev
set LOG=%PROJECT%\logs\watchdog_scheduler.log

:: 로그 디렉토리 생성
if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 현재 시각
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=:. " %%a in ('time /t') do set NOW=%%a:%%b

:: Python 확인
if not exist "%PYTHON%" (
    echo [%TODAY% %NOW%] [FATAL] Python not found: %PYTHON% >> "%LOG%"
    exit /b 1
)

set RESTARTED=0

:: ── 1. Scheduler 헬스체크 ──
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] [WARN] Scheduler DOWN - restarting... >> "%LOG%"
    start "Scheduler-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" scheduler.py --daemon"
    timeout /t 3 /nobreak >nul
    echo [%TODAY% %NOW%] Scheduler restarted >> "%LOG%"
    set RESTARTED=1
) else (
    echo [%TODAY% %NOW%] Scheduler OK >> "%LOG%"
)

:: ── 2. Flask 헬스체크 (HTTP) ──
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\wd_sched_flask.txt 2>nul
set /p FLASK_STATUS=<%TEMP%\wd_sched_flask.txt

if "%FLASK_STATUS%"=="200" (
    echo [%TODAY% %NOW%] Flask OK [HTTP 200] >> "%LOG%"
    goto :check_ngrok
)

:: Flask 다운 → 재시작
echo [%TODAY% %NOW%] [WARN] Flask DOWN (status=%FLASK_STATUS%) - restarting... >> "%LOG%"

:: 기존 Flask 프로세스 종료
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%A >nul 2>&1
)
timeout /t 3 /nobreak >nul

:: Flask 재시작
start "Flask-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%PYTHON%" flask_app.py"
timeout /t 12 /nobreak >nul

:: 재시작 후 확인
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\wd_sched_flask2.txt 2>nul
set /p FLASK_STATUS2=<%TEMP%\wd_sched_flask2.txt

if "%FLASK_STATUS2%"=="200" (
    echo [%TODAY% %NOW%] Flask restarted OK [HTTP 200] >> "%LOG%"
    set RESTARTED=1
) else (
    echo [%TODAY% %NOW%] [ERROR] Flask restart FAILED (status=%FLASK_STATUS2%) >> "%LOG%"
)

:: ── 3. ngrok 헬스체크 ──
:check_ngrok
tasklist /FI "IMAGENAME eq ngrok.exe" 2>nul | findstr /I "ngrok" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] [WARN] ngrok DOWN - restarting... >> "%LOG%"
    start "ngrok-MarketFlow" /MIN cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
    timeout /t 6 /nobreak >nul
    echo [%TODAY% %NOW%] ngrok restarted >> "%LOG%"
    set RESTARTED=1
) else (
    echo [%TODAY% %NOW%] ngrok OK >> "%LOG%"
)

:: ── 4. 텔레그램 알림 (재시작 발생 시만) ──
if "%RESTARTED%"=="1" (
    "%PYTHON%" -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'[Watchdog] Service restarted\n%TODAY% %NOW%','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
)

exit /b 0
