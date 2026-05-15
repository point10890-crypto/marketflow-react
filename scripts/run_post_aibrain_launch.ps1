$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\post_notice.py `
    --topic-file C:\bitman_marketfloww\scripts\notice_topic_aibrain_launch.txt `
    --board notice
