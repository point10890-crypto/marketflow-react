$ErrorActionPreference = 'Stop'

$root = 'C:\GoodrichTradingOS'
$python = Join-Path $root '.venv\Scripts\python.exe'
$apiDir = Join-Path $root 'services\api'
$logDir = Join-Path $root 'logs'

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$env:PYTHONIOENCODING = 'utf-8'
$env:GOODRICH_ENVIRONMENT = 'production'
$env:GOODRICH_DATABASE_URL = 'sqlite:///C:/GoodrichTradingOS/data/goodrich.db'
$env:GOODRICH_KIS_CREDENTIALS_FILE = Join-Path $root 'secrets\kis_credentials.txt'
$env:GOODRICH_OPENAI_CREDENTIALS_FILE = Join-Path $root 'secrets\openai_credentials.txt'
$env:GOODRICH_CORS_ORIGINS = 'https://bit-man.net,https://www.bit-man.net'

Set-Location -LiteralPath $apiDir
& $python -m uvicorn goodrich.main:app --host 127.0.0.1 --port 8000 `
    1>> (Join-Path $logDir 'goodrich.out.log') `
    2>> (Join-Path $logDir 'goodrich.err.log')
