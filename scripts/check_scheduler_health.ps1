cd C:\bitman_marketfloww
Write-Host "=== Python processes (scheduler-related) ==="
Get-Process python -ErrorAction SilentlyContinue | Select-Object Id, StartTime, @{n="HoursRunning";e={[math]::Round(((Get-Date) - $_.StartTime).TotalHours, 1)}} | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Lock file status ==="
$lock = "C:\bitman_marketfloww\data\.scheduler.lock"
if (Test-Path $lock) {
    $info = Get-Item $lock
    Write-Host "Lock exists, mtime: $($info.LastWriteTime), size: $($info.Length)"
    Get-Content $lock -ErrorAction SilentlyContinue | Select-Object -First 5 | ForEach-Object { Write-Host "  -> $_" }
} else {
    Write-Host "No lock file."
}

Write-Host ""
Write-Host "=== Latest scheduler log lines (find 11:00 morning refresh) ==="
$content = Get-Content C:\bitman_marketfloww\logs\scheduler.log -Encoding UTF8
$content | Select-String -Pattern "kr_vcp_morning|11:00|KR VCP 오전" | Select-Object -Last 20 | ForEach-Object { Write-Host "$($_.LineNumber): $($_.Line)" }
