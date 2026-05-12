# register_mirofish_tunnel_task.ps1
# Windows Task Scheduler 에 'MarketFlow-MCP-Tunnel' 작업 등록
# schtasks.exe (Windows 표준) 사용 — PowerShell 5.1 cmdlet 호환성 회피
#
# 동작:
#   - 매 5분 trigger (사용자 로그온 후 시작) — launcher 가 idempotent 이라
#     이미 listener 살아있으면 skip, 끊겨있으면 재가동
#   - 사용자 계정 (현재 로그인) 으로 실행 — SSH 키 접근 위해
#
# 제거: schtasks /delete /tn "MarketFlow-MCP-Tunnel" /f

$TaskName   = 'MarketFlow-MCP-Tunnel'
$ScriptPath = 'C:\bitman_marketfloww\scripts\start_mirofish_tunnel.ps1'

if (-not (Test-Path $ScriptPath)) {
    Write-Host "ERROR: launcher not found: $ScriptPath" -ForegroundColor Red
    exit 1
}

# 기존 작업 제거 (있으면)
$existing = schtasks /query /tn $TaskName 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "기존 작업 제거: $TaskName"
    schtasks /delete /tn $TaskName /f | Out-Null
}

# 실행 명령
$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

# schtasks /sc minute /mo 5 — 매 5분 실행
# /st 00:00 부터 매일 24시간 반복
# /ru <user> — 현재 사용자 계정 (SSH key access 위해)
# /it — interactive task only (SYSTEM 계정 아님)
# /rl LIMITED — 표준 권한
# /f — 강제 (확인 prompt 회피)
$createArgs = @(
    '/create',
    '/tn', $TaskName,
    '/tr', $cmd,
    '/sc', 'minute',
    '/mo', '5',
    '/st', '00:00',
    '/ru', $env:USERNAME,
    '/it',
    '/rl', 'LIMITED',
    '/f'
)

Write-Host "schtasks $($createArgs -join ' ')"
& schtasks @createArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: schtasks /create 실패 (exit code $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 검증
Write-Host ""
Write-Host "✓ 작업 등록 완료" -ForegroundColor Green
schtasks /query /tn $TaskName /fo LIST | Select-String -Pattern 'TaskName|Status|Next Run|Last Run|Last Result|Schedule Type|Repeat: Every'

Write-Host ""
Write-Host "즉시 1회 실행:"
Write-Host "  schtasks /run /tn $TaskName"
Write-Host "제거:"
Write-Host "  schtasks /delete /tn $TaskName /f"
