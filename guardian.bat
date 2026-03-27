@echo off
chcp 65001 >nul
:: ============================================================
:: MarketFlow Guardian — Watchdog의 감시자
:: 5분마다 watchdog heartbeat를 확인, 죽었으면 전체 재시작
:: Startup 폴더에서 부팅 시 자동 실행
:: ============================================================

set PROJECT=C:\bitman_marketfloww
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
set HEARTBEAT=%PROJECT%\logs\watchdog.heartbeat
set LOG=%PROJECT%\logs\guardian.log
set CHECK_INTERVAL=300

if not exist "%PROJECT%\logs" mkdir "%PROJECT%\logs"

:: 부팅 직후 서비스 시작 대기 (auto_start_scheduler.bat이 먼저 실행됨)
timeout /t 180 /nobreak >nul

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%
echo [%TS%] Guardian started >> "%LOG%"

:loop
:: 5분 대기
timeout /t %CHECK_INTERVAL% /nobreak >nul

:: Heartbeat 파일 존재 확인
if not exist "%HEARTBEAT%" (
    goto :restart_all
)

:: Heartbeat가 5분 이상 갱신 안됐으면 watchdog 사망 판정
"%PYTHON%" -c "import os,time,sys; t=float(open(r'%HEARTBEAT%').read().strip()); sys.exit(0 if time.time()-t < 600 else 1)" 2>nul
if errorlevel 1 (
    goto :restart_all
)

:: 정상 — 루프 계속
goto :loop

:restart_all
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%
echo [%TS%] Watchdog DEAD detected — restarting all services >> "%LOG%"

:: auto_start_scheduler.bat 호출 (Flask + Tunnel + Scheduler + Watchdog 전체 시작)
call "%PROJECT%\auto_start_scheduler.bat"

for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set DT=%%I
set TS=%DT:~0,4%-%DT:~4,2%-%DT:~6,2% %DT:~8,2%:%DT:~10,2%
echo [%TS%] All services restarted >> "%LOG%"

:: 재시작 후 3분 대기 (서비스 부팅 시간 확보)
timeout /t 180 /nobreak >nul
goto :loop
