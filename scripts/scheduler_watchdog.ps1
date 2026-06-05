# MarketFlow Scheduler Watchdog
# MiniPC-only liveness guard for scheduler.py --daemon.

$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Project       = 'C:\bitman_marketfloww'
$Python        = Join-Path $Project '.venv\Scripts\python.exe'
$Scheduler     = Join-Path $Project 'scheduler.py'
$HeartbeatFile = Join-Path $Project 'data\scheduler_heartbeat.json'
$PidFile       = Join-Path $Project 'logs\scheduler.pid'
$LogFile       = Join-Path $Project 'logs\scheduler_watchdog.log'
$StaleSeconds  = 180
$AllowedHosts  = @('MINIPC-NQYLP')

function Write-Log($msg) {
    $line = "{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-MiniPcHost {
    if ($env:MARKETFLOW_ALLOW_SCHEDULER_WATCHDOG -eq '1') {
        return $true
    }
    return $AllowedHosts -contains $env:COMPUTERNAME
}

function Read-EnvValue($name) {
    $envFile = Join-Path $Project '.env'
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        if ($line -match ("^" + [regex]::Escape($name) + "=(.+)$")) {
            $value = $Matches[1].Trim()
            $value = $value.Trim('"')
            $value = $value.Trim("'")
            return $value
        }
    }
    return $null
}

function Send-Telegram($msg) {
    try {
        $token = Read-EnvValue 'TELEGRAM_BOT_TOKEN'
        $chat = Read-EnvValue 'TELEGRAM_CHAT_ID'
        if (-not $token -or -not $chat) { return }

        $payload = @{
            chat_id    = $chat
            text       = $msg
            parse_mode = 'HTML'
        } | ConvertTo-Json -Depth 4 -Compress
        $body = [System.Text.Encoding]::UTF8.GetBytes($payload)

        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                          -Method Post `
                          -ContentType 'application/json; charset=utf-8' `
                          -Body $body `
                          -TimeoutSec 10 | Out-Null
    } catch {
        Write-Log ("Telegram send failed: " + $_.Exception.Message)
    }
}

function Test-DaemonAlive {
    if (-not (Test-Path $HeartbeatFile)) {
        return @{ Alive = $false; Reason = 'no_heartbeat_file' }
    }
    $age = (Get-Date) - (Get-Item $HeartbeatFile).LastWriteTime
    if ($age.TotalSeconds -gt $StaleSeconds) {
        return @{ Alive = $false; Reason = ("heartbeat_stale_{0:N0}s" -f $age.TotalSeconds) }
    }

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

    $marketflowSchedulerPath = Join-Path $Project 'scheduler.py'
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

if (-not (Test-MiniPcHost)) {
    Write-Log ("SKIP: scheduler watchdog is MiniPC-only. host=" + $env:COMPUTERNAME)
    exit 0
}

$status = Test-DaemonAlive
if ($status.Alive) {
    exit 0
}

Write-Log ("DAEMON DOWN: " + $status.Reason + " - restarting")
Start-Daemon

Start-Sleep -Seconds 5
$after = Test-DaemonAlive
if ($after.Alive) {
    Write-Log "Restart confirmed - daemon healthy."
    $message = @(
        "&#x1F501; <b>Scheduler watchdog</b>"
        ("사유: " + $status.Reason)
        "조치: MiniPC 스케줄러 재시작 완료"
    ) -join "`n"
    Send-Telegram $message
} else {
    Write-Log ("Restart FAILED - still: " + $after.Reason)
    $message = @(
        "&#x1F6A8; <b>Scheduler watchdog FAILED</b>"
        ("사유: " + $status.Reason)
        ("재시작 후 상태: " + $after.Reason)
        "수동 확인 필요"
    ) -join "`n"
    Send-Telegram $message
}
