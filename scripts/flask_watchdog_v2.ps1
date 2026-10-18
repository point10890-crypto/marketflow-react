param([ValidateSet('Primary', 'Legacy', 'All')][string]$Mode = 'Primary')

$ErrorActionPreference = 'Continue'
$Project = 'C:\bitman_marketfloww'
$ProductionHost = 'MINIPC-NQYLP'
$TaskName = 'MarketFlow-Flask'
$HealthUrl = 'http://127.0.0.1:5003/healthz'
$LogFile = Join-Path $Project 'logs\flask_watchdog.log'
$StateFile = Join-Path $Project 'data\flask_watchdog_state.json'
$RestartRequestFile = Join-Path $Project 'data\flask_restart.request'
$PidFile = Join-Path $Project 'data\flask_5003.pid'
$LegacyHealthUrl = 'http://127.0.0.1:5001/healthz'
$LegacyStartScript = Join-Path $Project 'run_flask.bat'
$LegacyStateFile = Join-Path $Project 'data\flask_5001_watchdog_state.json'
$LegacyProbeFailureThreshold = 3
$LegacyProbeDelaySeconds = 3
$LegacyRecoveryTimeoutSeconds = 60
$LegacyRecoveryPollSeconds = 3
$FailureThreshold = 3
$StartupGraceSeconds = 120

if ($env:COMPUTERNAME -ne $ProductionHost) { exit 0 }
. (Join-Path $PSScriptRoot 'health_probe.ps1')
. (Join-Path $PSScriptRoot 'flask_process_guard.ps1')

function Write-Log($Message) {
    Add-Content $LogFile ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' | ' + $Message) -Encoding UTF8
}

function Test-Health {
    $probe = Invoke-BoundedHealthProbe -Uri $HealthUrl -TimeoutSeconds 5
    if ($probe.reason -in @('probe_unavailable', 'cleanup_failed')) { throw 'primary_health_monitor_error' }
    if (-not $probe.healthy) { Write-Log "probe=primary_5003 reason=$($probe.reason) elapsed_ms=$($probe.elapsed_ms)" }
    return $probe.healthy
}

function Test-LegacyProducerHealth {
    $probe = Invoke-BoundedHealthProbe -Uri $LegacyHealthUrl -TimeoutSeconds 5
    if ($probe.reason -in @('probe_unavailable', 'cleanup_failed')) { throw 'legacy_health_monitor_error' }
    if (-not $probe.healthy) { Write-Log "probe=legacy_5001 reason=$($probe.reason) elapsed_ms=$($probe.elapsed_ms)" }
    return $probe.healthy
}

function Write-LegacyProducerState(
    [int]$Failures,
    [string]$Status,
    $LauncherExitCode = $null
) {
    @{
        consecutive_failures = $Failures
        status = $Status
        updated_at = (Get-Date).ToString('s')
        launcher_exit_code = $LauncherExitCode
    } | ConvertTo-Json | Set-Content -LiteralPath $LegacyStateFile -Encoding UTF8
}

function Confirm-LegacyProducerDown {
    for ($attempt = 1; $attempt -le $LegacyProbeFailureThreshold; $attempt++) {
        if (Test-LegacyProducerHealth) {
            if ($attempt -gt 1) {
                Write-Log "Legacy 5001 KIS producer health recovered during recheck attempt=$attempt; no restart."
            }
            Write-LegacyProducerState 0 'healthy'
            return $false
        }
        Write-LegacyProducerState $attempt 'health_probe_failed'
        if ($attempt -lt $LegacyProbeFailureThreshold) {
            Start-Sleep -Seconds $LegacyProbeDelaySeconds
        }
    }
    return $true
}

function Get-LegacyProducerPortOwners {
    $ownerIds = @(
        Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    @($ownerIds | ForEach-Object {
        Get-CimInstance Win32_Process -Filter "ProcessId=$_" -ErrorAction SilentlyContinue
    } | Where-Object { $_ })
}

function Test-IsMarketFlowLegacyProducer($Candidate) {
    return Test-MarketFlowFlaskProcess -Candidate $Candidate -Project $Project
}

function Invoke-LegacyProducerWatchdog {
    # Health alone is the restart contract.  A stale screener artifact is
    # handled by Claw's guarded KIS failover and must not cause process churn.
    if (-not (Confirm-LegacyProducerDown)) { return 0 }

    Write-Log "Legacy 5001 KIS producer failed ${LegacyProbeFailureThreshold} health probes; recovery starting."
    $owners = @(Get-LegacyProducerPortOwners)
    $foreignOwners = @($owners | Where-Object { -not (Test-IsMarketFlowLegacyProducer $_) })
    if ($foreignOwners.Count -gt 0) {
        $foreignIds = ($foreignOwners | ForEach-Object { $_.ProcessId }) -join ','
        Write-Log "Legacy 5001 recovery refused: port owned by non-MarketFlow process pid=$foreignIds."
        Write-LegacyProducerState $LegacyProbeFailureThreshold 'foreign_port_owner'
        return 1
    }

    foreach ($candidate in @($owners | Where-Object { Test-IsMarketFlowLegacyProducer $_ })) {
        Write-Log "Stopping unhealthy legacy 5001 MarketFlow producer pid=$($candidate.ProcessId)."
        & taskkill.exe /F /T /PID $candidate.ProcessId 2>&1 | Out-Null
    }

    $portReleaseDeadline = (Get-Date).AddSeconds(10)
    while (
        (Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue) -and
        (Get-Date) -lt $portReleaseDeadline
    ) {
        Start-Sleep -Milliseconds 500
    }
    if (Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue) {
        Write-Log 'Legacy 5001 recovery failed: listener did not release within 10 seconds.'
        Write-LegacyProducerState $LegacyProbeFailureThreshold 'port_release_timeout'
        return 1
    }
    if (-not (Test-Path -LiteralPath $LegacyStartScript)) {
        Write-Log "Legacy 5001 recovery failed: launcher missing at $LegacyStartScript."
        Write-LegacyProducerState $LegacyProbeFailureThreshold 'launcher_missing'
        return 1
    }

    try {
        $launcher = Start-Process -FilePath $LegacyStartScript `
            -WorkingDirectory $Project `
            -WindowStyle Hidden `
            -PassThru `
            -ErrorAction Stop
        Write-Log "Legacy 5001 launcher started hidden pid=$($launcher.Id)."
    } catch {
        Write-Log "Legacy 5001 recovery failed to start launcher: $($_.Exception.Message)"
        Write-LegacyProducerState $LegacyProbeFailureThreshold 'launcher_start_failed'
        return 1
    }

    $deadline = (Get-Date).AddSeconds($LegacyRecoveryTimeoutSeconds)
    do {
        if (Test-LegacyProducerHealth) {
            Write-Log 'Legacy 5001 KIS producer recovery succeeded.'
            Write-LegacyProducerState 0 'recovered'
            return 0
        }
        if ($launcher.HasExited) {
            $launcher.Refresh()
            Write-Log "Legacy 5001 launcher exited before health succeeded; exit_code=$($launcher.ExitCode)."
            Write-LegacyProducerState $LegacyProbeFailureThreshold 'launcher_exited' $launcher.ExitCode
            return 1
        }
        Start-Sleep -Seconds $LegacyRecoveryPollSeconds
    } while ((Get-Date) -lt $deadline)

    $launcherStatus = 'running'
    $launcherExitCode = $null
    if ($launcher.HasExited) {
        $launcher.Refresh()
        $launcherStatus = 'exited'
        $launcherExitCode = $launcher.ExitCode
    }
    Write-Log (
        "Legacy 5001 recovery timed out after ${LegacyRecoveryTimeoutSeconds}s; " +
        "launcher_status=$launcherStatus exit_code=$launcherExitCode"
    )
    Write-LegacyProducerState $LegacyProbeFailureThreshold 'health_timeout' $launcherExitCode
    return 1
}

function Get-FlaskProcesses {
    $candidateIds = [System.Collections.Generic.HashSet[int]]::new()
    if (Test-Path -LiteralPath $PidFile) {
        try { [void]$candidateIds.Add([int](Get-Content -LiteralPath $PidFile -Raw).Trim()) } catch {}
    }
    Get-NetTCPConnection -LocalPort 5003 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { [void]$candidateIds.Add([int]$_.OwningProcess) }
    @($candidateIds | ForEach-Object {
        Get-CimInstance Win32_Process -Filter "ProcessId=$_" -ErrorAction SilentlyContinue
    } | Where-Object { $_ })
}

function Test-FlaskStarting {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task -or $task.State -ne 'Running') { return $false }

    $now = Get-Date
    try {
        $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
        if ($taskInfo.LastRunTime -and ($now - $taskInfo.LastRunTime).TotalSeconds -lt $StartupGraceSeconds) {
            return $true
        }
    } catch {}
    foreach ($candidate in Get-FlaskProcesses) {
        try {
            $process = Get-Process -Id $candidate.ProcessId -ErrorAction Stop
            if (($now - $process.StartTime).TotalSeconds -lt $StartupGraceSeconds) {
                return $true
            }
        } catch {}
    }
    return $false
}

function Read-Failures {
    try {
        if (Test-Path $StateFile) {
            return [int]((Get-Content $StateFile -Raw | ConvertFrom-Json).consecutive_failures)
        }
    } catch {}
    return 0
}

function Write-State([int]$Failures, $RebootAt = $null, [string]$Status = 'healthy') {
    @{
        consecutive_failures = $Failures
        updated_at = (Get-Date).ToString('s')
        reboot_requested_at = $RebootAt
        status = $Status
    } | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
}

function Invoke-PrimaryFlaskWatchdog {
    $forceRestart = Test-Path -LiteralPath $RestartRequestFile
    if ((-not $forceRestart) -and (Test-Health)) {
        Write-State 0
        return 0
    }
    if ((-not $forceRestart) -and (Test-FlaskStarting)) {
        Write-Log 'Health not ready, but Flask is within startup grace; skipping restart.'
        return 0
    }
    $processes = @(Get-FlaskProcesses)
    try { Assert-MarketFlowPrimaryCandidates -Candidates $processes -Project $Project } catch {
        $reason = $_.Exception.Message
        if ($reason -notin @('legacy_5001_protected', 'unverified_process')) { $reason = 'ownership_check_failed' }
        Write-State ((Read-Failures) + 1) -Status $reason
        Write-Log "Primary recovery refused: reason=$reason"
        return 1
    }
    if ($forceRestart) {
        Write-Log 'Deployment restart requested; restarting Flask task.'
        Remove-Item -LiteralPath $RestartRequestFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Log 'Health check failed; restarting Flask task.'
    }
    Write-Log 'Primary recovery stage=stop_task'
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Start-Sleep -Seconds 3
    Write-Log 'Primary recovery stage=stop_verified_tree'
    $processes | ForEach-Object { Stop-MarketFlowPrimaryTree -Snapshot $_ -Project $Project }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Write-Log 'Primary recovery stage=start_task'
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    $deadline = (Get-Date).AddSeconds(75)
    do {
        Start-Sleep -Seconds 5
        if (Test-Health) {
            Write-Log 'Flask recovery succeeded.'
            Write-State 0
            if ($forceRestart) { Write-Log 'Deployment restart request completed.' }
            return 0
        }
    } while ((Get-Date) -lt $deadline)
    $failures = (Read-Failures) + 1
    Write-State $failures -Status 'recovery_failed'
    Write-Log "Flask recovery failed; consecutive_failures=$failures"
    if ($failures -ge $FailureThreshold) {
        Write-Log 'Failure threshold reached; leaving recovery to the MarketFlow operator without rebooting the MiniPC.'
    }
    return 1
}

function Invoke-FlaskWatchdog {
    param([ValidateSet('Primary', 'Legacy', 'All')][string]$Mode = 'Primary')
    $code = 0
    if ($Mode -in @('Primary', 'All')) {
        try { $code = Invoke-PrimaryFlaskWatchdog } catch {
            $reason = 'unexpected_failure'
            if ($_.Exception.Message -in @('missing_process_snapshot', 'process_identity_changed', 'legacy_5001_protected', 'unverified_process', 'ownership_check_failed', 'primary_health_monitor_error')) {
                $reason = $_.Exception.Message
            }
            # Never copy provider messages, command lines or credential-bearing URLs.
            Write-Log "Primary watchdog failed; reason=$reason line=$($_.InvocationInfo.ScriptLineNumber)"
            $code = 1
        }
    }
    if ($Mode -in @('Legacy', 'All')) {
        try { $code = [Math]::Max($code, (Invoke-LegacyProducerWatchdog)) } catch {
            Write-Log 'Legacy watchdog failed; primary recovery remains independent.'
            $code = 1
        }
    }
    return $code
}

exit (Invoke-FlaskWatchdog -Mode $Mode)
