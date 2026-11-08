param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$taskName = 'MarketFlow-Top3-Advisor'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath = Join-Path $rootPath 'scripts\run_top3_advisor.py'
foreach ($requiredPath in @($pythonPath, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw 'The project Python and advisor worker must exist before installation.'
    }
}
Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'from app.services.mirofish.alpha_lab.advisor import run_once; assert callable(run_once)'
    if ($LASTEXITCODE -ne 0) { throw 'Advisor worker imports failed.' }
} finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_top3_advisor' -WorkingDirectory $rootPath
$startup = New-ScheduledTaskTrigger -AtStartup
$daily = New-ScheduledTaskTrigger -Daily -At '00:02'
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At '00:02' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$daily.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startup, $daily) -Settings $settings -Principal $principal -Description 'Saved TOP3 news-grounded debate; shared evidence budget; no orders or notifications.' -Force | Out-Null
Write-Output "Installed $taskName. Runs every five minutes with durable stage reuse."
