# auto_runner tunables env vars 추가
$envFile = "C:\bitman_marketfloww\.env"
$content = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
if ($content -and ($content -match "MIROFISH_AUTO_RUNNER_MIN_ALPHA")) {
    Write-Host "ALREADY_PRESENT"
    exit 0
}
$append = @"

# === MCP Auto-Runner tunables (Stage 2 자동 실행기) ===
MIROFISH_AUTO_RUNNER_ENABLED=1
MIROFISH_AUTO_RUNNER_MIN_ALPHA=55
MIROFISH_AUTO_RUNNER_MAX_RISK=60
MIROFISH_AUTO_RUNNER_MIN_NEW=2
MIROFISH_AUTO_RUNNER_COOLDOWN_MIN=15
MIROFISH_AUTO_RUNNER_DAILY_CAP_USD=5.0
MIROFISH_AUTO_RUNNER_ALLOW_STALE=1
"@
Add-Content -Path $envFile -Value $append -Encoding UTF8
Write-Host "ADDED"
