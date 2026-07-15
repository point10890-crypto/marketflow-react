$ErrorActionPreference = 'Continue'
$Project = 'C:\bitman_marketfloww'
$ProductionHost = 'MINIPC-NQYLP'
$TaskName = 'MarketFlow-Flask'
$HealthUrl = 'http://localhost:5001/healthz'
$LogFile = Join-Path $Project 'logs\flask_watchdog.log'
$StateFile = Join-Path $Project 'data\flask_watchdog_state.json'
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

function Get-FlaskProcesses {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -like "$Project\.venv\Scripts\python.exe" -and
            $_.CommandLine -match '(^|[\\\s\"])(flask_app\.py)([\\\s\"]|$)'
        })
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

if (Test-Health) {
    Write-State 0
    exit 0
}

# At boot the Flask task and watchdog share an AtStartup trigger. Give the
# primary task time to import routes and bind the port instead of killing a
# healthy startup and creating overlapping launcher/listener processes.
if (Test-FlaskStarting) {
    Write-Log 'Health not ready, but Flask is within startup grace; skipping restart.'
    exit 0
}

Write-Log 'Health check failed; restarting Flask task.'
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Get-FlaskProcesses |
    ForEach-Object { & taskkill.exe /F /T /PID $_.ProcessId 2>&1 | Out-Null }
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName $TaskName

$deadline = (Get-Date).AddSeconds(75)
do {
    Start-Sleep -Seconds 5
    if (Test-Health) {
        Write-Log 'Flask recovery succeeded.'
        Write-State 0
        exit 0
    }
} while ((Get-Date) -lt $deadline)

$failures = (Read-Failures) + 1
Write-State $failures
Write-Log ("Flask recovery failed; consecutive_failures=$failures")

if ($failures -ge $FailureThreshold) {
    $rebootAt = (Get-Date).ToString('s')
    Write-State $failures $rebootAt
    Write-Log 'Failure threshold reached; scheduling MiniPC reboot in 60 seconds.'
    & shutdown.exe /r /t 60 /f /c 'MarketFlow Flask watchdog recovery'
}

exit 1
