$ErrorActionPreference = "Stop"

$taskName = "MarketFlow-Goodrich-30Min"
$launcher = "C:\bitman_marketfloww\deploy\run_goodrich_monitor.ps1"
$taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$launcher`""

if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Goodrich monitor launcher not found: $launcher"
}

schtasks.exe /Create `
    /TN $taskName `
    /TR $taskCommand `
    /SC MINUTE `
    /MO 30 `
    /ST 09:00 `
    /RU SYSTEM `
    /RL HIGHEST `
    /F | Out-Null

Write-Output "$taskName registered. The Python runner skips calls outside KRX market hours."
