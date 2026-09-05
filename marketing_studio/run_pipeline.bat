@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
  set /p TARGET=상품 URL 또는 상품 ID 를 입력하세요: 
) else (
  set TARGET=%~1
)
python -m studio run "%TARGET%"
pause
