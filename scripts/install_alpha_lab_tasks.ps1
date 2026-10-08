param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$monitorPath = Join-Path $rootPath 'scripts\run_alpha_lab_monitor.py'
$refreshPath = Join-Path $rootPath 'scripts\refresh_alpha_lab.ps1'
foreach ($requiredPath in @($pythonPath, $monitorPath, $refreshPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw 'AlphaLab task runtime and scripts must exist.' }
}
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$monitorSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
$researchSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 90)
$researchAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$refreshPath`" -Root `"$rootPath`"" -WorkingDirectory $rootPath
$researchTrigger = New-ScheduledTaskTrigger -Daily -At '20:30'
Register-ScheduledTask -TaskName 'MarketFlow-AlphaLab-Research' -Action $researchAction -Trigger $researchTrigger -Settings $researchSettings -Principal $principal -Description 'Completed-session sources then fixed research; official closed days skip; no broker orders.' -Force | Out-Null
$primeAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$monitorPath`" prime --root `"$(Join-Path $rootPath 'data\alpha_lab')`"" -WorkingDirectory $rootPath
$primeTrigger = New-ScheduledTaskTrigger -Daily -At '08:55'
Register-ScheduledTask -TaskName 'MarketFlow-AlphaLab-Prime' -Action $primeAction -Trigger $primeTrigger -Settings $monitorSettings -Principal $principal -Description 'Prime the saved official KIS session calendar; no orders.' -Force | Out-Null
$tickAction = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$monitorPath`" tick --root `"$(Join-Path $rootPath 'data\alpha_lab')`"" -WorkingDirectory $rootPath
$tickTrigger = New-ScheduledTaskTrigger -Daily -At '09:00'
# Daily trigger Repetition is initially null. Copy an initialized CIM pattern.
$tickTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At '09:00' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Minutes 391)).Repetition
$tickTrigger.Repetition.Interval = 'PT5M'
# 6h31m includes the 15:30 tick and cannot schedule a 15:35 tick.
$tickTrigger.Repetition.Duration = 'PT6H31M'
$tickTrigger.Repetition.StopAtDurationEnd = $false
Register-ScheduledTask -TaskName 'MarketFlow-AlphaLab-Monitor' -Action $tickAction -Trigger $tickTrigger -Settings $monitorSettings -Principal $principal -Description 'Saved manual price guards every five minutes09:00-15:30; known closed days skip; no orders.' -Force | Out-Null
Write-Output 'Installed AlphaLab Research20:30, Prime08:55, Monitor09:00-15:30 every five minutes; no initial cycles started.'
