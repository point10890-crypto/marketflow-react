@echo off
chcp 65001 >nul
title BitMan MarketFlow Services

:: ====================================
:: BitMan MarketFlow 전체 서비스 자동 시작
:: Flask(5001) + Spring Boot(8080) + Next.js(4000) + Scheduler
:: ====================================

set PROJECT=C:\bitman_service
set PYTHON=%PROJECT%\.venv\Scripts\python.exe
set FRONTEND=%PROJECT%\frontend
set BACKEND=%PROJECT%\backend
set PYTHONIOENCODING=utf-8

:: ── Pre-check ──
echo ========================================
echo  BitMan MarketFlow Service Launcher
echo  Project: %PROJECT%
echo ========================================
echo.

if not exist "%PYTHON%" (
    echo [ERROR] Python not found: %PYTHON%
    pause
    exit /b 1
)

:: Check ports - kill if occupied
echo [0/4] Cleaning occupied ports...
for %%P in (5001 8080 4000) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        taskkill /F /PID %%A >nul 2>&1
    )
)
timeout /t 2 /nobreak >nul
echo       Done.
echo.

:: 1) Flask API — 독립 창 (최소화)
echo [1/4] Starting Flask API (port 5001)...
start "Flask-5001" /MIN cmd /c "cd /d %PROJECT% && %PYTHON% flask_app.py"
timeout /t 5 /nobreak >nul

:: 2) Spring Boot — 독립 창 (최소화)
echo [2/4] Starting Spring Boot (port 8080)...
start "SpringBoot-8080" /MIN cmd /c "cd /d %BACKEND% && gradlew.bat bootRun"
timeout /t 10 /nobreak >nul

:: 3) Next.js — 독립 창 (최소화)
echo [3/4] Starting Next.js (port 4000)...
start "NextJS-4000" /MIN cmd /c "cd /d %FRONTEND% && npm start"
timeout /t 8 /nobreak >nul

:: 4) Scheduler daemon — 독립 창 (최소화)
echo [4/4] Starting Scheduler daemon...
start "Scheduler" /MIN cmd /c "cd /d %PROJECT% && %PYTHON% scheduler.py --daemon"
timeout /t 3 /nobreak >nul

:: ── Health Check ──
echo.
echo [CHECK] Verifying services...
timeout /t 5 /nobreak >nul

set FLASK_OK=FAIL
set SPRING_OK=FAIL
set NEXT_OK=FAIL

curl -s -o nul -w "%%{http_code}" http://localhost:5001/api/health >%TEMP%\flask_check.txt 2>nul
set /p FLASK_STATUS=<%TEMP%\flask_check.txt
if "%FLASK_STATUS%"=="200" set FLASK_OK=OK

curl -s -o nul -w "%%{http_code}" http://localhost:8080/api/health >%TEMP%\spring_check.txt 2>nul
set /p SPRING_STATUS=<%TEMP%\spring_check.txt
if "%SPRING_STATUS%"=="200" set SPRING_OK=OK

curl -s -o nul -w "%%{http_code}" http://localhost:4000 >%TEMP%\next_check.txt 2>nul
set /p NEXT_STATUS=<%TEMP%\next_check.txt
if "%NEXT_STATUS%"=="200" set NEXT_OK=OK
if "%NEXT_STATUS%"=="308" set NEXT_OK=OK

echo.
echo ========================================
echo  BitMan MarketFlow - All Services
echo ========================================
echo  [%FLASK_OK%]  Flask:       http://localhost:5001
echo  [%SPRING_OK%]  Spring Boot: http://localhost:8080
echo  [%NEXT_OK%]  Next.js:     http://localhost:4000
echo  [OK]  Scheduler:   daemon mode
echo ========================================
