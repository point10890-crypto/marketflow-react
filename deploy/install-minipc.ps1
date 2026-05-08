$ErrorActionPreference = "Stop"

$ProjectDir = $env:MARKETFLOW_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = "C:\bitman_marketfloww"
}

$RepoUrl = $env:MARKETFLOW_REPO_URL
if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
    $RepoUrl = "https://github.com/point10890-crypto/marketflow-react.git"
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " MarketFlow MiniPC install/update" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

function Assert-Command($Name, $InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required. $InstallHint"
    }
}

Assert-Command "git" "Install Git for Windows first."
Assert-Command "python" "Install Python 3.11+ first."

Write-Host "[1/5] Sync repository" -ForegroundColor Yellow
if (Test-Path "$ProjectDir\.git") {
    Set-Location $ProjectDir
    git fetch origin main
    git pull --ff-only origin main
} else {
    if (Test-Path $ProjectDir) {
        throw "$ProjectDir exists but is not a git repository. Move it first."
    }
    git clone $RepoUrl $ProjectDir
    Set-Location $ProjectDir
}

Write-Host "[2/5] Python virtualenv" -ForegroundColor Yellow
if (-not (Test-Path "$ProjectDir\.venv\Scripts\python.exe")) {
    python -m venv "$ProjectDir\.venv"
}
& "$ProjectDir\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$ProjectDir\.venv\Scripts\pip.exe" install -r "$ProjectDir\requirements.txt"

Write-Host "[3/5] Firewall rule for Flask 5001" -ForegroundColor Yellow
try {
    netsh advfirewall firewall add rule name="MarketFlow Flask 5001" dir=in action=allow protocol=tcp localport=5001 | Out-Null
} catch {
    Write-Host "Firewall rule was not changed. Run as Administrator if remote access is needed." -ForegroundColor Yellow
}

Write-Host "[4/5] Register scheduled tasks" -ForegroundColor Yellow
& "$ProjectDir\deploy\register_tasks.ps1"

Write-Host "[5/5] Secret and Cloudflare credential check" -ForegroundColor Yellow
if (-not (Test-Path "$ProjectDir\.env")) {
    Write-Host "Missing $ProjectDir\.env. Copy it manually through a secure channel." -ForegroundColor Yellow
}

$CloudflaredConfig = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
if (-not (Test-Path $CloudflaredConfig)) {
    Write-Host "Missing Cloudflared config. Do not download credentials over HTTP; copy them securely." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Install/update finished." -ForegroundColor Green
Write-Host "Run these checks after tasks start:" -ForegroundColor Cyan
Write-Host "  Invoke-WebRequest http://localhost:5001/healthz"
Write-Host "  Invoke-WebRequest http://localhost:5001/api/health"
