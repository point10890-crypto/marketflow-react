# miniPC 배포 후 최종 검증 — git pull 직후 한 번 실행
#
#   cd C:\bitman_marketfloww
#   powershell -ExecutionPolicy Bypass -File scripts\minipc_post_deploy_check.ps1
#
# 전부 [OK] 면 배포 마무리. [FAIL] 이 하나라도 있으면 해당 섹션의 안내를 따른다.
# (cp949 콘솔 호환을 위해 출력은 ASCII 위주)

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$PROJECT = 'C:\bitman_marketfloww'
$PYTHON  = "$PROJECT\.venv\Scripts\python.exe"
$fail = 0

function Report([bool]$ok, [string]$label, [string]$hint = '') {
    if ($ok) { Write-Host "[OK]   $label" }
    else {
        Write-Host "[FAIL] $label"
        if ($hint) { Write-Host "       -> $hint" }
        $script:fail++
    }
}

Set-Location $PROJECT
Write-Host "=== MarketFlow miniPC post-deploy check ==="

# ── 1. git 상태: main 최신인지 ─────────────────────────────
git fetch origin main 2>$null | Out-Null
$local  = (git rev-parse HEAD).Trim()
$remote = (git rev-parse origin/main).Trim()
$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Report ($branch -eq 'main') "branch = main (now: $branch)" "git checkout main"
Report ($local -eq $remote) "HEAD == origin/main ($($local.Substring(0,7)))" "git pull origin main"

# ── 2. 파이썬 임포트 + 앱 부팅 (운영 워커 미기동) ──────────
$boot = & $PYTHON -c @"
from app import create_app
app = create_app({'TESTING': True, 'SECRET_KEY': 'check', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'SQLALCHEMY_ENGINE_OPTIONS': {}})
from app.services.mirofish import decision_brief, decision_cache, decision_jobs, service_guard, number_guard
import scheduler
print('BOOT_OK')
"@ 2>&1
Report ($boot -match 'BOOT_OK') "create_app + decision/guard/scheduler imports" "python import error above"

# ── 3. 빠른 스모크 테스트 (풀스위트는 CI 가 이미 통과) ─────
& $PYTHON -m pytest tests/test_signal_contract.py tests/test_decision_cache.py tests/test_aibrain_service_guard.py -q -p no:cacheprovider 2>&1 | Select-Object -Last 3
Report ($LASTEXITCODE -eq 0) "smoke pytest (contract/quota/guard)" "run full: python -m pytest tests/ -q"

# ── 4. 서비스 살아있는지: Flask 5001 ───────────────────────
try {
    $resp = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 'http://localhost:5001/api/kr/market-gate'
    Report ($resp.StatusCode -eq 200) "Flask 5001 /api/kr/market-gate ($($resp.StatusCode))"
} catch {
    Report $false "Flask 5001 /api/kr/market-gate" "restart: run_flask.bat 또는 MarketFlow Flask 태스크 재시작 (8080 은 절대 건드리지 말 것)"
}

# ── 5. 예약 태스크 상태 (SYSTEM AtStartup 3종 + Claw) ──────
foreach ($t in 'MarketFlow-Scheduler', 'MarketFlow-Scheduler-Watchdog', 'MarketFlow-Claw', 'MarketFlow-Claw-Watchdog') {
    $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
    if ($null -eq $task) { Report $false "task $t" "deploy\register_tasks.ps1 / register_claw_task.ps1 로 재등록" }
    else { Report ($task.State -ne 'Disabled') "task $t ($($task.State))" "Enable-ScheduledTask -TaskName $t" }
}

# ── 6. 스케줄러 하트비트 신선도 (<10분) ────────────────────
$hb = Get-ChildItem "$PROJECT\logs" -Filter '*heartbeat*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($null -eq $hb) { Report $false "scheduler heartbeat file" "logs\ 에 heartbeat 없음 - 스케줄러 기동 확인" }
else {
    $age = (Get-Date) - $hb.LastWriteTime
    Report ($age.TotalMinutes -lt 10) "scheduler heartbeat ($([int]$age.TotalMinutes)m ago: $($hb.Name))" "watchdog 5분 주기 재기동 대기 또는 수동 재시작"
}

Write-Host "==========================================="
if ($fail -eq 0) { Write-Host "ALL CHECKS PASSED - deploy complete"; exit 0 }
else { Write-Host "$fail check(s) FAILED - see hints above"; exit 1 }
