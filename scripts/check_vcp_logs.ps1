$logPath = "C:\bitman_marketfloww\logs\scheduler.log"
$content = Get-Content $logPath -Encoding UTF8

Write-Host "=== Total lines: $($content.Length) ==="

Write-Host ""
Write-Host "=== VCP-related lines (last 40) ==="
$matches = @()
for ($i = 0; $i -lt $content.Length; $i++) {
    $line = $content[$i]
    if ($line -match "VCP|vcp_all|vcp_kr|vcp_us|signal_tracker|run_vcp") {
        $matches += "$($i+1): $line"
    }
}
Write-Host "Total VCP matches: $($matches.Count)"
$matches | Select-Object -Last 40 | ForEach-Object { Write-Host $_ }

Write-Host ""
Write-Host "=== 16:00 schedule entries (last 20) ==="
$sched = @()
for ($i = 0; $i -lt $content.Length; $i++) {
    $line = $content[$i]
    if ($line -match "16:00|VCP_UPDATE_TIME") {
        $sched += "$($i+1): $line"
    }
}
$sched | Select-Object -Last 20 | ForEach-Object { Write-Host $_ }
