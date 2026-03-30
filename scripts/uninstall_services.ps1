#Requires -RunAsAdministrator
<#
.SYNOPSIS
    MarketFlow NSSM 서비스 제거 (롤백용)
#>

$NSSM = "C:\bitman_marketfloww\nssm.exe"

Write-Host "`n=== Uninstalling MarketFlow Services ===" -ForegroundColor Yellow

foreach ($svc in @("MarketFlow-Flask", "MarketFlow-Scheduler")) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) {
        & $NSSM stop $svc confirm 2>$null
        & $NSSM remove $svc confirm 2>$null
        Write-Host "  Removed: $svc" -ForegroundColor Green
    } else {
        Write-Host "  Not found: $svc" -ForegroundColor Gray
    }
}

Write-Host "`nNote: Cloudflared service not removed (use 'cloudflared service uninstall' separately)`n" -ForegroundColor Gray
