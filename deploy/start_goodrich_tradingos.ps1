param(
    [string]$Root = 'C:\GoodrichTradingOS',
    [string]$MarketFlowEnv = 'C:\bitman_marketfloww\.env'
)

$ErrorActionPreference = 'Stop'

$python = Join-Path $root '.venv\Scripts\python.exe'
$apiDir = Join-Path $root 'services\api'
$logDir = Join-Path $root 'logs'
$databaseFile = [IO.Path]::GetFullPath(
    (Join-Path $root 'data\goodrich.db')
).Replace('\', '/')

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Goodrich TradingOS Python runtime is missing.'
}
if (-not (Test-Path -LiteralPath $apiDir -PathType Container)) {
    throw 'Goodrich TradingOS API directory is missing.'
}

$sdkProbe = @'
from inspect import signature
from openai import OpenAI
client = OpenAI(api_key='compatibility-check')
create = getattr(getattr(client, 'responses', None), 'create', None)
parameters = set(signature(create).parameters) if callable(create) else set()
required = {'text', 'reasoning', 'max_output_tokens', 'store'}
raise SystemExit(0 if required.issubset(parameters) else 1)
'@
$global:LASTEXITCODE = $null
& $python -c $sdkProbe
$sdkProbeSucceeded = $?
$sdkProbeExitCode = $LASTEXITCODE
if (
    -not $sdkProbeSucceeded -or
    $null -eq $sdkProbeExitCode -or
    [int]$sdkProbeExitCode -ne 0
) {
    throw 'Goodrich OpenAI SDK Responses API support is required.'
}

function Read-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }
    foreach ($line in Get-Content -LiteralPath $Path -ErrorAction Stop) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*?)\s*$')) {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

$deepSeekApiKey = Read-EnvValue $marketFlowEnv 'DEEPSEEK_API_KEY'
if ([string]::IsNullOrWhiteSpace($deepSeekApiKey)) {
    throw 'DEEPSEEK_API_KEY is not configured for Goodrich TradingOS.'
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$env:PYTHONIOENCODING = 'utf-8'
$env:GOODRICH_ENVIRONMENT = 'production'
$env:GOODRICH_DATABASE_URL = "sqlite:///$databaseFile"
$env:GOODRICH_KIS_CREDENTIALS_FILE = Join-Path $root 'secrets\kis_credentials.txt'
$env:GOODRICH_DEEPSEEK_API_KEY = $deepSeekApiKey
$env:GOODRICH_DEEPSEEK_MODEL = 'deepseek-v4-pro'
$env:GOODRICH_DEEPSEEK_BASE_URL = 'https://api.deepseek.com'
$env:GOODRICH_OPENAI_CREDENTIALS_FILE = Join-Path $root 'secrets\openai_credentials.txt'
$env:GOODRICH_CORS_ORIGINS = 'https://bit-man.net,https://www.bit-man.net'

Set-Location -LiteralPath $apiDir
$ErrorActionPreference = 'Continue'
$global:LASTEXITCODE = $null
& $python -m uvicorn goodrich.main:app --host 127.0.0.1 --port 8000 `
    1>> (Join-Path $logDir 'goodrich.out.log') `
    2>> (Join-Path $logDir 'goodrich.err.log')
$processSucceeded = $?
$nativeExitCode = $LASTEXITCODE
$exitCode = if ($null -eq $nativeExitCode) { 1 } else { [int]$nativeExitCode }
if (-not $processSucceeded -and $exitCode -eq 0) {
    $exitCode = 1
}
$deepSeekApiKey = $null
Remove-Item Env:GOODRICH_DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
exit $exitCode
