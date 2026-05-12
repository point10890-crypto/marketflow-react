# Register MiroFish MCP startup and watchdog scheduled tasks.
# Run from an elevated PowerShell session on the MiniPC.

$ErrorActionPreference = 'Stop'

$Project = 'C:\bitman_marketfloww'
$McpTask = 'MarketFlow-MiroFish-MCP'
$WatchdogTask = 'MarketFlow-MiroFish-MCP-Watchdog'

$mcpAction = New-ScheduledTaskAction `
    -Execute 'wscript.exe' `
    -Argument ('"{0}"' -f (Join-Path $Project 'deploy\start_mirofish_mcp.vbs'))

$watchdogAction = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f (Join-Path $Project 'scripts\mirofish_mcp_watchdog.ps1')) `
    -WorkingDirectory $Project

$startupTrigger = New-ScheduledTaskTrigger -AtStartup
$intervalTrigger = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $McpTask `
    -Action $mcpAction `
    -Trigger $startupTrigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Register-ScheduledTask `
    -TaskName $WatchdogTask `
    -Action $watchdogAction `
    -Trigger @($startupTrigger, $intervalTrigger) `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName $McpTask
Start-ScheduledTask -TaskName $WatchdogTask

Write-Host "Registered $McpTask and $WatchdogTask as SYSTEM startup tasks."
