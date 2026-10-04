param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$collectorPath = Join-Path $rootPath 'scripts\refresh_alpha_lab_inputs.py'
$researchPath = Join-Path $rootPath 'scripts\run_alpha_lab.py'
$monitorPath = Join-Path $rootPath 'scripts\run_alpha_lab_monitor.py'
foreach ($requiredPath in @($pythonPath, $collectorPath, $researchPath, $monitorPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) { throw 'AlphaLab requires the project runtime, source collector, research and calendar checker.' }
}
Set-Location -LiteralPath $rootPath
$env:PYTHONIOENCODING = 'utf-8'
& $pythonPath $monitorPath calendar-check --root (Join-Path $rootPath 'data\alpha_lab')
$calendarExit = $LASTEXITCODE
if ($calendarExit -eq 10) {
    Write-Output 'AlphaLab completed-session refresh skipped: official closed date; saved research retained.'
    exit 0
}
if ($calendarExit -ne 0) {
    Write-Warning 'AlphaLab completed-session refresh held: official calendar unavailable; saved research retained.'
    exit 2
}
& $pythonPath $collectorPath --fetch
$sourceExit = $LASTEXITCODE
if ($sourceExit -ne 0) {
    Write-Warning 'AlphaLab input refresh held; previous immutable snapshot retained. Research will expose that fallback.'
}
& $pythonPath $researchPath
if ($LASTEXITCODE -ne 0) { throw 'AlphaLab research failed; previous saved report retained.' }
if ($sourceExit -ne 0) { exit 2 }
