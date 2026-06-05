# 본PC scheduled task cleanup
#   - MarketFlow 4개: Disable (production은 miniPC가 담당, 본PC는 dev/test용)
#   - AutoTrading 3개: S4U + Hidden=True (기능 유지하되 화면 팝업 제거)
# Run as Administrator

$disableTargets = @(
    'MarketFlow-AutoStart',
    'MarketFlow-V1-Flask',
    'MarketFlow-MiroFish-MCP',
    'MarketFlow-MCP-Tunnel'
)
$hideTargets = @(
    'AutoTraderScheduler',
    'AutoTrading_PaperStart',
    'AutoTrading_TokenRefresh'
)

Write-Host "=== STEP 1: Disable MarketFlow tasks ===" -ForegroundColor Cyan
foreach ($t in $disableTargets) {
    try {
        Disable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
        Write-Host "  $t -> Disabled" -ForegroundColor Green
    } catch {
        Write-Host "  $t -> FAILED: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== STEP 2: Hide AutoTrading tasks (S4U + Hidden) ===" -ForegroundColor Cyan
foreach ($t in $hideTargets) {
    try {
        $task = Get-ScheduledTask -TaskName $t -ErrorAction Stop
        $oldLogon = $task.Principal.LogonType
        $oldHidden = $task.Settings.Hidden
        $newPrincipal = New-ScheduledTaskPrincipal -UserId $task.Principal.UserId -LogonType S4U -RunLevel $task.Principal.RunLevel
        $newSettings = $task.Settings
        $newSettings.Hidden = $true
        Set-ScheduledTask -TaskName $t -Principal $newPrincipal -Settings $newSettings -ErrorAction Stop | Out-Null
        Write-Host "  $t : LogonType $oldLogon -> S4U, Hidden $oldHidden -> True" -ForegroundColor Green
    } catch {
        Write-Host "  $t -> FAILED: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "=== Verification ===" -ForegroundColor Cyan
@($disableTargets + $hideTargets) | ForEach-Object {
    $info = Get-ScheduledTask -TaskName $_ -ErrorAction SilentlyContinue
    if ($info) {
        Write-Host ("{0,-32} State={1,-10} LogonType={2,-12} Hidden={3}" -f $info.TaskName, $info.State, $info.Principal.LogonType, $info.Settings.Hidden)
    }
}

Write-Host ""
Write-Host "Done. Press Enter to close." -ForegroundColor Cyan
Read-Host
