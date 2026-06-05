# Append Devil's Advocate env vars if not present
$envFile = "C:\bitman_marketfloww\.env"
$content = Get-Content $envFile -Raw
if ($content -match "DEVIL_ADVOCATE_ENABLED") {
    Write-Host "ALREADY_PRESENT"
    exit 0
}
$append = @"

# Devil's Advocate (Claude Haiku 4.5 - consensus_strong post-review)
DEVIL_ADVOCATE_ENABLED=1
DEVIL_ADVOCATE_MODEL=claude-haiku-4-5-20251001
DEVIL_ADVOCATE_TIMEOUT=30
"@
Add-Content -Path $envFile -Value $append -Encoding UTF8
Write-Host "ADDED"
