# Register MarketFlow-Scheduler-Watchdog in Windows Task Scheduler.
# Run this ONCE (no admin needed for current-user task).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_scheduler_watchdog.ps1
#
# Idempotent: safe to re-run.

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

# Run every 5 minutes for 10 years (Task Scheduler rejects MaxValue).
# Re-install in 2036 if MarketFlow is still running.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'Restarts MarketFlow scheduler.py --daemon when its heartbeat goes stale (>3min) or PID is dead.'

Write-Host ""
Write-Host "Installed: $TaskName" -ForegroundColor Green
Write-Host "Runs every 5 minutes. Logs: logs\scheduler_watchdog.log"
Write-Host ""
Write-Host "Run once now to verify:"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
