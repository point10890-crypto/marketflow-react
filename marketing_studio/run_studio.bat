@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [안내] 먼저 setup.bat 을 실행하세요.
  pause & exit /b 1
)
call ".venv\Scripts\activate.bat"
set PYTHONIOENCODING=utf-8
echo Marketing Studio 시작 중... 브라우저가 자동으로 열립니다. (종료: 이 창 닫기)
python -m studio serve --open
pause
