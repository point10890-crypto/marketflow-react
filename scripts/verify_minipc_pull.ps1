cd C:\bitman_marketfloww
Write-Host "=== git status ==="
git status --short
Write-Host ""
Write-Host "=== Latest commit ==="
git log -1 --oneline
Write-Host ""
Write-Host "=== Verify new symbols in scheduler.py ==="
Select-String -Path C:\bitman_marketfloww\scheduler.py -Pattern "KR_VCP_MORNING_TIME|run_kr_vcp_morning_refresh" | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
