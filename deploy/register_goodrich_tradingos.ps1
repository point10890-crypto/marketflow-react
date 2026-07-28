$ErrorActionPreference = 'Stop'

$root = 'C:\GoodrichTradingOS'
$starter = 'C:\bitman_marketfloww\deploy\start_goodrich_tradingos.vbs'
$python = Join-Path $root '.venv\Scripts\python.exe'
$api = Join-Path $root 'services\api\src\goodrich\main.py'
$kis = Join-Path $root 'secrets\kis_credentials.txt'
$openai = Join-Path $root 'secrets\openai_credentials.txt'

foreach ($required in @($starter, $python, $api, $kis, $openai)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required Goodrich runtime file is missing: $required"
    }
}

$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$starter`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType S4U `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName 'Goodrich-TradingOS' `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName 'Goodrich-TradingOS'

$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest `
            -UseBasicParsing `
            -Uri 'http://127.0.0.1:8000/health' `
            -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch {
        # Continue bounded readiness polling.
    }
}

if (-not $ready) {
    throw 'Goodrich TradingOS did not become healthy on 127.0.0.1:8000.'
}

Write-Output 'Goodrich-TradingOS task registered and healthy.'
