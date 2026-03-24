@echo off
chcp 65001 >nul

set PROJECT=C:\bitman_marketfloww
set PYTHON=python
set PYTHONIOENCODING=utf-8
set NGROK_DOMAIN=nonalliterated-sunshine-unaffiliated.ngrok-free.dev
set LOG=%PROJECT%\logs\watchdog.log

:: 로그 디렉토리 생성
if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 현재 시각
for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set TODAY=%%c-%%a-%%b
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b

:: ── Flask 헬스체크 ──
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\wd_health.txt 2>nul
set /p FLASK_STATUS=<%TEMP%\wd_health.txt

if "%FLASK_STATUS%"=="200" (
    :: 정상 - 로그만 기록 (조용히)
    echo [%TODAY% %NOW%] Flask OK >> "%LOG%"
    exit /b 0
)

:: ── Flask 다운 감지 → 재시작 ──
echo [%TODAY% %NOW%] Flask DOWN (status=%FLASK_STATUS%) - 재시작 중... >> "%LOG%"

:: 기존 Flask 프로세스 종료
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%A >nul 2>&1
)
:: 기존 ngrok 종료
taskkill /F /IM ngrok.exe >nul 2>&1
timeout /t 3 /nobreak >nul

:: Flask 재시작
start "Flask-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && %PYTHON% flask_app.py"
timeout /t 12 /nobreak >nul

:: ngrok 재시작
start "ngrok-MarketFlow" /MIN cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
timeout /t 6 /nobreak >nul

:: 재시작 후 헬스체크
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\wd_health2.txt 2>nul
set /p FLASK_STATUS2=<%TEMP%\wd_health2.txt

if "%FLASK_STATUS2%"=="200" (
    echo [%TODAY% %NOW%] Flask 재시작 성공 [HTTP 200] >> "%LOG%"
    :: 텔레그램 알림 (재시작 성공)
    %PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'⚠️ MarketFlow Flask 자동 재시작\n%TODAY% %NOW%\n✅ 재시작 성공 (HTTP 200)','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
    :: 재시작 후 스냅샷 오래됐으면 즉시 재동기화
    %PYTHON% "%PROJECT%\trigger_sync.py" --check >nul 2>&1
) else (
    echo [%TODAY% %NOW%] Flask 재시작 실패! (status=%FLASK_STATUS2%) >> "%LOG%"
    :: 텔레그램 알림 (재시작 실패)
    %PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'🚨 MarketFlow Flask 재시작 실패!\n%TODAY% %NOW%\n❌ HTTP %FLASK_STATUS2%\n수동 확인 필요','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
)

:: ── ngrok 독립 헬스체크 ──
curl -s -o nul -w "%%{http_code}" -H "ngrok-skip-browser-warning: true" "https://%NGROK_DOMAIN%/api/health" > %TEMP%\wd_ngrok.txt 2>nul
set /p NGROK_STATUS=<%TEMP%\wd_ngrok.txt

if "%NGROK_STATUS%"=="200" (
    echo [%TODAY% %NOW%] ngrok OK >> "%LOG%"
) else (
    echo [%TODAY% %NOW%] ngrok DOWN (status=%NGROK_STATUS%) - 재시작 중... >> "%LOG%"
    taskkill /F /IM ngrok.exe >nul 2>&1
    timeout /t 3 /nobreak >nul
    start "ngrok-MarketFlow" /MIN cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
    timeout /t 6 /nobreak >nul
    echo [%TODAY% %NOW%] ngrok 재시작 완료 >> "%LOG%"
    %PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'⚠️ ngrok 자동 재시작\n%TODAY% %NOW%\n터널: %NGROK_DOMAIN%','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
)

:: ── 스케줄러 데몬 헬스체크 (강화) ──
set SCHED_PYTHON=C:\bitman_marketfloww\.venv\Scripts\python.exe
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
if errorlevel 1 (
    echo [%TODAY% %NOW%] Scheduler DOWN - 재시작 중... >> "%LOG%"
    start "Scheduler-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && "%SCHED_PYTHON%" scheduler.py --daemon"
    timeout /t 10 /nobreak >nul
    :: 재시작 확인
    tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /I "python" >nul
    if not errorlevel 1 (
        echo [%TODAY% %NOW%] Scheduler 재시작 성공 (missed schedule recovery 자동 실행됨) >> "%LOG%"
        :: 텔레그램 알림 (스케줄러 재시작)
        %PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'⚠️ Scheduler 자동 재시작\n%TODAY% %NOW%\n✅ 놓친 스케줄 자동 복구 포함','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
    ) else (
        echo [%TODAY% %NOW%] Scheduler 재시작 실패! >> "%LOG%"
        %PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); from dotenv import load_dotenv; load_dotenv(); t=os.getenv('TELEGRAM_BOT_TOKEN'); c=os.getenv('TELEGRAM_CHAT_ID'); requests.post(f'https://api.telegram.org/bot{t}/sendMessage', json={'chat_id':c,'text':'🚨 Scheduler 재시작 실패!\n%TODAY% %NOW%\n수동 확인 필요','parse_mode':'HTML'}, timeout=10) if t and c else None" >nul 2>&1
    )
) else (
    echo [%TODAY% %NOW%] Scheduler OK >> "%LOG%"
)

exit /b 0
