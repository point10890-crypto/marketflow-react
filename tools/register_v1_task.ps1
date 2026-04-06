# ============================================================================
#  Register MarketFlow-V1-Flask Windows Task Scheduler task
#  - Replaces the broken "MarketFlow-AutoStart" task (references deleted .bat)
#  - Triggers on user logon; batch handles its own restart loop
#  - Does NOT start the task now; current v1 Flask process is left running
# ============================================================================

$NewTaskName = "MarketFlow-V1-Flask"
$OldTaskName = "MarketFlow-AutoStart"
$BatPath     = "C:\bitman_marketfloww\tools\start_v1_flask.bat"
$WorkDir     = "C:\bitman_marketfloww"

# --- Remove broken legacy task ---
$old = Get-ScheduledTask -TaskName $OldTaskName -ErrorAction SilentlyContinue
if ($old) {
    Write-Host "Removing broken legacy task: $OldTaskName"
    Unregister-ScheduledTask -TaskName $OldTaskName -Confirm:$false
} else {
    Write-Host "Legacy task $OldTaskName not found (already removed)."
}

# --- Remove existing v1 task if present (idempotent) ---
$existing = Get-ScheduledTask -TaskName $NewTaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task: $NewTaskName"
    Unregister-ScheduledTask -TaskName $NewTaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$BatPath`"" `
    -WorkingDirectory $WorkDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $NewTaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "MarketFlow v1 Flask backend on port 5002. Stays behind v2 proxy during and after migration. Loop batch handles own crash recovery." | Out-Null

Write-Host ""
Write-Host "Task registered: $NewTaskName"
Write-Host "NOT starting now - current v1 Flask (manually started earlier) continues running."
Get-ScheduledTask -TaskName $NewTaskName | Select-Object TaskName, State | Format-List
