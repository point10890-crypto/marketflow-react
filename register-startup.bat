@echo off
chcp 65001 >nul
title MarketFlow Startup Registration

set PROJECT=C:\bitman_marketfloww
set TASK_NAME=MarketFlow-AutoStart
set WATCHDOG_TASK=MarketFlow-Watchdog

echo ========================================
echo  MarketFlow Windows 자동 시작 등록
echo ========================================
echo.

:: ── 1) 로그인 시 자동 시작 (Task Scheduler) ──
echo [1/2] 로그인 자동 시작 등록...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

schtasks /create /tn "%TASK_NAME%" ^
  /tr "cmd /c \"cd /d %PROJECT% && start-local-deploy.bat\"" ^
  /sc ONLOGON ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /delay 0000:30 ^
  /f >nul 2>&1

if %ERRORLEVEL%==0 (
    echo    [OK] 로그인 자동 시작 등록 완료
    echo         작업 이름: %TASK_NAME%
    echo         트리거: 로그인 시 (30초 지연)
) else (
    echo    [FAIL] 등록 실패 - 관리자 권한으로 재시도 필요
)
echo.

:: ── 2) Watchdog 5분 주기 등록 ──
echo [2/2] Watchdog 5분 주기 등록...
schtasks /delete /tn "%WATCHDOG_TASK%" /f >nul 2>&1

schtasks /create /tn "%WATCHDOG_TASK%" ^
  /tr "cmd /c \"cd /d %PROJECT% && watchdog.bat\"" ^
  /sc MINUTE ^
  /mo 5 ^
  /ru "%USERNAME%" ^
  /f >nul 2>&1

if %ERRORLEVEL%==0 (
    echo    [OK] Watchdog 5분 주기 등록 완료
    echo         작업 이름: %WATCHDOG_TASK%
    echo         트리거: 매 5분마다 (Flask 헬스체크)
) else (
    echo    [FAIL] Watchdog 등록 실패
)
echo.

:: ── 결과 확인 ──
echo ========================================
echo  등록된 작업 목록:
echo ========================================
schtasks /query /tn "%TASK_NAME%" /fo LIST 2>nul | findstr /i "Task Name\|Status\|Next Run"
schtasks /query /tn "%WATCHDOG_TASK%" /fo LIST 2>nul | findstr /i "Task Name\|Status\|Next Run"
echo.

echo 등록 완료. PC 재부팅 후 자동으로 MarketFlow가 시작됩니다.
echo.
echo [수동 제거 방법]
echo   schtasks /delete /tn "%TASK_NAME%" /f
echo   schtasks /delete /tn "%WATCHDOG_TASK%" /f
echo.
pause
