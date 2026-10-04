param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$collectorPath = Join-Path $rootPath 'scripts\refresh_alpha_lab_inputs.py'
$researchPath = Join-Path $rootPath 'scripts\run_alpha_lab.py'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $collectorPath) -or -not (Test-Path -LiteralPath $researchPath)) {
    throw 'AlphaLab requires the project Python, source collector and fixed research runner.'
}
Set-Location -LiteralPath $rootPath
$env:PYTHONIOENCODING = 'utf-8'
& $pythonPath $collectorPath --fetch
$sourceExit = $LASTEXITCODE
if ($sourceExit -ne 0) {
    Write-Warning 'AlphaLab input refresh held; previous immutable snapshot retained. Research will expose that fallback.'
}
& $pythonPath $researchPath
if ($LASTEXITCODE -ne 0) { throw 'AlphaLab research failed; previous saved report retained.' }
if ($sourceExit -ne 0) { exit 2 }
