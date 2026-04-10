# ─────────────────────────────────────────────────────────────────────
# MarketFlow 홈서버 셋업 (Windows 미니PC)
# 실행: PowerShell 관리자 모드에서
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\deploy\setup-windows.ps1
# ─────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Continue"
$PROJECT_DIR = "C:\bitman_marketfloww"

Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " MarketFlow 홈서버 셋업 (Windows)" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan

# ── 1. Chocolatey 설치 ──
Write-Host "`n▶ 1/7  Chocolatey 패키지 매니저" -ForegroundColor Yellow
if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
    Write-Host "  설치 중..."
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Write-Host "  [OK] Chocolatey 설치 완료" -ForegroundColor Green
} else {
    Write-Host "  [OK] Chocolatey 이미 설치됨" -ForegroundColor Green
}

# ── 2. Python 3.13 ──
Write-Host "`n▶ 2/7  Python 3.13" -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue) -or (python --version 2>&1) -notmatch "3\.1[3-9]") {
    choco install python313 -y --no-progress 2>$null
    refreshenv 2>$null
    Write-Host "  [OK] Python 설치" -ForegroundColor Green
} else {
    Write-Host "  [OK] Python $(python --version 2>&1)" -ForegroundColor Green
}

# ── 3. Git ──
Write-Host "`n▶ 3/7  Git" -ForegroundColor Yellow
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    choco install git -y --no-progress 2>$null
    refreshenv 2>$null
    Write-Host "  [OK] Git 설치" -ForegroundColor Green
} else {
    Write-Host "  [OK] Git $(git --version 2>&1)" -ForegroundColor Green
}

# ── 4. Node.js 20 LTS ──
Write-Host "`n▶ 4/7  Node.js 20 LTS" -ForegroundColor Yellow
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    choco install nodejs-lts -y --no-progress 2>$null
    refreshenv 2>$null
    Write-Host "  [OK] Node.js 설치" -ForegroundColor Green
} else {
    Write-Host "  [OK] Node.js $(node --version 2>&1)" -ForegroundColor Green
}

# ── 5. Cloudflared ──
Write-Host "`n▶ 5/7  Cloudflared" -ForegroundColor Yellow
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    choco install cloudflared -y --no-progress 2>$null
    refreshenv 2>$null
    Write-Host "  [OK] cloudflared 설치" -ForegroundColor Green
} else {
    Write-Host "  [OK] cloudflared 설치됨" -ForegroundColor Green
}

# ── 6. 프로젝트 클론 ──
Write-Host "`n▶ 6/7  프로젝트 디렉토리" -ForegroundColor Yellow
if (-not (Test-Path "$PROJECT_DIR\.git")) {
    Write-Host "  Git clone 중..."
    git clone https://github.com/point10890-crypto/marketflow-react.git $PROJECT_DIR 2>$null
    Write-Host "  [OK] 프로젝트 클론 완료" -ForegroundColor Green
} else {
    Set-Location $PROJECT_DIR
    git pull origin main 2>$null
    Write-Host "  [OK] 프로젝트 이미 존재 (pull 완료)" -ForegroundColor Green
}

# ── 7. Python venv + 의존성 ──
Write-Host "`n▶ 7/7  Python venv + 패키지" -ForegroundColor Yellow
Set-Location $PROJECT_DIR
if (-not (Test-Path "$PROJECT_DIR\.venv\Scripts\python.exe")) {
    Write-Host "  venv 생성 중..."
    python -m venv .venv
}
Write-Host "  pip install 중..."
& "$PROJECT_DIR\.venv\Scripts\pip.exe" install -r requirements.txt -q 2>$null
Write-Host "  [OK] venv + 패키지 설치 완료" -ForegroundColor Green

# ── 완료 ──
Write-Host "`n═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host " 셋업 완료!" -ForegroundColor Green
Write-Host ""
Write-Host " 남은 단계:"
Write-Host "   1. data/ 폴더 복사 (노트북 → 미니PC)"
Write-Host "   2. .env 파일 복사"
Write-Host "   3. Cloudflared 자격증명 복사:"
Write-Host "      C:\Users\<user>\.cloudflared\config.yml"
Write-Host "      C:\Users\<user>\.cloudflared\678e9c60-...json"
Write-Host "   4. 서비스 테스트:"
Write-Host "      cd $PROJECT_DIR"
Write-Host "      .venv\Scripts\python.exe flask_app.py"
Write-Host "   5. Task Scheduler에 autostart 등록"
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
