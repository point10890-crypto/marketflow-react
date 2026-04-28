# Register MarketFlow-Flask-Watchdog in Windows Task Scheduler.
# Run ONCE as Administrator (SYSTEM principal requires elevation to register).
#
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\scripts\install_flask_watchdog.ps1'
#
# Idempotent: safe to re-run.
#
# Why: 2026-04-24 20:07 Flask silent death undetected for 24h+.
# MarketFlow-Scheduler-Watchdog only monitors scheduler.py.
# This closes the gap — same SYSTEM + 5min + AtStartup pattern.

$ErrorActionPreference = 'Stop'

$TaskName  = 'MarketFlow-Flask-Watchdog'
$Project   = 'C:\bitman_marketfloww'
$Script    = Join-Path $Project 'scripts\flask_watchdog.ps1'

if (-not (Test-Path $Script)) {
    Write-Error "Watchdog script not found: $Script"
    exit 1
}

# Idempotent re-install
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task: $TaskName"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Project

# Dual trigger: AtStartup + 5-min repeating
$trigger1 = New-ScheduledTaskTrigger -AtStartup
$trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew

# SYSTEM principal — survives logout/switch/reboot
$principal = New-ScheduledTaskPrincipal `
    -UserId 'SYSTEM' `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($trigger1, $trigger2) `
    -Settings $settings `
    -Principal $principal `
    -Description 'Restarts MarketFlow-Flask task when port 5001 is unreachable or /healthz times out. Runs as SYSTEM every 5 min + AtStartup. Closes Flask silent-death gap.'

Write-Host ""
Write-Host "Installed: $TaskName" -ForegroundColor Green
Write-Host "Runs every 5 minutes. Logs: logs\flask_watchdog.log"
Write-Host ""
Write-Host "Run once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
