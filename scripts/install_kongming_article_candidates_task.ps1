param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$taskName = 'MarketFlow-Kongming-Article-Candidates'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath = Join-Path $rootPath 'scripts\run_kongming_article_candidates.py'
foreach ($requiredPath in @($pythonPath, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw 'The MarketFlow project Python and article collector must exist before installation.'
    }
}

Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'import filelock, requests; from app.services.kongming_article_candidates import run_once; assert callable(run_once)'
    if ($LASTEXITCODE -ne 0) {
        throw 'Article collector imports failed. Install the MarketFlow runtime dependencies before registering the task.'
    }
} finally {
    Pop-Location
}

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_kongming_article_candidates' -WorkingDirectory $rootPath
$startup = New-ScheduledTaskTrigger -AtStartup
$daily = New-ScheduledTaskTrigger -Daily -At '00:00'
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes 1) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$daily.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startup, $daily) -Settings $settings -Principal $principal -Description 'Collect BusinessPost RSS article candidates on the saved MarketFlow schedule.' -Force | Out-Null
Write-Output "Installed $taskName. Checks for a due poll at startup and every minute."
