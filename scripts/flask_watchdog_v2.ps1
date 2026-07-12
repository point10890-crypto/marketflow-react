$ErrorActionPreference = 'Continue'
$Project = 'C:\bitman_marketfloww'
$ProductionHost = 'MINIPC-NQYLP'
$TaskName = 'MarketFlow-Flask'
$HealthUrl = 'http://localhost:5001/healthz'
$LogFile = Join-Path $Project 'logs\flask_watchdog.log'
$StateFile = Join-Path $Project 'data\flask_watchdog_state.json'
$FailureThreshold = 3

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

Write-Log 'Health check failed; restarting Flask task.'
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*flask_app.py*' } |
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
