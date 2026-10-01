param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$builderPath = Join-Path $rootPath 'scripts\build_chart_analogue_index.py'
$collectorPath = Join-Path $rootPath 'scripts\refresh_chart_analogue_prices.py'
$evaluationPath = Join-Path $rootPath 'scripts\evaluate_chart_analogue_shadow.py'
$pricesPath = Join-Path $rootPath 'data\daily_prices.csv'
$indexPath = Join-Path $rootPath 'data\chart_analogue'
$closedPricesPath = Join-Path $indexPath 'closed_prices.csv'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $builderPath) -or -not (Test-Path -LiteralPath $collectorPath) -or -not (Test-Path -LiteralPath $pricesPath)) {
    throw 'Chart analogue refresh requires the project Python, collector, builder and universe source.'
}
Set-Location -LiteralPath $rootPath
$env:PYTHONIOENCODING = 'utf-8'
& $pythonPath $collectorPath --prices $pricesPath --output $closedPricesPath --workers 4
if ($LASTEXITCODE -ne 0) { throw "Completed daily price collection failed: $LASTEXITCODE; existing index preserved." }
& $pythonPath $builderPath --prices $closedPricesPath --output $indexPath --price-basis provider_adjusted --source-id naver_closed_daily
if ($LASTEXITCODE -ne 0) { throw "Chart analogue index refresh failed: $LASTEXITCODE" }
& $pythonPath $evaluationPath --ingest-latest
if ($LASTEXITCODE -ne 0) { throw "Chart analogue outcome evaluation failed: $LASTEXITCODE; prepared price index retained." }
