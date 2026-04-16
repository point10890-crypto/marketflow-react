@echo off
cd /d C:\bitman_marketfloww
set HOME_SERVER=1
set PYTHONIOENCODING=utf-8
C:\bitman_marketfloww\.venv\Scripts\python.exe flask_app.py >> C:\bitman_marketfloww\logs\flask_stdout.log 2>> C:\bitman_marketfloww\logs\flask_stderr.log
