$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BackupScript = Join-Path $Root "scripts\backup_marketflow_data.py"
$Runner = Join-Path $Root "scripts\run_durable_backup_task.ps1"
$TaskName = "MarketFlow-Durable-Backup"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Python runtime is missing: $Python"
}
if (-not (Test-Path -LiteralPath $BackupScript -PathType Leaf)) {
    throw "Backup script is missing: $BackupScript"
}
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "Backup task runner is missing: $Runner"
}

$Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`""
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument $Arguments `
    -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At "03:15"
$Principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "Daily verified SQLite online backup for MarketFlow member data (30-day retention)." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Output "TASK_REGISTERED=$($task.TaskName)"
Write-Output "TASK_STATE=$($task.State)"
