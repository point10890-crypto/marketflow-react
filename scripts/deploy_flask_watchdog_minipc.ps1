cd C:\bitman_marketfloww
Write-Host "=== Pull latest ==="
git pull --autostash origin main 2>&1 | Select-Object -Last 5

Write-Host ""
Write-Host "=== Install Flask watchdog (requires admin) ==="
& powershell -ExecutionPolicy Bypass -File C:\bitman_marketfloww\scripts\install_flask_watchdog.ps1

Write-Host ""
Write-Host "=== Restart Flask to pick up /healthz ==="
Stop-ScheduledTask -TaskName MarketFlow-Flask -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
# Kill orphan flask procs
$flaskAppPath = 'C:\bitman_marketfloww\flask_app.py'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
    | Where-Object { $_.CommandLine -like ('*' + $flaskAppPath + '*') } `
    | ForEach-Object {
        Write-Host "Killing orphan Flask PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName MarketFlow-Flask
Write-Host "Flask restart issued, waiting 10s..."
Start-Sleep -Seconds 10

Write-Host ""
Write-Host "=== Verify /healthz responds ==="
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:5001/healthz' -TimeoutSec 5 -UseBasicParsing
    Write-Host "Status: $($resp.StatusCode), Body: $($resp.Content)"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== Trigger watchdog once ==="
Start-ScheduledTask -TaskName MarketFlow-Flask-Watchdog
Start-Sleep -Seconds 5
$info = Get-ScheduledTaskInfo -TaskName MarketFlow-Flask-Watchdog
Write-Host "Watchdog LastRun: $($info.LastRunTime), Result: $($info.LastTaskResult)"

Write-Host ""
Write-Host "=== Watchdog log tail ==="
$log = 'C:\bitman_marketfloww\logs\flask_watchdog.log'
if (Test-Path $log) {
    Get-Content $log -Tail 5 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "(no log yet — silent run is normal when healthy)"
}
