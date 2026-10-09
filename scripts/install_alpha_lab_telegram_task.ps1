param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$deliveryPath = Join-Path $rootPath 'scripts\run_alpha_lab_telegram.py'
foreach ($path in @($pythonPath, $deliveryPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'AlphaLab notification runtime and script must exist.' }
}
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "`"$deliveryPath`" --automatic --root `"$(Join-Path $rootPath 'data\alpha_lab')`"" -WorkingDirectory $rootPath
$trigger = New-ScheduledTaskTrigger -Daily -At '00:00'
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$trigger.Repetition.StopAtDurationEnd = $false
Register-ScheduledTask -TaskName 'MarketFlow-AlphaLab-Telegram-Events' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Recover delivery of the latest completed AlphaLab decision only; exact-event receipt dedupe; opt-in private bot; no research or orders.' -Force | Out-Null
Write-Output 'Installed AlphaLab private Telegram event recovery every five minutes; no initial send started.'
