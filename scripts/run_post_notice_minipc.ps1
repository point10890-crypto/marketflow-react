# Run post_notice.py on miniPC against local Flask (production)
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.UTF8Encoding]::new()
chcp 65001 | Out-Null

if (-not $env:MARKETFLOW_ADMIN_TOKEN -and -not $env:MARKETFLOW_ADMIN_PASSWORD) {
    Write-Error "MARKETFLOW_ADMIN_TOKEN 또는 MARKETFLOW_ADMIN_PASSWORD 환경변수가 필요합니다."
    exit 1
}

& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\post_notice.py --topic-file C:\bitman_marketfloww\scripts\notice_topic_20260513.txt --board notice
