# Register MarketFlow-Scheduler-Watchdog in Windows Task Scheduler.
# Run ONCE as Administrator (SYSTEM principal requires elevation to register).
#
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\scripts\install_scheduler_watchdog.ps1'
#
# Idempotent: safe to re-run.
#
# Runs as NT AUTHORITY\SYSTEM every 5 minutes (matches other MarketFlow tasks),
# so it survives logout / user-switch / reboot without needing an interactive session.

$ErrorActionPreference = 'Stop'

$TaskName  = 'MarketFlow-Scheduler-Watchdog'
$Project   = 'C:\bitman_marketfloww'
$Script    = Join-Path $Project 'scripts\scheduler_watchdog.ps1'

if (-not (Test-Path $Script)) {
    Write-Error "Watchdog script not found: $Script"
    exit 1
}

# Remove existing task if present (idempotent re-install)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task: $TaskName"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Script`"" `
    -WorkingDirectory $Project

# Dual trigger: AtStartup (immediately after reboot) + 5-min repeating (ongoing liveness).
# RepetitionDuration = 10 years — re-install in 2036 if MarketFlow is still running.
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

# SYSTEM account: no interactive login required, survives user logout/switch.
# Matches the other MarketFlow-* tasks (migrated to SYSTEM on 2026-04-14).
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
    -Description 'Restarts MarketFlow scheduler.py --daemon when its heartbeat goes stale (>3min) or PID is dead. Runs as SYSTEM every 5 min + AtStartup.'

Write-Host ""
Write-Host "Installed: $TaskName" -ForegroundColor Green
Write-Host "Runs every 5 minutes. Logs: logs\scheduler_watchdog.log"
Write-Host ""
Write-Host "Run once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
