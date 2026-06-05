$logPath = "C:\bitman_marketfloww\logs\scheduler.log"
$content = Get-Content $logPath -Encoding UTF8

# 04-24 morning to 16:00
Write-Host "=== 04-24 04:00-16:30 VCP-related lines ==="
foreach ($line in $content) {
    if ($line -match "^2026-04-24" -and $line -match "vcp|VCP|signal_tracker|run_vcp") {
        Write-Host $line
    }
}

Write-Host ""
Write-Host "=== Search for vcp_kr_latest write events on any date ==="
$idx = 0
foreach ($line in $content) {
    if ($line -match "vcp_kr_latest") {
        Write-Host "$($idx): $line"
    }
    $idx++
}
