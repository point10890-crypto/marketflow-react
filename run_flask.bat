@echo off
REM ============================================================================
REM Legacy KIS producer instance (port 5001, loopback only).
REM
REM MiniPC runs TWO Flask instances by design (see scripts/flask_watchdog_v2.ps1
REM which health-probes and auto-restarts BOTH):
REM   - 5003 = API instance for the Cloudflare tunnel (scripts/start_flask_task.ps1)
REM            owns: expiry checkers + manual-stock-analysis scraper loop
REM   - 5001 = THIS producer instance
REM            owns: in-process workers (KIS screener / precompute / alpha monitor)
REM
REM Duplicated-worker cleanup (2026-09-02): expiry checkers and the Selenium
REM scraper loop used to start in BOTH processes (double telegram risk, double
REM Cloudflare block pressure). They are owned by the 5003 instance now, so this
REM producer explicitly disables them. FLASK_HOST pins the listener to loopback:
REM nothing on the LAN consumes 5001, and it must not be exposed.
REM ============================================================================
cd /d C:\bitman_marketfloww
set HOME_SERVER=1
set PYTHONIOENCODING=utf-8
set FLASK_HOST=127.0.0.1
set MARKETFLOW_EXPIRY_WORKERS_ENABLED=false
set MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART=false
C:\bitman_marketfloww\.venv\Scripts\python.exe flask_app.py >> C:\bitman_marketfloww\logs\flask_stdout.log 2>> C:\bitman_marketfloww\logs\flask_stderr.log
