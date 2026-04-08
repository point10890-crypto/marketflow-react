<#
.SYNOPSIS
    MarketFlow 서비스 상태 확인 (관리자 권한 불필요)
.USAGE
    > powershell -ExecutionPolicy Bypass -File .\scripts\service_status.ps1
#>

Write-Host "`n=== MarketFlow Service Status ===" -ForegroundColor Cyan

# Task Scheduler 상태
Write-Host "`n[Tasks]" -ForegroundColor Yellow
$tasks = @("MarketFlow-Flask", "MarketFlow-Scheduler", "MarketFlow-Cloudflared")
foreach ($t in $tasks) {
    $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($task) {
        $color = if ($task.State -eq "Running") { "Green" } elseif ($task.State -eq "Ready") { "Yellow" } else { "Red" }
        Write-Host "  [$($task.State.ToString().PadRight(10))] $t" -ForegroundColor $color
    } else {
        Write-Host "  [NOT FOUND ] $t" -ForegroundColor Red
    }
}

# 프로세스 상태
Write-Host "`n[Processes]" -ForegroundColor Yellow
$flask = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*flask_app.py*' }
$sched = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*scheduler.py*--daemon*' }
$cf = Get-Process -Name cloudflared -ErrorAction SilentlyContinue

Write-Host "  Flask:      $(if ($flask) { "PID $($flask[0].ProcessId)" } else { 'NOT RUNNING' })" -ForegroundColor $(if ($flask) { 'Green' } else { 'Red' })
Write-Host "  Scheduler:  $(if ($sched) { "PID $($sched[0].ProcessId)" } else { 'NOT RUNNING' })" -ForegroundColor $(if ($sched) { 'Green' } else { 'Red' })
Write-Host "  Cloudflared:$(if ($cf) { " PID $($cf[0].Id)" } else { ' NOT RUNNING' })" -ForegroundColor $(if ($cf) { 'Green' } else { 'Red' })

# 포트 확인
Write-Host "`n[Ports]" -ForegroundColor Yellow
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $tcp.Connect("127.0.0.1", 5001)
    $tcp.Close()
    Write-Host "  Port 5001: OPEN" -ForegroundColor Green
} catch {
    Write-Host "  Port 5001: CLOSED" -ForegroundColor Red
}

# 프로덕션 확인 (MarketFlow 전용 호스트만 — api.bit-man.net 은 별도 프로젝트 JUST BUY 소속이므로 점검 안 함)
Write-Host "`n[Production]" -ForegroundColor Yellow
try {
    $resp = Invoke-WebRequest -Uri "https://marketflow-api.bit-man.net/api/kr/market-gate" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  marketflow-api.bit-man.net: $($resp.StatusCode) OK" -ForegroundColor Green
} catch {
    Write-Host "  marketflow-api.bit-man.net: FAILED" -ForegroundColor Red
}

# 스케줄러 마지막 실행
Write-Host "`n[Last Runs]" -ForegroundColor Yellow
$lastRun = "C:\bitman_marketfloww\data\scheduler_last_run.json"
if (Test-Path $lastRun) {
    $d = Get-Content $lastRun | ConvertFrom-Json
    $d.PSObject.Properties | Sort-Object Name | ForEach-Object {
        Write-Host "  $($_.Name): $($_.Value)"
    }
}

Write-Host ""
