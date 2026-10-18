$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$ControlLog = Join-Path $LogDir "flask_task.control.log"
$PidFile = Join-Path $Root "data\flask_5003.pid"
$RunStamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutLog = Join-Path $LogDir "flask_server.$RunStamp.out.log"
$ErrLog = Join-Path $LogDir "flask_server.$RunStamp.err.log"
. (Join-Path $PSScriptRoot 'health_probe.ps1')
. (Join-Path $PSScriptRoot 'flask_process_guard.ps1')

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
$env:HOME_SERVER = "1"
$env:FLASK_HOST = "127.0.0.1"
$env:FLASK_PORT = "5003"
$env:WERKZEUG_RUN_MAIN = $null
# The MiniPC has a dedicated scheduler.py daemon for recurring work. Keep the
# Flask process request-only so worker failures cannot take every API down.
$env:MARKETFLOW_BACKGROUND_WORKERS = "false"
# 일반 분석 워커는 끄더라도 회원 구독 만료 처리는 반드시 유지한다.
# Pro/AI Brain 만료, Pro pause 재개, D-3/D-1 알림만 수행하는 경량 스레드다.
$env:MARKETFLOW_EXPIRY_WORKERS_ENABLED = "true"
# Alpha scanning already runs in scheduler.py on the MiniPC.  Starting the
# in-process monitor here can block Flask before it binds port 5003 when the
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

function Stop-TrackedFlaskTree([int]$TargetProcessId, [string]$Reason, $Snapshot) {
    if ($TargetProcessId -le 0) { return }
    try {
        # Never terminate the legacy 5001 producer merely because both entry
        # points are named flask_app.py.  Only the PID recorded by this launcher
        # or the process currently listening on the dedicated 5003 port reaches
        # this helper.
        Stop-MarketFlowPrimaryTree -Snapshot $Snapshot -Project $Root
        Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) stopped $Reason pid=$TargetProcessId"
    } catch {
        Add-Content -Path $ErrLog -Encoding UTF8 -Value "$(Get-Date -Format o) refused or failed to stop $Reason pid=${TargetProcessId}"
        throw
    }
}

$trackedProcessId = 0
if (Test-Path -LiteralPath $PidFile) {
    try { $trackedProcessId = [int](Get-Content -LiteralPath $PidFile -Raw).Trim() } catch {}
}
$portOwner = Get-NetTCPConnection -LocalPort 5003 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
$ownedIds = @(@($trackedProcessId) + @($portOwner) | Where-Object { $_ -gt 0 } | Sort-Object -Unique)
# Check every candidate before stopping any. A stale PID file or a foreign
# listener must not terminate an unrelated service or launch over it.
$candidates = @()
foreach ($ownerPid in $ownedIds) {
    $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
    if ($candidate) { $candidates += $candidate }
}
try { Assert-MarketFlowPrimaryCandidates -Candidates $candidates -Project $Root } catch {
    Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) startup refused: unverified or protected tracked PID or port 5003 owner"
    exit 1
}
foreach ($snapshot in $candidates) {
    Stop-TrackedFlaskTree -TargetProcessId $snapshot.ProcessId -Reason 'verified flask 5003 tree' -Snapshot $snapshot
}

Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

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
Set-Content -LiteralPath $PidFile -Encoding ASCII -Value $flaskProcess.Id

function Wait-FlaskStartup {
    param([int]$ProcessId, [double]$TimeoutSeconds = 60, [double]$PollSeconds = 2)
    $clock = [System.Diagnostics.Stopwatch]::StartNew()
    while ($clock.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return $false }
        $remaining = $TimeoutSeconds - $clock.Elapsed.TotalSeconds
        $probe = Invoke-BoundedHealthProbe -Uri 'http://127.0.0.1:5003/healthz' -TimeoutSeconds ([Math]::Max(0.1, [Math]::Min(3, $remaining)))
        if ($probe.healthy) { return $true }
        if ($probe.reason -in @('probe_unavailable', 'cleanup_failed')) { return $false }
        $sleepMs = [int]([Math]::Min($PollSeconds, [Math]::Max(0, $TimeoutSeconds - $clock.Elapsed.TotalSeconds)) * 1000)
        if ($sleepMs -gt 0) { Start-Sleep -Milliseconds $sleepMs }
    }
    return $false
}

$healthy = Wait-FlaskStartup -ProcessId $flaskProcess.Id
if (-not $healthy) {
    Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz failed within startup deadline pid=$($flaskProcess.Id)"
    exit 1
}
Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz reachable status=200"

if ($healthy) {
    Wait-Process -Id $flaskProcess.Id
    try {
        if ((Get-Content -LiteralPath $PidFile -Raw -ErrorAction Stop).Trim() -eq [string]$flaskProcess.Id) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        }
    } catch {}
    Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask_app.py exited pid=$($flaskProcess.Id)"
    exit 0
}
