param([string]$Root = (Split-Path -Parent $PSScriptRoot))

$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$taskName = 'MarketFlow-Surge-Catalyst-Trace'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$workerPath = Join-Path $rootPath 'scripts\run_surge_trace.py'
foreach ($requiredPath in @($pythonPath, $workerPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw 'MarketFlow Python and surge trace worker must exist before installation.'
    }
}
Push-Location -LiteralPath $rootPath
try {
    & $pythonPath -X utf8 -c 'from app.services.surge_trace.service import run_once; assert callable(run_once)'
    if ($LASTEXITCODE -ne 0) { throw 'Surge trace worker imports failed.' }
} finally { Pop-Location }

$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-X utf8 -m scripts.run_surge_trace' -WorkingDirectory $rootPath
$startup = New-ScheduledTaskTrigger -AtStartup
$daily = New-ScheduledTaskTrigger -Daily -At '00:04'
$daily.Repetition = (New-ScheduledTaskTrigger -Once -At '00:04' -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$daily.Repetition.StopAtDurationEnd = $false
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($startup,$daily) -Settings $settings -Principal $principal -Description 'Read saved Korean surges; reverse trace attributed news and disclosures. No orders, paid models or notifications.' -Force | Out-Null
Write-Output "Installed $taskName. Bounded source lookup every five minutes."
