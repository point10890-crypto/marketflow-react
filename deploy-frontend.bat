@echo off
chcp 65001 >nul
title MarketFlow Frontend Deploy

set PROJECT=C:\bitman_marketfloww
set FRONTEND=%PROJECT%\frontend-react
set PYTHON=python

echo ========================================
echo  MarketFlow Frontend Deploy
echo  Vite Build → Cloudflare Workers
echo ========================================
echo.

:: ── 빌드 ──
echo [1/2] npm run build 중...
cd /d "%FRONTEND%"
call npm run build
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] 빌드 실패 - 에러 확인 후 재시도
    pause
    exit /b 1
)
echo    빌드 OK
echo.

:: ── Cloudflare 배포 ──
echo [2/2] Cloudflare Workers 배포 중...
call npx wrangler deploy --config "%FRONTEND%\wrangler.toml" 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FAIL] Cloudflare 배포 실패
    pause
    exit /b 1
)
echo.

:: ── 텔레그램 알림 ──
%PYTHON% -c "import os,requests; os.chdir(r'%PROJECT%'); exec(open('.env').read().replace('=','=\"',1).replace('\n','\"\n') if False else None) if False else None" >nul 2>&1
%PYTHON% -c "
import os, requests
from pathlib import Path
env = {}
env_path = r'%PROJECT%\.env'
if os.path.exists(env_path):
    for line in open(env_path):
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
t = env.get('TELEGRAM_BOT_TOKEN', '')
c = env.get('TELEGRAM_CHAT_ID', '')
if t and c:
    requests.post(f'https://api.telegram.org/bot{t}/sendMessage',
        json={'chat_id': c, 'text': '🚀 MarketFlow 프론트엔드 배포 완료\nhttps://marketflow-dashboard.point10890.workers.dev', 'parse_mode': 'HTML'},
        timeout=10)
" >nul 2>&1

echo ========================================
echo  배포 완료!
echo  https://marketflow-dashboard.point10890.workers.dev
echo ========================================
echo.
echo 아무 키나 누르면 대시보드 열림...
pause >nul
start https://marketflow-dashboard.point10890.workers.dev
