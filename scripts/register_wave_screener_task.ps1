# register_wave_screener_task.ps1
# Windows Task Scheduler 에 'MarketFlow-Wave-Screener' 작업 등록
# schtasks.exe 사용 (PowerShell 5.1 cmdlet 호환성 회피)
#
# 스케줄: 매일 16:00 KST (장 마감 30분 후 — 데이터 안정 시점)
# 실행 계정: SYSTEM (사용자 로그아웃 상태에서도 동작)
# 권한: 표준 (LIMITED)
#
# 제거: schtasks /delete /tn "MarketFlow-Wave-Screener" /f

$TaskName   = 'MarketFlow-Wave-Screener'
$ScriptPath = 'C:\bitman_marketfloww\scripts\run_wave_screener.ps1'
$RunTime    = '16:00'   # KST 매일

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: launcher not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

# 기존 작업 제거
$existing = schtasks /query /tn $TaskName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "기존 작업 제거: $TaskName"
    schtasks /delete /tn $TaskName /f | Out-Null
}

# 실행 명령
$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

# schtasks /sc daily — 매일 1회
# /st 16:00       — 16:00 KST
# /ru SYSTEM      — SYSTEM 계정 (로그아웃 상태 OK)
# /rl HIGHEST     — SYSTEM 은 HIGHEST 필요
# /f              — 강제 (확인 prompt 회피)
$createArgs = @(
    '/create',
    '/tn', $TaskName,
    '/tr', $cmd,
    '/sc', 'daily',
    '/st', $RunTime,
    '/ru', 'SYSTEM',
    '/rl', 'HIGHEST',
    '/f'
)

Write-Host "schtasks $($createArgs -join ' ')"
& schtasks @createArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: schtasks /create 실패 (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 검증
Write-Host ""
Write-Host "[OK] 작업 등록 완료" -ForegroundColor Green
schtasks /query /tn $TaskName

Write-Host ""
Write-Host "즉시 1회 실행 (수분 소요):"
Write-Host "  schtasks /run /tn $TaskName"
Write-Host ""
Write-Host "로그 확인:"
Write-Host "  Get-Content C:\bitman_marketfloww\logs\wave_screener_yyyyMMdd.log -Tail 20"
