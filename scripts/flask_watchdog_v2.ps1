$ErrorActionPreference = 'Continue'
$Project = 'C:\bitman_marketfloww'
$ProductionHost = 'MINIPC-NQYLP'
$TaskName = 'MarketFlow-Flask'
$HealthUrl = 'http://localhost:5003/healthz'
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

function Write-Log($Message) {
    Add-Content $LogFile ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' | ' + $Message) -Encoding UTF8
}

function Test-Health {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 15 -Uri $HealthUrl -ErrorAction Stop
        return $response.StatusCode -eq 200
    } catch { return $false }
}

function Test-LegacyProducerHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri $LegacyHealthUrl -ErrorAction Stop
        return $response.StatusCode -eq 200
    } catch { return $false }
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
    if (-not $Candidate -or -not $Candidate.CommandLine) { return $false }
    $expectedPythonPattern = [regex]::Escape((Join-Path $Project '.venv\Scripts\python.exe'))
    return (
        $Candidate.CommandLine -match $expectedPythonPattern -and
        $Candidate.CommandLine -match '(^|[\s"])flask_app\.py([\s"]|$)'
    )
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

function Write-State([int]$Failures, $RebootAt = $null) {
    @{
        consecutive_failures = $Failures
        updated_at = (Get-Date).ToString('s')
        reboot_requested_at = $RebootAt
    } | ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
}

# Run the legacy KIS producer check before every possible fast exit in the 5003
# watchdog.  Its result is carried into the final process exit code, while the
# two service recovery paths remain otherwise independent.
$LegacyProducerExitCode = Invoke-LegacyProducerWatchdog

$forceRestart = Test-Path -LiteralPath $RestartRequestFile

if ((-not $forceRestart) -and (Test-Health)) {
    Write-State 0
    exit $LegacyProducerExitCode
}

# At boot the Flask task and watchdog share an AtStartup trigger. Give the
# primary task time to import routes and bind the port instead of killing a
# healthy startup and creating overlapping launcher/listener processes.
if ((-not $forceRestart) -and (Test-FlaskStarting)) {
    Write-Log 'Health not ready, but Flask is within startup grace; skipping restart.'
    exit $LegacyProducerExitCode
}

if ($forceRestart) {
    Write-Log 'Deployment restart requested; restarting Flask task.'
    # Consume the one-shot request before touching the service.  If recovery
    # fails, the normal health-failure policy remains in control; a stale
    # request must not force a fresh restart every five minutes forever.
    Remove-Item -LiteralPath $RestartRequestFile -Force -ErrorAction SilentlyContinue
} else {
    Write-Log 'Health check failed; restarting Flask task.'
}
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Get-FlaskProcesses |
    ForEach-Object { & taskkill.exe /F /T /PID $_.ProcessId 2>&1 | Out-Null }
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName $TaskName

$deadline = (Get-Date).AddSeconds(75)
do {
    Start-Sleep -Seconds 5
    if (Test-Health) {
        Write-Log 'Flask recovery succeeded.'
        Write-State 0
        if ($forceRestart) { Write-Log 'Deployment restart request completed.' }
        exit $LegacyProducerExitCode
    }
} while ((Get-Date) -lt $deadline)

$failures = (Read-Failures) + 1
Write-State $failures
Write-Log ("Flask recovery failed; consecutive_failures=$failures")

if ($failures -ge $FailureThreshold) {
    Write-State $failures
    Write-Log 'Failure threshold reached; leaving recovery to the MarketFlow operator without rebooting the MiniPC.'
}

exit 1
