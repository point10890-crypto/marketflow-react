cd C:\bitman_marketfloww

Write-Host "=== Stop Flask task ==="
Stop-ScheduledTask -TaskName MarketFlow-Flask -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== Find and kill all flask_app.py processes ==="
$flaskPath = "C:\bitman_marketfloww\flask_app.py"
$procs = Get-CimInstance -ClassName Win32_Process | Where-Object {
    $_.Name -eq 'python.exe' -and $_.CommandLine -like "*flask_app*"
}
foreach ($p in $procs) {
    Write-Host "Killing PID $($p.ProcessId): $($p.CommandLine)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 3

Write-Host ""
Write-Host "=== Verify port 5001 is free ==="
$tcp = Test-NetConnection -ComputerName localhost -Port 5001 -WarningAction SilentlyContinue -InformationLevel Quiet
Write-Host "Port 5001 listening: $tcp"

Write-Host ""
Write-Host "=== Start Flask task fresh ==="
Start-ScheduledTask -TaskName MarketFlow-Flask
Start-Sleep -Seconds 12

Write-Host ""
Write-Host "=== Verify Flask is responding on /healthz ==="
$retries = 0
while ($retries -lt 5) {
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:5001/healthz' -TimeoutSec 5 -UseBasicParsing
        Write-Host "OK: Status=$($resp.StatusCode), Body=$($resp.Content)"
        break
    } catch {
        $retries++
        Write-Host "Attempt $retries failed: $($_.Exception.Message)"
        Start-Sleep -Seconds 3
    }
}

Write-Host ""
Write-Host "=== /api/health for comparison ==="
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:5001/api/health' -TimeoutSec 5 -UseBasicParsing
    Write-Host "Status=$($resp.StatusCode), version field present: $($resp.Content -match 'version')"
} catch {
    Write-Host "FAILED: $($_.Exception.Message)"
}
