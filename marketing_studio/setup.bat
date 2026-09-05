@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo  Marketing Studio - 초기 설치 (최초 1회)
echo ================================================
where py >nul 2>nul && (py -3.11 -m venv .venv 2>nul || py -3 -m venv .venv) || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [오류] Python 3.11+ 를 설치한 뒤 다시 실행하세요. https://www.python.org/downloads/
  pause & exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
echo.
echo [브라우저] Playwright Chromium 설치 중...
python -m playwright install chromium
if not exist ".env" copy ".env.example" ".env" >nul && echo [설정] .env 파일을 만들었습니다. API 키를 입력하세요: notepad .env
echo.
python -m studio doctor
echo.
echo 설치 완료. run_studio.bat 을 실행하세요.
pause
