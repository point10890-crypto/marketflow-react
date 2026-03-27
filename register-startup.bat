@echo off
chcp 65001 >nul
title MarketFlow Startup Registration

set PROJECT=C:\bitman_marketfloww
set TASK_NAME=MarketFlow-AutoStart

echo ========================================
echo  MarketFlow Windows 자동 시작 등록
echo ========================================
echo.

:: ── 구 작업 정리 ──
schtasks /delete /tn "MarketFlow-Watchdog" /f >nul 2>&1
echo [정리] 구 Watchdog 작업 삭제 완료

:: ── 로그인 시 자동 시작 (Task Scheduler) ──
echo [1/1] 로그인 자동 시작 등록...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create /tn "%TASK_NAME%" /tr "%PROJECT%\auto_start_scheduler.bat" /sc ONLOGON /f

if %ERRORLEVEL%==0 (
    echo    [OK] 로그인 자동 시작 등록 완료
    echo         작업 이름: %TASK_NAME%
    echo         실행: auto_start_scheduler.bat (Flask + Tunnel + Scheduler)
) else (
    echo    [FAIL] 등록 실패 - 관리자 권한으로 재시도 필요
)
echo.

:: ── 결과 확인 ──
echo ========================================
echo  등록된 작업 목록:
echo ========================================
schtasks /query /tn "%TASK_NAME%" /fo LIST 2>nul | findstr /i "Task Name\|Status\|Next Run"
echo.

echo 등록 완료. PC 재부팅 후 자동으로 MarketFlow가 시작됩니다.
echo.
echo [수동 제거 방법]
echo   schtasks /delete /tn "%TASK_NAME%" /f
echo.
pause
