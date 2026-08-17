@echo off
cd /d C:\bitman_marketfloww
set HOME_SERVER=1
set PYTHONIOENCODING=utf-8
REM manual 스크래퍼 루프 부팅 자동시작 — 대시보드 접속(GET) 트리거에 의존하면
REM 무인 운영 중 Flask 재시작 시 루프가 영영 멈출 수 있다 (2026-07-25 10일 정지 재발 방지)
set MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART=true
C:\bitman_marketfloww\.venv\Scripts\python.exe flask_app.py >> C:\bitman_marketfloww\logs\flask_stdout.log 2>> C:\bitman_marketfloww\logs\flask_stderr.log
