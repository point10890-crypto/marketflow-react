# Restart the MarketFlow-Claw resident loop so it re-reads .env (CLAW_* keys are loaded once at process start).
#
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\scripts\restart_claw.ps1'
#
# Why not just Stop-ScheduledTask / Start-ScheduledTask?
#   The task launches wscript.exe -> cmd.exe -> python.exe. Stop-ScheduledTask only ends wscript.exe; the python loop
#   keeps running with its OLD environment (observed 2026-08-23: PID survived, delivery stayed OFF), and the next
#   Start-ScheduledTask instance exits on the single-poller lock. Mirrors scripts/claw_watchdog.ps1: kill every
#   'marketflow_claw start' process by command line, drop the pid file, then start the task.
# Must run elevated (the task runs as SYSTEM). Never touches Flask/scheduler/8080.

$ErrorActionPreference = 'Continue'
$Project  = 'C:\bitman_marketfloww'
$TaskName = 'MarketFlow-Claw'
$PidFile  = Join-Path $Project 'data\claw\claw.pid'
$LogFile  = Join-Path $Project 'logs\claw_restart.log'

function Write-Log($msg) {
    New-Item -ItemType Directory -Force (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value ("{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg) -Encoding UTF8
    Write-Host $msg
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$role = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "restart_claw.ps1 must run elevated (task principal is SYSTEM)."
}

function Get-ClawProcs {
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'marketflow_claw start' }
}

$before = @(Get-ClawProcs)
Write-Log ("before: " + (($before | ForEach-Object { $_.ProcessId }) -join ',' ))

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
foreach ($p in $before) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Log ("killed " + $p.ProcessId)
}
if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 6

$after = @(Get-ClawProcs)
Write-Log ("after: " + (($after | ForEach-Object { "$($_.ProcessId):$($_.CommandLine)" }) -join ' | ' ))
if ($after.Count -eq 0) { Write-Log "WARN: no marketflow_claw process after restart — check logs\claw.err"; exit 1 }
if (-not ($after | Where-Object { $_.CommandLine -match '(?:^|\s)--send(?:\s|$)' })) {
    Write-Log "ERROR: restarted Claw command line does not include --send"
    exit 2
}
Write-Log "verified: restarted Claw command line includes --send"
Write-Host "Verify: .venv\Scripts\python.exe -m marketflow_claw status   (delivery enabled=... must reflect .env)"
