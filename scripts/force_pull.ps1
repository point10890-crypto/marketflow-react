cd C:\bitman_marketfloww
Write-Host "=== Removing conflicting untracked file ==="
Remove-Item C:\bitman_marketfloww\scripts\run_post_notice_minipc.ps1 -ErrorAction SilentlyContinue
Write-Host "=== git pull ==="
git pull --autostash origin main 2>&1 | Select-Object -Last 10
Write-Host ""
Write-Host "=== Verify new commit + symbol ==="
git log -1 --oneline
Select-String -Path C:\bitman_marketfloww\scheduler.py -Pattern "KR_VCP_MORNING_TIME|run_kr_vcp_morning_refresh" | ForEach-Object { "$($_.LineNumber): $($_.Line)" }
