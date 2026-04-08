# MarketFlow Scheduler Watchdog
# ------------------------------------------------------------------
# Purpose : Restart scheduler.py --daemon when its heartbeat goes stale
#           or its PID is dead. Send a Telegram alert on every restart so
#           the user knows the daemon was rotting and is now back.
#
# Schedule: Run every 5 minutes via Task Scheduler
#           (MarketFlow-Scheduler-Watchdog).
#
# Why this exists:
#   The scheduler daemon can hang (alive process, frozen loop) without
#   any external indicator — autostart.vbs only checks if the process
#   *exists*, which is not the same as *working*. The heartbeat file
#   solves liveness by requiring the daemon to touch it on every loop.
# ------------------------------------------------------------------

$ErrorActionPreference = 'Continue'

$Project       = 'C:\bitman_marketfloww'
$Python        = Join-Path $Project '.venv\Scripts\python.exe'
$Scheduler     = Join-Path $Project 'scheduler.py'
$HeartbeatFile = Join-Path $Project 'data\scheduler_heartbeat.json'
$PidFile       = Join-Path $Project 'logs\scheduler.pid'
$LogFile       = Join-Path $Project 'logs\scheduler_watchdog.log'
$StaleSeconds  = 180   # heartbeat older than 3 min = dead/hung

function Write-Log($msg) {
    $line = "{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Send-Telegram($msg) {
    try {
        $envFile = Join-Path $Project '.env'
        if (-not (Test-Path $envFile)) { return }
        $token = $null; $chat = $null
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^TELEGRAM_BOT_TOKEN=(.+)$') { $token = $Matches[1].Trim() }
            if ($_ -match '^TELEGRAM_CHAT_ID=(.+)$')   { $chat  = $Matches[1].Trim() }
        }
        if (-not $token -or -not $chat) { return }
        $body = @{
            chat_id    = $chat
            text       = $msg
            parse_mode = 'HTML'
        }
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                          -Method Post -Body $body -TimeoutSec 10 | Out-Null
    } catch {
        Write-Log ("Telegram send failed: " + $_.Exception.Message)
    }
}

function Test-DaemonAlive {
    # 1) heartbeat file must exist and be fresh
    if (-not (Test-Path $HeartbeatFile)) {
        return @{ Alive = $false; Reason = 'no_heartbeat_file' }
    }
    $age = (Get-Date) - (Get-Item $HeartbeatFile).LastWriteTime
    if ($age.TotalSeconds -gt $StaleSeconds) {
        return @{ Alive = $false; Reason = ("heartbeat_stale_{0:N0}s" -f $age.TotalSeconds) }
    }

    # 2) PID file must point at a live process
    if (-not (Test-Path $PidFile)) {
        return @{ Alive = $false; Reason = 'no_pid_file' }
    }
    try {
        $pidNum = [int](Get-Content $PidFile -Raw).Trim()
    } catch {
        return @{ Alive = $false; Reason = 'pid_file_unreadable' }
    }
    $proc = Get-Process -Id $pidNum -ErrorAction SilentlyContinue
    if (-not $proc) {
        return @{ Alive = $false; Reason = "pid_${pidNum}_dead" }
    }

    return @{ Alive = $true; Reason = 'ok' }
}

function Start-Daemon {
    Write-Log "Starting scheduler daemon..."
    # Clean stale PID so daemon's own self-check doesn't false-positive
    if (Test-Path $PidFile) {
        try {
            $oldPid = [int](Get-Content $PidFile -Raw).Trim()
            if (-not (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
                Remove-Item $PidFile -Force
                Write-Log "Removed stale PID file (was $oldPid)"
            }
        } catch {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        }
    }

    # Kill any orphaned MarketFlow scheduler.py --daemon processes (hung instances).
    # IMPORTANT: filter on the FULL project path. Other projects on the same
    # machine (e.g. JUST BUY) have their own scheduler.py and must NOT be killed.
    $marketflowSchedulerPath = (Join-Path $Project 'scheduler.py')
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
        | Where-Object {
            $_.CommandLine -like ('*' + $marketflowSchedulerPath + '*') -and
            $_.CommandLine -like '*--daemon*'
        } `
        | ForEach-Object {
            Write-Log ("Killing orphan PID " + $_.ProcessId)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }

    Start-Sleep -Seconds 1

    $env:PYTHONIOENCODING = 'utf-8'
    Start-Process -FilePath $Python `
                  -ArgumentList @($Scheduler, '--daemon') `
                  -WorkingDirectory $Project `
                  -WindowStyle Hidden
    Start-Sleep -Seconds 8
    Write-Log "Daemon start command issued."
}

# ── Main ──
$status = Test-DaemonAlive
if ($status.Alive) {
    # Healthy. Don't spam logs every 5 min — only write on state changes.
    exit 0
}

Write-Log ("DAEMON DOWN: " + $status.Reason + " — restarting")
Start-Daemon

# Verify
Start-Sleep -Seconds 5
$after = Test-DaemonAlive
if ($after.Alive) {
    Write-Log "Restart confirmed — daemon healthy."
    Send-Telegram ("&#x1F501; <b>Scheduler watchdog</b>`n사유: " + $status.Reason + "`n조치: 데몬 재기동 완료")
} else {
    Write-Log ("Restart FAILED — still: " + $after.Reason)
    Send-Telegram ("&#x1F6A8; <b>Scheduler watchdog FAILED</b>`n사유: " + $status.Reason + "`n재기동 후에도: " + $after.Reason + "`n수동 확인 필요")
}
