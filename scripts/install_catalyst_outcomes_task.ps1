param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
if ((Get-TimeZone).Id -ne 'Korea Standard Time') { throw 'This task requires Asia/Seoul Windows timezone.' }
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath = Join-Path $rootPath 'scripts\run_catalyst_outcomes.py'
foreach ($requiredPath in @($pythonPath,$workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw 'MarketFlow worker and Python are required.' }
}
Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'from app.services.catalyst_outcomes.service import run_once; assert callable(run_once)'
    if ($LASTEXITCODE -ne 0) { throw 'Catalyst outcomes import failed.' }
} finally { Pop-Location }
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_catalyst_outcomes' -WorkingDirectory $rootPath
$morning = New-ScheduledTaskTrigger -Daily -At '10:00'
$afternoon = New-ScheduledTaskTrigger -Daily -At '15:00'
# Completed slots exit without acquisition; only unfinished slots resume on this recovery trigger.
$recovery = New-ScheduledTaskTrigger -Daily -At '00:02'
$recovery.Repetition = (New-ScheduledTaskTrigger -Once -At '00:02' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$recovery.Repetition.StopAtDurationEnd = $false
$startup = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName 'MarketFlow-Catalyst-Outcomes' -Action $action -Trigger @($morning,$afternoon,$recovery,$startup) -Settings $settings -Principal $principal -Description 'Historical catalyst outcomes and current research candidates at 10:00/15:00 KST. Resume incomplete slots only. No orders, paid models or notifications.' -Force | Out-Null
Write-Output 'Installed MarketFlow-Catalyst-Outcomes: 10:00/15:00 KST, five-minute incomplete-slot recovery.'
