# MarketFlow Claw Watchdog
# Liveness guard for `python -m marketflow_claw start` (Task: MarketFlow-Claw).
# Restarts the task when data\claw\heartbeat.json is older than $StaleSeconds or the PID is gone.
# Outside market hours the loop writes an idle heartbeat every 60s, so 180s stale = really dead.

$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Project       = 'C:\bitman_marketfloww'
$HeartbeatFile = Join-Path $Project 'data\claw\heartbeat.json'
$PidFile       = Join-Path $Project 'data\claw\claw.pid'
$LogFile       = Join-Path $Project 'logs\claw_watchdog.log'
$TaskName      = 'MarketFlow-Claw'
$StaleSeconds  = 180
$AllowedHosts  = @('MINIPC-NQYLP')

function Write-Log($msg) {
    New-Item -ItemType Directory -Force (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value ("{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding UTF8
}

if (($AllowedHosts -notcontains $env:COMPUTERNAME) -and ($env:MARKETFLOW_ALLOW_CLAW -ne '1')) {
    exit 0
}

function Test-ClawAlive {
    if (-not (Test-Path $HeartbeatFile)) { return @{ Alive = $false; Reason = 'no_heartbeat_file' } }
    $age = (Get-Date) - (Get-Item $HeartbeatFile).LastWriteTime
    if ($age.TotalSeconds -gt $StaleSeconds) {
        return @{ Alive = $false; Reason = ("heartbeat_stale_{0:N0}s" -f $age.TotalSeconds) }
    }
    if (Test-Path $PidFile) {
        try {
            $pidNum = [int](Get-Content $PidFile -Raw).Trim()
            if (-not (Get-Process -Id $pidNum -ErrorAction SilentlyContinue)) {
                return @{ Alive = $false; Reason = "pid_${pidNum}_not_running" }
            }
        } catch { }
    }
    return @{ Alive = $true; Reason = 'ok' }
}

$state = Test-ClawAlive
if ($state.Alive) { exit 0 }

Write-Log ("Claw not alive: " + $state.Reason + " -> restarting task " + $TaskName)
try {
    # kill stale loop processes (only marketflow_claw, never flask/scheduler)
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'marketflow_claw start' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
    Start-ScheduledTask -TaskName $TaskName
    Write-Log "restart requested"
} catch {
    Write-Log ("restart failed: " + $_.Exception.Message)
}
