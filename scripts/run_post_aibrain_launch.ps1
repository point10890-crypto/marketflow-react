$env:PYTHONIOENCODING = "utf-8"
# 운영 admin 토큰을 커밋하지 않는다 — 실행 전 셸에서 설정: $env:MARKETFLOW_ADMIN_TOKEN = "..."
if (-not $env:MARKETFLOW_ADMIN_TOKEN) {
    Write-Error "MARKETFLOW_ADMIN_TOKEN env var required"
    exit 1
}
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
& C:\bitman_marketfloww\.venv\Scripts\python.exe C:\bitman_marketfloww\scripts\post_notice.py `
    --topic-file C:\bitman_marketfloww\scripts\notice_topic_aibrain_launch.txt `
    --board notice
