$ErrorActionPreference = 'Continue'

'MarketFlow-Flask', 'MarketFlow-Scheduler' | ForEach-Object {
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable

$trigger = New-ScheduledTaskTrigger -AtLogOn

$flaskAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument '"C:\bitman_marketfloww\deploy\start_flask_only.vbs"'
Register-ScheduledTask -TaskName "MarketFlow-Flask" -Action $flaskAction -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[OK] Flask registered"

$schedAction = New-ScheduledTaskAction -Execute "wscript.exe" -Argument '"C:\bitman_marketfloww\deploy\start_scheduler.vbs"'
Register-ScheduledTask -TaskName "MarketFlow-Scheduler" -Action $schedAction -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[OK] Scheduler registered"

Get-ScheduledTask -TaskName "MarketFlow-*" | Select-Object TaskName, State | Format-Table -AutoSize

Start-ScheduledTask -TaskName "MarketFlow-Flask"
Start-Sleep 5
Start-ScheduledTask -TaskName "MarketFlow-Scheduler"
Write-Host "[OK] Both started"
