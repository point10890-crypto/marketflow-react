@echo off
chcp 65001 >nul
title MarketFlow Local Deploy

set PROJECT=C:\bitman_marketfloww
set PYTHON=python
set PYTHONIOENCODING=utf-8
set NGROK_DOMAIN=nonalliterated-sunshine-unaffiliated.ngrok-free.dev

echo ========================================
echo  MarketFlow Local Deploy
echo  Flask(5001) + ngrok tunnel
echo ========================================
echo.

:: Flask 기존 프로세스 종료
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%A >nul 2>&1
)
:: ngrok 기존 프로세스 종료
taskkill /F /IM ngrok.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: [1/2] Flask 시작 (최소화 창)
echo [1/2] Flask API 시작 중 (port 5001)...
start "Flask-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && %PYTHON% flask_app.py"
timeout /t 10 /nobreak >nul

:: Flask 헬스체크
curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health > %TEMP%\flask_health.txt 2>nul
set /p FLASK_STATUS=<%TEMP%\flask_health.txt
if "%FLASK_STATUS%"=="200" (
    echo    Flask OK [HTTP 200]
) else (
    echo    Flask 실패 - Flask 창에서 에러 확인
    pause
    exit /b 1
)
echo.

:: [2/3] ngrok 터널 시작 (최소화 창)
echo [2/3] ngrok 터널 시작 중...
echo    https://%NGROK_DOMAIN%
start "ngrok-MarketFlow" /MIN cmd /c "ngrok http 5001 --domain=%NGROK_DOMAIN%"
timeout /t 5 /nobreak >nul

:: ngrok 헬스체크 (로컬 API)
curl -s http://localhost:4040/api/tunnels > %TEMP%\ngrok_check.txt 2>nul
findstr /i "ngrok-free" %TEMP%\ngrok_check.txt >nul 2>&1
if %ERRORLEVEL%==0 (
    echo    ngrok 터널 OK
) else (
    echo    ngrok 터널 확인 필요 (ngrok 창 확인)
)
echo.

:: [3/3] 스케줄러 데몬 시작 (최소화 창)
echo [3/3] 스케줄러 데몬 시작 중...
start "Scheduler-MarketFlow" /MIN cmd /c "cd /d %PROJECT% && set PYTHONIOENCODING=utf-8 && %PYTHON% scheduler.py --daemon"
timeout /t 5 /nobreak >nul

:: 스케줄러 프로세스 확인
tasklist /FI "WINDOWTITLE eq Scheduler-MarketFlow" 2>nul | findstr /i "cmd.exe" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo    스케줄러 OK
) else (
    echo    스케줄러 시작됨 (백그라운드 실행 중)
)
echo.

echo ========================================
echo  실행 중:
echo  Flask:      http://localhost:5001
echo  터널:       https://%NGROK_DOMAIN%
echo  스케줄러:   daemon mode (15:10 종가베팅 / 16:00 VCP / 04:00 US)
echo  대시보드:   https://marketflow-dashboard.point10890.workers.dev
echo ========================================
echo.
:: 최신 데이터 스냅샷 트리거 (스냅샷이 오래됐으면 GitHub Actions 재실행)
echo 최신 데이터 스냅샷 확인 중...
%PYTHON% "%PROJECT%\trigger_sync.py" --check
echo.

echo 아무 키나 누르면 대시보드 열림...
pause >nul
start https://marketflow-dashboard.point10890.workers.dev
