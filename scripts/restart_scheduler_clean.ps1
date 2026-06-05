cd C:\bitman_marketfloww

Write-Host "=== Identify scheduler.py process ==="
$schedProcs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*scheduler.py*--daemon*" }
foreach ($p in $schedProcs) {
    Write-Host "PID $($p.ProcessId): $($p.CommandLine)"
}

Write-Host ""
Write-Host "=== Stop MarketFlow-Scheduler task and kill scheduler.py procs ==="
Stop-ScheduledTask -TaskName MarketFlow-Scheduler -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
foreach ($p in $schedProcs) {
    try {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        Write-Host "Killed PID $($p.ProcessId)"
    } catch {
        Write-Host "Skip PID $($p.ProcessId): $_"
    }
}

Write-Host ""
Write-Host "=== Remove stale lock file ==="
$lock = "C:\bitman_marketfloww\data\.scheduler.lock"
if (Test-Path $lock) {
    Remove-Item $lock -Force
    Write-Host "Lock removed."
}

Write-Host ""
Write-Host "=== Start fresh ==="
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName MarketFlow-Scheduler
Start-Sleep -Seconds 8

Write-Host ""
Write-Host "=== Verify new schedule registered ==="
$content = Get-Content C:\bitman_marketfloww\logs\scheduler.log -Encoding UTF8 -Tail 200
$content | Select-String -Pattern "kr_vcp_morning|VCP 오전|11:00.*KR VCP|KR_VCP_MORNING_TIME" | Select-Object -Last 10 | ForEach-Object { Write-Host $_.Line }

Write-Host ""
Write-Host "=== Schedule registration log (last 50 lines) ==="
$content | Select-String -Pattern "스케줄러 시작|스케줄 등록|평일.*VCP" | Select-Object -Last 15 | ForEach-Object { Write-Host $_.Line }
