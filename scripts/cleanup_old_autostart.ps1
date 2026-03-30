#Requires -RunAsAdministrator
<#
.SYNOPSIS
    기존 자동시작 인프라 정리 (NSSM 서비스 전환 후 실행)
#>

Write-Host "`n=== Cleanup Old Auto-Start Infrastructure ===" -ForegroundColor Yellow

# 1. Startup 폴더 batch 파일 제거
$startup = [Environment]::GetFolderPath('Startup')
$files = @("MarketFlow_AutoStart.bat", "MarketFlow_Guardian.bat", "cloudflared-tunnel.bat")
foreach ($f in $files) {
    $path = Join-Path $startup $f
    if (Test-Path $path) {
        Remove-Item $path -Force
        Write-Host "  Removed: $path" -ForegroundColor Green
    } else {
        Write-Host "  Not found: $f" -ForegroundColor Gray
    }
}

# 2. Task Scheduler 항목 제거
try {
    Unregister-ScheduledTask -TaskName "MarketFlow-AutoStart" -Confirm:$false -ErrorAction Stop
    Write-Host "  Removed Task: MarketFlow-AutoStart" -ForegroundColor Green
} catch {
    Write-Host "  Task 'MarketFlow-AutoStart' not found or already removed" -ForegroundColor Gray
}

# 3. 기존 watchdog/guardian 프로세스 중지
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*watchdog.py*' -or
    $_.CommandLine -like '*guardian*'
} | ForEach-Object {
    Write-Host "  Killing: PID $($_.ProcessId) ($($_.Name))" -ForegroundColor Gray
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
}

# 4. 스테일 PID 파일 정리
$pidFiles = @("C:\bitman_marketfloww\logs\watchdog.pid", "C:\bitman_marketfloww\logs\watchdog.heartbeat")
foreach ($p in $pidFiles) {
    if (Test-Path $p) {
        Remove-Item $p -Force
        Write-Host "  Removed: $p" -ForegroundColor Green
    }
}

Write-Host "`nCleanup complete. Old auto-start infrastructure removed.`n" -ForegroundColor Cyan
Write-Host "Files kept for reference (not deleted):" -ForegroundColor Gray
Write-Host "  - watchdog.py, guardian.bat, auto_start_scheduler.bat" -ForegroundColor Gray
