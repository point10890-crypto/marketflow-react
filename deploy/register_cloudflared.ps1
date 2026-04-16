Unregister-ScheduledTask -TaskName "MarketFlow-Cloudflared" -Confirm:$false -ErrorAction SilentlyContinue
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 0) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2) -StartWhenAvailable
$trigger = New-ScheduledTaskTrigger -AtLogOn
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument '"C:\bitman_marketfloww\deploy\start_cloudflared.vbs"'
Register-ScheduledTask -TaskName "MarketFlow-Cloudflared" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[OK] Cloudflared task registered"
Start-ScheduledTask -TaskName "MarketFlow-Cloudflared"
Get-ScheduledTask -TaskName "MarketFlow-*" | Select TaskName, State | Format-Table -AutoSize
