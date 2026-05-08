$ErrorActionPreference = "Stop"

$ProjectDir = $env:MARKETFLOW_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = "C:\bitman_marketfloww"
}

$TaskNames = @("MarketFlow-Flask", "MarketFlow-Scheduler")
foreach ($TaskName in $TaskNames) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$Trigger = New-ScheduledTaskTrigger -AtStartup

$FlaskAction = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$ProjectDir\deploy\start_flask_only.vbs`"" `
    -WorkingDirectory $ProjectDir
Register-ScheduledTask -TaskName "MarketFlow-Flask" -Action $FlaskAction -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host "[OK] MarketFlow-Flask registered at startup as SYSTEM"

$SchedulerAction = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$ProjectDir\deploy\start_scheduler.vbs`"" `
    -WorkingDirectory $ProjectDir
Register-ScheduledTask -TaskName "MarketFlow-Scheduler" -Action $SchedulerAction -Trigger $Trigger -Settings $Settings -Principal $Principal -Force | Out-Null
Write-Host "[OK] MarketFlow-Scheduler registered at startup as SYSTEM"
