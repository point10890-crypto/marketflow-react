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
$RestartRequestFile = Join-Path $Project 'data\claw\restart.request'
$LogFile       = Join-Path $Project 'logs\claw_watchdog.log'
$TaskName      = 'MarketFlow-Claw'
$StaleSeconds  = 180
$RestartVerifyTimeoutSeconds = 90
$RestartPollSeconds = 2
$WmiTimeoutSeconds = 4
$TaskStopTimeoutSeconds = 15
$TaskStatePollMilliseconds = 500
$AllowedHosts  = @('MINIPC-NQYLP')

function Write-Log($msg) {
    New-Item -ItemType Directory -Force (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value ("{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding UTF8
}

if (($AllowedHosts -notcontains $env:COMPUTERNAME) -and ($env:MARKETFLOW_ALLOW_CLAW -ne '1')) {
    exit 0
}

function Read-ClawPidFile {
    if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
    try {
        $candidate = [int](Get-Content -LiteralPath $PidFile -Raw -ErrorAction Stop).Trim()
        if ($candidate -gt 0) { return $candidate }
    } catch { }
    return $null
}

function Test-PidAlive($CandidatePid) {
    if ($null -eq $CandidatePid -or [int]$CandidatePid -le 0) { return $false }
    return [bool](Get-Process -Id ([int]$CandidatePid) -ErrorAction SilentlyContinue)
}

function Get-ClawFallbackPids {
    # WMI can block for a long time on an unhealthy Windows host. It is only a
    # fallback when the pidfile cannot identify a live process, and the job
    # boundary guarantees that the watchdog itself remains bounded.
    $job = $null
    try {
        $job = Start-Job -ScriptBlock {
            Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction Stop |
                Where-Object { $_.CommandLine -match 'marketflow_claw start' } |
                ForEach-Object { [int]$_.ProcessId }
        }
        $completed = Wait-Job -Job $job -Timeout $WmiTimeoutSeconds
        if (-not $completed) {
            Stop-Job -Job $job -ErrorAction SilentlyContinue
            Write-Log "WMI fallback timed out after ${WmiTimeoutSeconds}s"
            return @()
        }
        return @(Receive-Job -Job $job -ErrorAction SilentlyContinue |
            Where-Object { $_ -and (Test-PidAlive $_) } |
            Sort-Object -Unique)
    } catch {
        Write-Log ("WMI fallback failed: " + $_.Exception.Message)
        return @()
    } finally {
        if ($job) { Remove-Job -Job $job -Force -ErrorAction SilentlyContinue }
    }
}

function Resolve-ClawProcess {
    $pidNum = Read-ClawPidFile
    $pidReason = 'no_pid_file'
    if ($null -ne $pidNum) {
        if (Test-PidAlive $pidNum) {
            return @{ Pid = $pidNum; Source = 'pidfile'; Reason = 'ok' }
        }
        $pidReason = "pid_${pidNum}_not_running"
    }

    $fallback = @(Get-ClawFallbackPids)
    if ($fallback.Count -gt 0) {
        return @{ Pid = [int]$fallback[0]; Source = 'wmi_fallback'; Reason = 'ok' }
    }
    return @{ Pid = $null; Source = 'none'; Reason = $pidReason }
}

function Read-ClawHeartbeat {
    if (-not (Test-Path -LiteralPath $HeartbeatFile)) { return $null }
    try {
        return Get-Content -LiteralPath $HeartbeatFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $null
    }
}

function Test-ClawAlive {
    # Fast path: the resident loop owns this pidfile. WMI is consulted only by
    # Resolve-ClawProcess when that fast path is unavailable or dead.
    $resolved = Resolve-ClawProcess
    if ($null -eq $resolved.Pid) {
        return @{ Alive = $false; Reason = $resolved.Reason; Pid = $null }
    }
    if (-not (Test-Path -LiteralPath $HeartbeatFile)) {
        return @{ Alive = $false; Reason = 'no_heartbeat_file'; Pid = $resolved.Pid }
    }
    try {
        $heartbeatItem = Get-Item -LiteralPath $HeartbeatFile -ErrorAction Stop
        $age = (Get-Date) - $heartbeatItem.LastWriteTime
    } catch {
        return @{ Alive = $false; Reason = 'heartbeat_unreadable'; Pid = $resolved.Pid }
    }
    if ($age.TotalSeconds -gt $StaleSeconds) {
        return @{ Alive = $false; Reason = ("heartbeat_stale_{0:N0}s" -f $age.TotalSeconds); Pid = $resolved.Pid }
    }
    $heartbeat = Read-ClawHeartbeat
    if ($null -eq $heartbeat -or $null -eq $heartbeat.pid) {
        return @{ Alive = $false; Reason = 'heartbeat_payload_unreadable'; Pid = $resolved.Pid }
    }
    if ([int]$heartbeat.pid -ne [int]$resolved.Pid) {
        return @{ Alive = $false; Reason = "heartbeat_pid_$($heartbeat.pid)_expected_$($resolved.Pid)"; Pid = $resolved.Pid }
    }
    return @{
        Alive = $true
        Reason = 'ok'
        Pid = [int]$resolved.Pid
        PidSource = $resolved.Source
        HeartbeatWriteTime = $heartbeatItem.LastWriteTime
    }
}

function Wait-ClawRestart($OldPid, $NotBefore) {
    $deadline = (Get-Date).AddSeconds($RestartVerifyTimeoutSeconds)
    $lastReason = 'not_checked'
    while ((Get-Date) -lt $deadline) {
        $after = Test-ClawAlive
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

function Wait-ClawTaskStopped {
    $deadline = (Get-Date).AddSeconds($TaskStopTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
            if ([string]$task.State -ne 'Running') { return $true }
        } catch {
            Write-Log ("task state query failed: " + $_.Exception.Message)
            return $false
        }
        Start-Sleep -Milliseconds $TaskStatePollMilliseconds
    }
    return $false
}

$forceRestart = Test-Path -LiteralPath $RestartRequestFile
$state = Test-ClawAlive
if ($state.Alive -and -not $forceRestart) { exit 0 }

if ($forceRestart) {
    Write-Log ("Deployment restart requested -> restarting task " + $TaskName)
    # Consume the request before restarting. A failed restart is then handled
    # by the ordinary stale-heartbeat path instead of creating a restart loop.
    Remove-Item -LiteralPath $RestartRequestFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Log ("Claw not alive: " + $state.Reason + " -> restarting task " + $TaskName)
}

try {
    # Stop the scheduled-task wrapper first. Otherwise MultipleInstances=IgnoreNew
    # can discard Start-ScheduledTask while the previous wscript/cmd wrapper is
    # still transitioning out of Running after its Python child is killed.
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if (-not (Wait-ClawTaskStopped)) {
        throw "task $TaskName remained Running after ${TaskStopTimeoutSeconds}s"
    }

    # Prefer the exact resident-loop PID. Only fall back to bounded WMI when
    # the pidfile is absent, corrupt, or no longer identifies a live process.
    $oldPid = Read-ClawPidFile
    $stoppedExactPid = $false
    if (Test-PidAlive $oldPid) {
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
        $stoppedExactPid = $true
        Write-Log "stopped Claw pidfile PID $oldPid"
    }
    if (-not $stoppedExactPid -or (Test-PidAlive $oldPid)) {
        foreach ($fallbackPid in @(Get-ClawFallbackPids)) {
            Stop-Process -Id $fallbackPid -Force -ErrorAction SilentlyContinue
            Write-Log "stopped Claw WMI fallback PID $fallbackPid"
        }
    }
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
    $restartStartedAt = Get-Date
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Write-Log "restart requested; verifying for up to ${RestartVerifyTimeoutSeconds}s"
    $verification = Wait-ClawRestart -OldPid $oldPid -NotBefore $restartStartedAt
    if ($verification.Success) {
        Write-Log ("restart confirmed: PID {0}, heartbeat {1:yyyy-MM-dd HH:mm:ss}" -f $verification.Pid, $verification.HeartbeatWriteTime)
        exit 0
    }
    Write-Log ("restart FAILED after ${RestartVerifyTimeoutSeconds}s: " + $verification.Reason)
    exit 1
} catch {
    Write-Log ("restart failed: " + $_.Exception.Message)
    exit 1
}
