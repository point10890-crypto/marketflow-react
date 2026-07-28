$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$ControlLog = Join-Path $LogDir "flask_task.control.log"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutLog = Join-Path $LogDir "flask_server.$RunStamp.out.log"
$ErrLog = Join-Path $LogDir "flask_server.$RunStamp.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:HOME_SERVER = "1"
$env:FLASK_HOST = "127.0.0.1"
$env:FLASK_PORT = "5001"
$env:WERKZEUG_RUN_MAIN = $null
# The MiniPC has a dedicated scheduler.py daemon for recurring work. Keep the
# Flask process request-only so worker failures cannot take every API down.
$env:MARKETFLOW_BACKGROUND_WORKERS = "false"
# 일반 분석 워커는 끄더라도 회원 구독 만료 처리는 반드시 유지한다.
# Pro/AI Brain 만료, Pro pause 재개, D-3/D-1 알림만 수행하는 경량 스레드다.
$env:MARKETFLOW_EXPIRY_WORKERS_ENABLED = "true"
# Alpha scanning already runs in scheduler.py on the MiniPC.  Starting the
# in-process monitor here can block Flask before it binds port 5001 when the
# MiroFish auto-runner is unhealthy, so keep the API startup independent.
$env:WORKER_ALPHA_MONITOR_ENABLED = "0"
# The MiniPC serves durable JSON runs. Re-scanning legacy Excel locations on
# every /manual-stock-analysis/runs poll can block the whole Flask process.
$env:MANUAL_STOCK_ANALYSIS_AUTO_IMPORT = "0"
# Status polling must not launch thousands of Selenium scrapes implicitly.
# Operators can still start a deliberate run through the POST start endpoint.
$env:MANUAL_STOCK_ANALYSIS_AUTO_LOOP = "0"
# ...but the loop is the ONLY producer of manual-stock-analysis runs, so with
# nothing starting it the dashboard silently froze at the 2026-07-15 run. Start it
# once per Flask process instead: deliberate, not request-triggered.
$env:MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART = "true"
# Give the API health gate and normal request traffic time to settle before
# Selenium starts. The default 45s overlaps this launcher's 60s health window,
# so a large resumed scrape can starve /healthz and make Task Scheduler tear
# down an otherwise healthy Flask process.
$env:MANUAL_STOCK_ANALYSIS_LOOP_AUTOSTART_DELAY_SEC = "180"

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*flask_app.py*"
}

foreach ($proc in $existing) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) stopped stale flask_app.py pid=$($proc.ProcessId)"
    } catch {
        Add-Content -Path $ErrLog -Encoding UTF8 -Value "$(Get-Date -Format o) failed to stop pid=$($proc.ProcessId): $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 2

$portOwner = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ownerPid in $portOwner) {
    try {
        Stop-Process -Id $ownerPid -Force -ErrorAction Stop
        Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) stopped stale port 5001 pid=$ownerPid"
    } catch {
        Add-Content -Path $ErrLog -Encoding UTF8 -Value "$(Get-Date -Format o) failed to stop port pid=${ownerPid}: $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1

Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) starting flask_app.py detached via start_flask_task.ps1 stdout=$OutLog stderr=$ErrLog"

$flaskProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("flask_app.py") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) started flask_app.py pid=$($flaskProcess.Id)"

$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Seconds 2

    $current = Get-Process -Id $flaskProcess.Id -ErrorAction SilentlyContinue
    if ($null -eq $current) {
        Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask_app.py exited before health check attempt=$attempt"
        exit 1
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:5001/healthz"
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz reachable status=$($response.StatusCode)"
            $healthy = $true
            break
        }
    } catch {
        if ($attempt -eq 30) {
            Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz failed after attempts: $($_.Exception.Message)"
            exit 1
        }
    }
}

if ($healthy) {
    Wait-Process -Id $flaskProcess.Id
    Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask_app.py exited pid=$($flaskProcess.Id)"
    exit 0
}
