param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference='Stop'
$rootPath=(Resolve-Path -LiteralPath $Root).Path
$pythonPath=Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath=Join-Path $rootPath 'scripts\run_kongming_technical.py'
foreach($path in @($pythonPath,$workerPath)) {
    if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw 'Project Python and technical worker are required.'}
}
Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'from app.services.mirofish.kongming_technical.service import run_once; assert callable(run_once)'
    if($LASTEXITCODE -ne 0){throw 'Technical worker import failed.'}
} finally {Pop-Location}
$action=New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_kongming_technical' -WorkingDirectory $rootPath
$startup=New-ScheduledTaskTrigger -AtStartup
$daily=New-ScheduledTaskTrigger -Daily -At '00:00'
$daily.Repetition=(New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$daily.Repetition.StopAtDurationEnd=$false
$settings=New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$principal=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'MarketFlow-Kongming-Technical' -Action $action -Trigger @($startup,$daily) -Settings $settings -Principal $principal -Description 'Bounded saved 20-session technical volume profiles; no LLM, orders or notifications.' -Force | Out-Null
Write-Output 'Installed MarketFlow-Kongming-Technical: startup and every minute, up to three due symbols per run.'
