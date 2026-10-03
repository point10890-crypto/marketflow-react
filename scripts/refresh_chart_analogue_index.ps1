param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
$builderPath = Join-Path $rootPath 'scripts\build_chart_analogue_index.py'
$collectorPath = Join-Path $rootPath 'scripts\refresh_chart_analogue_prices.py'
$evaluationPath = Join-Path $rootPath 'scripts\evaluate_chart_analogue_shadow.py'
$scanPath = Join-Path $rootPath 'scripts\scan_chart_analogue_top3.py'
$kellyScanPath = Join-Path $rootPath 'scripts\scan_chart_analogue_kelly.py'
$pricesPath = Join-Path $rootPath 'data\daily_prices.csv'
$indexPath = Join-Path $rootPath 'data\chart_analogue'
$closedPricesPath = Join-Path $indexPath 'closed_prices.csv'
$kellyRootPath = Join-Path $indexPath 'kelly'
$kellyUniversePath = Join-Path $kellyRootPath 'universe.json'
if (-not (Test-Path -LiteralPath $pythonPath) -or -not (Test-Path -LiteralPath $builderPath) -or -not (Test-Path -LiteralPath $collectorPath) -or -not (Test-Path -LiteralPath $evaluationPath) -or -not (Test-Path -LiteralPath $scanPath) -or -not (Test-Path -LiteralPath $pricesPath)) {
    throw 'Chart analogue refresh requires the project Python, collector, builder, evaluator, TOP3 scanner and universe source.'
}
Set-Location -LiteralPath $rootPath
$env:PYTHONIOENCODING = 'utf-8'
& $pythonPath $collectorPath --prices $pricesPath --output $closedPricesPath --workers 4
if ($LASTEXITCODE -ne 0) { throw "Completed daily price collection failed: $LASTEXITCODE; existing index preserved." }
& $pythonPath $builderPath --prices $closedPricesPath --output $indexPath --price-basis provider_adjusted --source-id naver_closed_daily
if ($LASTEXITCODE -ne 0) { throw "Chart analogue index refresh failed: $LASTEXITCODE" }
& $pythonPath $evaluationPath --ingest-latest
if ($LASTEXITCODE -ne 0) { throw "Chart analogue outcome evaluation failed: $LASTEXITCODE; prepared price index retained." }
& $pythonPath $scanPath
if ($LASTEXITCODE -ne 0) { throw "Chart analogue TOP3 scan failed: $LASTEXITCODE; prepared price index retained." }

# This optional stage reads the existing dated large-cap/quality scope and
# freshly prepared index. It never acquires financial data or places orders.
if ((Test-Path -LiteralPath $kellyScanPath) -and (Test-Path -LiteralPath $kellyUniversePath)) {
    & $pythonPath $kellyScanPath --root $kellyRootPath --index-root $indexPath --universe $kellyUniversePath
    $kellyExitCode = $LASTEXITCODE
    if ($kellyExitCode -eq 2) {
        Write-Warning 'Chart analogue Kelly research scan held: prepared scope or data require validation; prepared price index retained.'
    } elseif ($kellyExitCode -ne 0) {
        throw "Chart analogue Kelly research scan failed: $kellyExitCode; prepared price index retained."
    }
} else {
    Write-Output 'Chart analogue Kelly research scan skipped: prepared scanner and dated TOP100 quality universe are required.'
}
