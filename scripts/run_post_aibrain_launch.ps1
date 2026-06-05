$env:PYTHONIOENCODING = "utf-8"
$env:MARKETFLOW_ADMIN_TOKEN = "3:1781481465:d49dc66c103275e2a83c12e6bdbd5082"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\post_notice.py `
    --topic-file C:\bitman_marketfloww\scripts\notice_topic_aibrain_launch.txt `
    --board notice
