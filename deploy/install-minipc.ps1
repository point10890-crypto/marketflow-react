# ─────────────────────────────────────────────────────────────────────
# MarketFlow 미니PC 올인원 설치 스크립트
# PowerShell 관리자 모드에서 실행:
#   powershell -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/point10890-crypto/marketflow-react/main/deploy/install-minipc.ps1 | iex"
# ─────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Continue"
$PROJECT_DIR = "C:\bitman_marketfloww"
$NOTEBOOK_IP = "192.168.45.129"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " MarketFlow 미니PC 올인원 설치" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── 1. Git 확인/설치 ──
Write-Host "`n[1/8] Git 확인..." -ForegroundColor Yellow
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  Git 설치 중 (winget)..."
    winget install Git.Git --accept-package-agreements --accept-source-agreements 2>$null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "  winget 실패 → choco 시도..." -ForegroundColor Yellow
        if (Get-Command choco -ErrorAction SilentlyContinue) {
            choco install git -y --no-progress 2>$null
        } else {
            Write-Host "  [ERROR] Git 설치 실패. 수동 설치 필요: https://git-scm.com" -ForegroundColor Red
            exit 1
        }
    }
}
Write-Host "  [OK] Git $(git --version 2>&1)" -ForegroundColor Green

# ── 2. Python 확인 ──
Write-Host "`n[2/8] Python 확인..." -ForegroundColor Yellow
$pythonCmd = $null
foreach ($cmd in @("python", "python3", "py")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $ver = & $cmd --version 2>&1
        if ($ver -match "3\.\d+") { $pythonCmd = $cmd; break }
    }
}
if (-not $pythonCmd) {
    Write-Host "  Python 설치 중 (winget)..."
    winget install Python.Python.3.13 --accept-package-agreements --accept-source-agreements 2>$null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    $pythonCmd = "python"
}
Write-Host "  [OK] $($pythonCmd) $(& $pythonCmd --version 2>&1)" -ForegroundColor Green

# ── 3. 프로젝트 클론 ──
Write-Host "`n[3/8] 프로젝트 클론..." -ForegroundColor Yellow
if (Test-Path "$PROJECT_DIR\.git") {
    Write-Host "  이미 존재 → git pull..."
    Set-Location $PROJECT_DIR
    git pull origin main 2>$null
    Write-Host "  [OK] 프로젝트 업데이트 완료" -ForegroundColor Green
} else {
    if (Test-Path $PROJECT_DIR) { Remove-Item $PROJECT_DIR -Recurse -Force 2>$null }
    git clone https://github.com/point10890-crypto/marketflow-react.git $PROJECT_DIR 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERROR] git clone 실패" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] 프로젝트 클론 완료" -ForegroundColor Green
}

# ── 4. Python venv ──
Write-Host "`n[4/8] Python venv 생성..." -ForegroundColor Yellow
Set-Location $PROJECT_DIR
if (-not (Test-Path "$PROJECT_DIR\.venv\Scripts\python.exe")) {
    & $pythonCmd -m venv .venv
}
Write-Host "  pip install 중 (시간 소요)..."
& "$PROJECT_DIR\.venv\Scripts\pip.exe" install -r requirements.txt -q 2>$null
Write-Host "  [OK] venv + 패키지 완료" -ForegroundColor Green

# ── 5. 방화벽 규칙 (노트북 접근 허용) ──
Write-Host "`n[5/8] 방화벽 규칙..." -ForegroundColor Yellow
try {
    netsh advfirewall firewall add rule name="MarketFlow Flask" dir=in action=allow protocol=tcp localport=5001 2>$null
    Write-Host "  [OK] 5001 포트 허용" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] 방화벽 규칙 추가 실패 (관리자 권한 필요)" -ForegroundColor Yellow
}

# ── 6. 노트북에서 데이터 다운로드 ──
Write-Host "`n[6/8] 노트북에서 데이터 다운로드..." -ForegroundColor Yellow
$dataDir = "$PROJECT_DIR\data"
if (-not (Test-Path $dataDir)) { New-Item -ItemType Directory -Path $dataDir -Force | Out-Null }

# tar.gz 다운로드 시도
$tarFile = "$dataDir\marketflow_data.tar.gz"
try {
    Write-Host "  http://${NOTEBOOK_IP}:9999 에서 다운로드 시도..."
    Invoke-WebRequest -Uri "http://${NOTEBOOK_IP}:9999/marketflow_data.tar.gz" -OutFile $tarFile -TimeoutSec 30 -ErrorAction Stop
    Write-Host "  [OK] 데이터 아카이브 다운로드 완료" -ForegroundColor Green

    # tar 풀기
    Write-Host "  압축 해제 중..."
    Set-Location $PROJECT_DIR
    tar xzf $tarFile 2>$null
    Write-Host "  [OK] 데이터 압축 해제 완료" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] 노트북 HTTP 서버 접근 불가" -ForegroundColor Yellow
    Write-Host "  → 수동으로 data/ 폴더를 복사해야 합니다" -ForegroundColor Yellow
}

# .env 다운로드
try {
    Invoke-WebRequest -Uri "http://${NOTEBOOK_IP}:9999/install.bat" -OutFile "$PROJECT_DIR\install.bat" -TimeoutSec 5 -ErrorAction Stop 2>$null
} catch {}

# ── 7. Cloudflared 자격증명 ──
Write-Host "`n[7/8] Cloudflared 자격증명..." -ForegroundColor Yellow
try {
    Invoke-WebRequest -Uri "http://${NOTEBOOK_IP}:9999/cloudflared_config.yml" -OutFile "$env:USERPROFILE\.cloudflared\config.yml" -TimeoutSec 5 -ErrorAction Stop
    Invoke-WebRequest -Uri "http://${NOTEBOOK_IP}:9999/cloudflared_cred.json" -OutFile "$env:USERPROFILE\.cloudflared\678e9c60-9f8d-4f49-9fba-a49400ef4ca0.json" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "  [OK] Cloudflared 자격증명 복사 완료" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] 자격증명 다운로드 실패 → 수동 복사 필요" -ForegroundColor Yellow
}

# ── 8. Cloudflared 설치 ──
Write-Host "`n[8/8] Cloudflared..." -ForegroundColor Yellow
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "  설치 중 (winget)..."
    winget install Cloudflare.cloudflared --accept-package-agreements --accept-source-agreements 2>$null
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    Write-Host "  [OK] cloudflared 설치됨" -ForegroundColor Green
} else {
    Write-Host "  [WARN] cloudflared 수동 설치 필요" -ForegroundColor Yellow
}

# ── 완료 ──
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 설치 완료!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host " 테스트:"
Write-Host "   cd $PROJECT_DIR"
Write-Host "   .venv\Scripts\python.exe flask_app.py"
Write-Host ""
Write-Host " .env 파일이 없으면 노트북에서 수동 복사 필요"
Write-Host "========================================" -ForegroundColor Cyan
