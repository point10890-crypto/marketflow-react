@echo off
chcp 65001 >nul

:: ====================================
:: MarketFlow — Windows Task Scheduler 등록
:: 관리자 권한 필요 (schtasks /create)
:: ====================================

set PROJECT=C:\bitman_marketfloww

echo ========================================
echo  MarketFlow Task Scheduler Setup
echo ========================================
echo.

:: ── 관리자 권한 확인 ──
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 관리자 권한이 필요합니다.
    echo         이 파일을 우클릭 → "관리자 권한으로 실행"
    echo.
    pause
    exit /b 1
)

:: ── Task 1: MarketFlow-AutoStart (로그인 시 실행) ──
echo [1/2] Registering MarketFlow-AutoStart...

schtasks /Delete /TN "MarketFlow-AutoStart" /F >nul 2>&1

schtasks /Create ^
    /TN "MarketFlow-AutoStart" ^
    /TR "\"%PROJECT%\auto_start_scheduler.bat\"" ^
    /SC ONLOGON ^
    /DELAY 0000:30 ^
    /RL HIGHEST ^
    /F

if errorlevel 1 (
    echo [FAIL] MarketFlow-AutoStart 등록 실패
) else (
    echo [OK]   MarketFlow-AutoStart — 로그인 시 실행 (30초 지연)
)
echo.

:: ── Task 2: MarketFlow-Watchdog (5분마다 실행) ──
echo [2/2] Registering MarketFlow-Watchdog...

schtasks /Delete /TN "MarketFlow-Watchdog" /F >nul 2>&1

schtasks /Create ^
    /TN "MarketFlow-Watchdog" ^
    /TR "\"%PROJECT%\watchdog_scheduler.bat\"" ^
    /SC MINUTE ^
    /MO 5 ^
    /RL HIGHEST ^
    /F

if errorlevel 1 (
    echo [FAIL] MarketFlow-Watchdog 등록 실패
) else (
    echo [OK]   MarketFlow-Watchdog — 5분 간격 실행
)
echo.

:: ── 등록 결과 확인 ──
echo ========================================
echo  Registered Tasks:
echo ========================================
schtasks /Query /TN "MarketFlow-AutoStart" /FO LIST 2>nul | findstr /I "TaskName Status Next"
echo.
schtasks /Query /TN "MarketFlow-Watchdog" /FO LIST 2>nul | findstr /I "TaskName Status Next"
echo.
echo ========================================
echo  Setup complete!
echo.
echo  - MarketFlow-AutoStart: PC 로그인 시 자동 시작
echo  - MarketFlow-Watchdog:  5분마다 프로세스 감시
echo.
echo  수동 확인: taskschd.msc (작업 스케줄러)
echo  수동 삭제:
echo    schtasks /Delete /TN "MarketFlow-AutoStart" /F
echo    schtasks /Delete /TN "MarketFlow-Watchdog" /F
echo ========================================
echo.
pause
