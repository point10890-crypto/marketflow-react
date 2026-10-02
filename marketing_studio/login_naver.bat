@echo off
chcp 65001 >nul
cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
set PYTHONIOENCODING=utf-8
echo 네이버 로그인 창을 엽니다. 브라우저에서 직접 로그인하면 세션이 data\browser_profile 에 저장됩니다.
python -m studio login
pause
