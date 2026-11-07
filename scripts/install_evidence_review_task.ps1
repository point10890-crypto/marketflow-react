param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$taskName = 'MarketFlow-Evidence-Review'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath = Join-Path $rootPath 'scripts\run_evidence_review.py'
foreach ($requiredPath in @($pythonPath, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw 'The project Python and saved evidence worker must exist before installation.'
    }
}
Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'import filelock; from app.services.evidence_review import run_once; assert callable(run_once)'
    if ($LASTEXITCODE -ne 0) { throw 'Saved evidence worker imports failed.' }
} finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_evidence_review' -WorkingDirectory $rootPath
$startup = New-ScheduledTaskTrigger -AtStartup
$daily = New-ScheduledTaskTrigger -Daily -At '00:00'
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At '00:00' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$daily.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startup, $daily) -Settings $settings -Principal $principal -Description 'Saved bounded article and AlphaLab evidence interpretation; no orders or notifications.' -Force | Out-Null
Write-Output "Installed $taskName. Runs at startup and every five minutes; overlapping runs are ignored."
