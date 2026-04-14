# enable-remote.ps1 - MarketFlow mini PC remote admin enabler
# Requires Administrator. Enables WinRM + SSH for access from main PC.
#
# Usage:
#   cd C:\bitman_marketfloww
#   Set-ExecutionPolicy Bypass -Scope Process -Force
#   .\deploy\enable-remote.ps1

$ErrorActionPreference = 'Continue'

# ===== Self-elevation: UAC auto-request =====
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[INFO] Not Administrator. Requesting UAC elevation..." -ForegroundColor Yellow
    Write-Host "       A UAC prompt will appear. Click 'Yes' to continue." -ForegroundColor Yellow
    Start-Sleep -Seconds 1
    try {
        Start-Process powershell.exe -Verb RunAs -ArgumentList @(
            '-NoProfile',
            '-ExecutionPolicy', 'Bypass',
            '-NoExit',
            '-File', "`"$PSCommandPath`""
        ) -ErrorAction Stop
        Write-Host "[OK] New elevated window opened. Check the new window for progress." -ForegroundColor Green
    } catch {
        Write-Host "[FATAL] UAC elevation failed: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "        Current account may not be in Administrators group." -ForegroundColor Red
        Write-Host "        Check: whoami /groups | findstr Administrators" -ForegroundColor Yellow
    }
    exit 0
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " MarketFlow mini PC remote enabler" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[OK] Administrator confirmed" -ForegroundColor Green
Write-Host ""

# 2. Enable WinRM / PSRemoting
Write-Host "[2/5] Enabling WinRM / PSRemoting..." -ForegroundColor Cyan
try {
    Enable-PSRemoting -Force -SkipNetworkProfileCheck -ErrorAction Stop | Out-Null
    Write-Host "  [OK] PSRemoting enabled" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] PSRemoting: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 3. TrustedHosts for main PC subnet
try {
    Set-Item WSMan:\localhost\Client\TrustedHosts -Value "192.168.45.*,192.168.55.*" -Force
    $th = (Get-Item WSMan:\localhost\Client\TrustedHosts).Value
    Write-Host "  [OK] TrustedHosts = $th" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] TrustedHosts: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 4. OpenSSH Server
Write-Host ""
Write-Host "[3/5] Installing / starting OpenSSH Server..." -ForegroundColor Cyan
try {
    $cap = Get-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 -ErrorAction Stop
    if ($cap.State -ne 'Installed') {
        Write-Host "  Installing (may take minutes)..." -ForegroundColor Gray
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
        Write-Host "  [OK] OpenSSH Server installed" -ForegroundColor Green
    } else {
        Write-Host "  [OK] OpenSSH Server already installed" -ForegroundColor Green
    }
    Start-Service sshd -ErrorAction SilentlyContinue
    Set-Service sshd -StartupType Automatic
    $sshd = Get-Service sshd
    Write-Host "  sshd status: $($sshd.Status) / StartType: $($sshd.StartType)" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] SSH: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 5. Firewall rules (Private profile only)
Write-Host ""
Write-Host "[4/5] Firewall rules..." -ForegroundColor Cyan
$rules = @(
    @{ Name = 'MarketFlow-Flask-5001';  Port = 5001; Label = 'Flask API' },
    @{ Name = 'MarketFlow-Vite-4000';   Port = 4000; Label = 'Vite Dev' },
    @{ Name = 'MarketFlow-WinRM-5985';  Port = 5985; Label = 'WinRM HTTP' },
    @{ Name = 'MarketFlow-SSH-22';      Port = 22;   Label = 'SSH' }
)
foreach ($r in $rules) {
    $existing = Get-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
    if ($existing) { Remove-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue }
    try {
        New-NetFirewallRule -Name $r.Name -DisplayName "MarketFlow: $($r.Label)" `
            -Direction Inbound -Action Allow -Protocol TCP -LocalPort $r.Port `
            -Profile Private -ErrorAction Stop | Out-Null
        $msg = "  [OK] " + $r.Label + " (port " + $r.Port + ", Private)"
        Write-Host $msg -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] $($r.Label): $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 6. Final summary
Write-Host ""
Write-Host "[5/5] Final status" -ForegroundColor Cyan
Write-Host "----------------------------------------" -ForegroundColor Gray
$winrm = Get-Service WinRM -ErrorAction SilentlyContinue
$sshd  = Get-Service sshd  -ErrorAction SilentlyContinue
if ($winrm) { Write-Host ("  WinRM: {0} ({1})" -f $winrm.Status, $winrm.StartType) -ForegroundColor White }
if ($sshd)  { Write-Host ("  sshd : {0} ({1})" -f $sshd.Status,  $sshd.StartType)  -ForegroundColor White }
$th = (Get-Item WSMan:\localhost\Client\TrustedHosts -ErrorAction SilentlyContinue).Value
Write-Host ("  TrustedHosts: {0}" -f $th) -ForegroundColor White
Write-Host ""
Write-Host "  LISTENING ports:" -ForegroundColor White
$ports = netstat -an | Select-String -Pattern ':(22|5985|5986|5001|4000)\s' | Select-Object -First 10
$ports | ForEach-Object { Write-Host "    $_" -ForegroundColor Gray }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Done. Test from main PC:" -ForegroundColor Cyan
Write-Host "   ssh $env:USERNAME@192.168.55.103" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
