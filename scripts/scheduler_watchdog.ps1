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
$RestartRequestFile = Join-Path $Project 'data\scheduler_restart.request'
$LogFile       = Join-Path $Project 'logs\scheduler_watchdog.log'
$StaleSeconds  = 180
$RestartVerifyTimeoutSeconds = 180
$RestartPollSeconds = 3
$WmiTimeoutSeconds = 4
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

function Read-SchedulerPidFile {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    try {
        $candidate = [int](Get-Content -LiteralPath $PidFile -Raw -ErrorAction Stop).Trim()
        if ($candidate -gt 0) { return $candidate }
    } catch { }
    return $null
}

function Read-SchedulerHeartbeat {
    if (-not (Test-Path -LiteralPath $HeartbeatFile)) { return $null }
    try {
        return Get-Content -LiteralPath $HeartbeatFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-SchedulerPidAlive($CandidatePid) {
    if ($null -eq $CandidatePid -or [int]$CandidatePid -le 0) { return $false }
    return [bool](Get-Process -Id ([int]$CandidatePid) -ErrorAction SilentlyContinue)
}

function Get-SchedulerFallbackPids {
    # Only used when the pidfile fast path cannot stop a live daemon. Keep WMI
    # bounded so a damaged provider cannot wedge the watchdog indefinitely.
    $job = $null
    try {
        $job = Start-Job -ArgumentList $Scheduler -ScriptBlock {
            param($ExpectedSchedulerPath)
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
                Where-Object {
                    $_.CommandLine -like ('*' + $ExpectedSchedulerPath + '*') -and
                    $_.CommandLine -like '*--daemon*'
                } |
                ForEach-Object { [int]$_.ProcessId }
        }
        $completed = Wait-Job -Job $job -Timeout $WmiTimeoutSeconds
        if (-not $completed) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Write-Log "Scheduler WMI fallback timed out after ${WmiTimeoutSeconds}s"
            return @()
        }
        return @(Receive-Job -Job $job -ErrorAction SilentlyContinue |
            Where-Object { $_ -and (Test-SchedulerPidAlive $_) } |
            Sort-Object -Unique)
    } catch {
        Write-Log ("Scheduler WMI fallback failed: " + $_.Exception.Message)
        return @()
    } finally {
        if ($job) { Remove-Job -Job $job -Force -ErrorAction SilentlyContinue }
    }
}

function Test-DaemonAlive {
    $pidNum = Read-SchedulerPidFile
    if ($null -eq $pidNum) {
        return @{ Alive = $false; Reason = 'no_or_unreadable_pid_file'; Pid = $null }
    }
    $proc = Get-Process -Id $pidNum -ErrorAction SilentlyContinue
    if (-not $proc) {
        return @{ Alive = $false; Reason = "pid_${pidNum}_dead"; Pid = $pidNum }
    }
    if (-not (Test-Path -LiteralPath $HeartbeatFile)) {
        return @{ Alive = $false; Reason = 'no_heartbeat_file'; Pid = $pidNum }
    }
    try {
        $heartbeatItem = Get-Item -LiteralPath $HeartbeatFile -ErrorAction Stop
        $age = (Get-Date) - $heartbeatItem.LastWriteTime
    } catch {
        return @{ Alive = $false; Reason = 'heartbeat_unreadable'; Pid = $pidNum }
    }
    if ($age.TotalSeconds -gt $StaleSeconds) {
        return @{ Alive = $false; Reason = ("heartbeat_stale_{0:N0}s" -f $age.TotalSeconds); Pid = $pidNum }
    }
    $heartbeat = Read-SchedulerHeartbeat
    if ($null -eq $heartbeat -or $null -eq $heartbeat.pid) {
        return @{ Alive = $false; Reason = 'heartbeat_payload_unreadable'; Pid = $pidNum }
    }
    if ([int]$heartbeat.pid -ne $pidNum) {
        return @{ Alive = $false; Reason = "heartbeat_pid_$($heartbeat.pid)_expected_${pidNum}"; Pid = $pidNum }
    }

    return @{
        Alive = $true
        Reason = 'ok'
        Pid = $pidNum
        HeartbeatWriteTime = $heartbeatItem.LastWriteTime
    }
}

function Wait-DaemonRestart($OldPid, $NotBefore) {
    $deadline = (Get-Date).AddSeconds($RestartVerifyTimeoutSeconds)
    $lastReason = 'not_checked'
    while ((Get-Date) -lt $deadline) {
        $after = Test-DaemonAlive
        $lastReason = $after.Reason
        if ($after.Alive) {
            $newPid = [int]$after.Pid
            $isNewPid = ($null -eq $OldPid) -or ([int]$OldPid -le 0) -or ($newPid -ne [int]$OldPid)
            $freshHeartbeat = $after.HeartbeatWriteTime -ge $NotBefore.AddSeconds(-1)
            if ($isNewPid -and $freshHeartbeat) {
                return @{ Success = $true; Pid = $newPid; Reason = 'ok'; HeartbeatWriteTime = $after.HeartbeatWriteTime }
            }
            if (-not $isNewPid) { $lastReason = "old_pid_${OldPid}_still_active" }
            elseif (-not $freshHeartbeat) { $lastReason = 'heartbeat_not_refreshed_after_restart' }
        }
        Start-Sleep -Seconds $RestartPollSeconds
    }
    return @{ Success = $false; Pid = $null; Reason = $lastReason }
}

function Start-Daemon {
    Write-Log "Starting scheduler daemon..."
    $oldPid = Read-SchedulerPidFile
    $stoppedExactPid = $false
    if (Test-SchedulerPidAlive $oldPid) {
        # Kill the exact process tree recorded by this daemon. This also works
        # when a SYSTEM process hides its command line from an operator account.
        & taskkill.exe /F /T /PID $oldPid 2>&1 | Out-Null
        Start-Sleep -Milliseconds 500
        $stoppedExactPid = -not (Test-SchedulerPidAlive $oldPid)
        if ($stoppedExactPid) { Write-Log "Stopped scheduler PID tree $oldPid" }
        else { Write-Log "Scheduler PID tree $oldPid did not stop; using bounded WMI fallback" }
    } elseif ($null -ne $oldPid) {
        Write-Log "Removed stale PID file (was $oldPid)"
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

    if (-not $stoppedExactPid) {
        foreach ($fallbackPid in @(Get-SchedulerFallbackPids)) {
            Write-Log "Killing scheduler WMI fallback PID $fallbackPid"
            & taskkill.exe /F /T /PID $fallbackPid 2>&1 | Out-Null
        }
    }

    Start-Sleep -Seconds 1
    $env:PYTHONIOENCODING = 'utf-8'
    Start-Process -FilePath $Python `
                  -ArgumentList @($Scheduler, '--daemon') `
                  -WorkingDirectory $Project `
                  -WindowStyle Hidden `
                  -ErrorAction Stop
    Write-Log "Daemon start command issued; awaiting pidfile and heartbeat."
}

if (-not (Test-MiniPcHost)) {
    Write-Log ("SKIP: scheduler watchdog is MiniPC-only. host=" + $env:COMPUTERNAME)
    exit 0
}

$forceRestart = Test-Path -LiteralPath $RestartRequestFile
$status = Test-DaemonAlive
if ($status.Alive -and -not $forceRestart) {
    exit 0
}

if ($forceRestart) {
    Write-Log "Deployment restart requested - restarting scheduler"
    Remove-Item -LiteralPath $RestartRequestFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Log ("DAEMON DOWN: " + $status.Reason + " - restarting")
}
$oldPidBeforeRestart = Read-SchedulerPidFile
$restartStartedAt = Get-Date
try {
    Start-Daemon
} catch {
    Write-Log ("Restart command FAILED: " + $_.Exception.Message)
    exit 1
}

Write-Log "Verifying scheduler restart for up to ${RestartVerifyTimeoutSeconds}s"
$after = Wait-DaemonRestart -OldPid $oldPidBeforeRestart -NotBefore $restartStartedAt
if ($after.Success) {
    Write-Log ("Restart confirmed - daemon healthy. PID {0}, heartbeat {1:yyyy-MM-dd HH:mm:ss}" -f $after.Pid, $after.HeartbeatWriteTime)
    # 텔레그램 알림 비활성화 (사용자 요청 2026-07-09 — watchdog 알림 기능 전체 중단).
    # watchdog 의 재기동 동작 자체는 그대로 유지, 로그만 남김.
    # $message = @(
    #     "&#x1F501; <b>Scheduler watchdog</b>"
    #     ("사유: " + $status.Reason)
    #     "조치: MiniPC 스케줄러 재시작 완료"
    # ) -join "`n"
    # Send-Telegram $message
} else {
    Write-Log ("Restart FAILED after ${RestartVerifyTimeoutSeconds}s - still: " + $after.Reason)
    # 텔레그램 알림 비활성화 (사용자 요청 2026-07-09).
    # $message = @(
    #     "&#x1F6A8; <b>Scheduler watchdog FAILED</b>"
    #     ("사유: " + $status.Reason)
    #     ("재시작 후 상태: " + $after.Reason)
    #     "수동 확인 필요"
    # ) -join "`n"
    # Send-Telegram $message
    exit 1
}
