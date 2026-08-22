@echo off
setlocal

set "PROJECT_ROOT=C:\bitman_marketfloww"
set "PYTHON_EXE=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "LOG_DIR=%PROJECT_ROOT%\logs"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
cd /d "%PROJECT_ROOT%"

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "HOME_SERVER=1"

>>"%LOG_DIR%\jongga_telegram_1510.log" echo [%DATE% %TIME%] start
"%PYTHON_EXE%" -c "import scheduler; raise SystemExit(0 if scheduler.update_jongga_v2() else 1)" >>"%LOG_DIR%\jongga_telegram_1510.log" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
>>"%LOG_DIR%\jongga_telegram_1510.log" echo [%DATE% %TIME%] exit=%EXIT_CODE%

exit /b %EXIT_CODE%
