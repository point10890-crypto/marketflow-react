param([string]$Root = (Split-Path -Parent $PSScriptRoot))
$ErrorActionPreference = 'Stop'
$rootPath = (Resolve-Path -LiteralPath $Root).Path
$refreshPath = Join-Path $rootPath 'scripts\refresh_chart_analogue_index.ps1'
$pythonPath = Join-Path $rootPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $refreshPath) -or -not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Refresh script and project Python must exist before installation.'
}
Write-Output 'Checking existing NumPy and requests dependencies:'
& $pythonPath -c 'import numpy, requests, urllib3; from urllib3.response import HTTPResponse; assert callable(HTTPResponse.read1); print(numpy.__version__, urllib3.__version__)'
if ($LASTEXITCODE -ne 0) { throw 'Install the existing NumPy/requests dependencies with urllib3 read1 support before installing the refresh task.' }
$taskName = 'MarketFlow-ChartAnalogue-Index'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$refreshPath`" -Root `"$rootPath`"" -WorkingDirectory $rootPath
$trigger = New-ScheduledTaskTrigger -Daily -At '18:10'
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Refresh completed daily bars and prepare historical chart analogue evidence after market close; no order or LLM calls.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output "Installed $taskName; daily refresh 18:10 local time; initial refresh started."
