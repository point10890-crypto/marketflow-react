$ErrorActionPreference = "Stop"

$root = "C:\bitman_marketfloww"
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"
$outLog = Join-Path $logDir "goodrich_intraday.out.log"
$errLog = Join-Path $logDir "goodrich_intraday.err.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location -LiteralPath $root

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"

& $python (Join-Path $root "scripts\run_goodrich_intraday_cycle.py") `
    1>> $outLog `
    2>> $errLog

exit $LASTEXITCODE
