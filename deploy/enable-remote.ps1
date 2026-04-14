# enable-remote.ps1 — 미니PC 원격 관리 활성화
# 관리자 권한 필수. 본PC(192.168.45.*)가 WinRM/SSH로 미니PC 관리할 수 있게 설정.
#
# 실행:
#   cd C:\bitman_marketfloww
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\deploy\enable-remote.ps1

$ErrorActionPreference = 'Continue'

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " MarketFlow 미니PC 원격 접속 활성화" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# 1. 관리자 권한 확인
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[FATAL] 관리자 권한이 아닙니다." -ForegroundColor Red
    Write-Host "  Win+X → 'Windows Terminal (관리자)' 선택 후 다시 실행하세요.`n" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] 관리자 권한 확인`n" -ForegroundColor Green

# 2. WinRM (PSRemoting) 활성화
Write-Host "[2/5] WinRM / PowerShell Remoting 활성화..." -ForegroundColor Cyan
try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction Stop | Out-Null
    Write-Host "  [OK] PSRemoting 활성화" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] PSRemoting: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 3. TrustedHosts에 본PC 대역 추가 (양방향 양쪽에서 설정하는 것이 안전)
try {
    Set-Item WSMan:\localhost\Client\TrustedHosts -Value "192.168.45.*,192.168.55.*" -Force
    $th = (Get-Item WSMan:\localhost\Client\TrustedHosts).Value
    Write-Host "  [OK] TrustedHosts = $th" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] TrustedHosts: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 4. OpenSSH Server 설치 + 시작 + 자동시작
Write-Host "`n[3/5] OpenSSH Server 설치 및 시작..." -ForegroundColor Cyan
try {
    $cap = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop
    if ($cap.State -ne 'Installed') {
        Write-Host "  설치 중... (수 분 소요 가능)" -ForegroundColor Gray
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
        Write-Host "  [OK] OpenSSH Server 설치 완료" -ForegroundColor Green
    } else {
        Write-Host "  [OK] OpenSSH Server 이미 설치됨" -ForegroundColor Green
    }
    Start-Service sshd -ErrorAction SilentlyContinue
    Set-Service sshd -StartupType Automatic
    $sshd = Get-Service sshd
    Write-Host "  sshd 상태: $($sshd.Status) / StartType: $($sshd.StartType)" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] SSH: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 5. 방화벽 규칙 (Private 프로필만 허용 — 보안)
Write-Host "`n[4/5] 방화벽 규칙..." -ForegroundColor Cyan
$rules = @(
    @{Name='MarketFlow-Flask-5001';  Port=5001; Label='Flask API'},
    @{Name='MarketFlow-Vite-4000';   Port=4000; Label='Vite Dev'},
    @{Name='MarketFlow-WinRM-5985';  Port=5985; Label='WinRM HTTP'},
    @{Name='MarketFlow-SSH-22';      Port=22;   Label='SSH'}
)
foreach ($r in $rules) {
    $existing = Get-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
    if ($existing) { Remove-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue }
    try {
        New-NetFirewallRule -Name $r.Name -DisplayName "MarketFlow: $($r.Label)" `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPort $r.Port `
            -Profile Private -ErrorAction Stop | Out-Null
        Write-Host "  [OK] $($r.Label) ($($r.Port)/tcp, Private 프로필)" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] $($r.Label): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 6. 최종 상태 요약
Write-Host "`n[5/5] 최종 상태 요약" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
$winrm = Get-Service WinRM -ErrorAction SilentlyContinue
$sshd  = Get-Service sshd  -ErrorAction SilentlyContinue
Write-Host ("  WinRM: {0} ({1})" -f $winrm.Status, $winrm.StartType) -ForegroundColor White
Write-Host ("  sshd : {0} ({1})" -f $sshd.Status,  $sshd.StartType)  -ForegroundColor White
$th = (Get-Item WSMan:\localhost\Client\TrustedHosts -ErrorAction SilentlyContinue).Value
Write-Host ("  TrustedHosts: {0}" -f $th) -ForegroundColor White
$listening = netstat -an | Select-String -Pattern ':(22|5985|5986|5001|4000)\s' | Select-Object -First 10
Write-Host "`n  LISTENING 포트:" -ForegroundColor White
$listening | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host " 완료. 본PC에서 테스트:" -ForegroundColor Cyan
Write-Host "   ssh $env:USERNAME@192.168.55.103" -ForegroundColor Yellow
Write-Host "   (또는 WinRM)" -ForegroundColor Gray
Write-Host "========================================`n" -ForegroundColor Cyan
