#Requires -RunAsAdministrator
<#
.SYNOPSIS
    MarketFlow 자동 시작 등록 (Task Scheduler 기반)
    Flask API (5001) + Scheduler Daemon + Cloudflared Tunnel

.DESCRIPTION
    - 부팅 시 사용자 계정으로 자동 시작 (venv 호환)
    - crash 시 자동 재시작 (restart-on-failure 정책)
    - 기존 7겹 batch/watchdog 인프라를 3개 Task로 대체

.USAGE
    관리자 PowerShell에서 실행:
    > Set-ExecutionPolicy Bypass -Scope Process -Force
    > .\scripts\install_services.ps1
#>

$PROJECT = "C:\bitman_marketfloww"
$PYTHON = "$PROJECT\.venv\Scripts\python.exe"
$LOG_DIR = "$PROJECT\logs"
$USERNAME = $env:USERNAME

if (-not (Test-Path $PYTHON)) { Write-Error "Python not found: $PYTHON"; exit 1 }
if (-not (Test-Path $LOG_DIR)) { New-Item -Path $LOG_DIR -ItemType Directory -Force | Out-Null }

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  MarketFlow Auto-Start Installer" -ForegroundColor Cyan
Write-Host "  (Task Scheduler + restart-on-failure)" -ForegroundColor Cyan
Write-Host "========================================`n" -ForegroundColor Cyan

# ──────────────────────────────────────
# Helper: VBS wrapper를 생성 (콘솔 창 없이 실행하기 위해)
# ──────────────────────────────────────
$wrapperDir = "$PROJECT\scripts\wrappers"
if (-not (Test-Path $wrapperDir)) { New-Item -Path $wrapperDir -ItemType Directory -Force | Out-Null }

# Flask wrapper
@"
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "$PROJECT"
objShell.Run """$PYTHON"" flask_app.py", 0, True
"@ | Out-File -FilePath "$wrapperDir\flask.vbs" -Encoding ASCII -Force

# Scheduler wrapper
@"
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "$PROJECT"
objShell.Run """$PYTHON"" scheduler.py --daemon", 0, True
"@ | Out-File -FilePath "$wrapperDir\scheduler.vbs" -Encoding ASCII -Force

# Cloudflared wrapper
$cfExe = "$PROJECT\cloudflared.exe"
$cfConfig = "C:\Users\$USERNAME\.cloudflared\config.yml"
@"
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "$PROJECT"
objShell.Run """$cfExe"" tunnel --config ""$cfConfig"" run bitman-api", 0, True
"@ | Out-File -FilePath "$wrapperDir\cloudflared.vbs" -Encoding ASCII -Force

Write-Host "  VBS wrappers created (silent execution)" -ForegroundColor Gray

# ──────────────────────────────────────
# 환경변수 설정 (사용자 레벨)
# ──────────────────────────────────────
[Environment]::SetEnvironmentVariable("PYTHONIOENCODING", "utf-8", "User")
Write-Host "  PYTHONIOENCODING=utf-8 set (User level)" -ForegroundColor Gray

# ──────────────────────────────────────
# 1. Flask Task
# ──────────────────────────────────────
$taskName = "MarketFlow-Flask"
Write-Host "`n[1/3] $taskName ..." -ForegroundColor Yellow

# 기존 삭제
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $USERNAME
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$wrapperDir\flask.vbs""" `
    -WorkingDirectory $PROJECT
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 15) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId $USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName `
    -Trigger $trigger -Action $action -Settings $settings -Principal $principal `
    -Description "Flask API server on port 5001 (auto-restart on failure)" | Out-Null

Write-Host "  $taskName registered (AtLogOn + RestartOnFailure)" -ForegroundColor Green

# ──────────────────────────────────────
# 2. Scheduler Task
# ──────────────────────────────────────
$taskName = "MarketFlow-Scheduler"
Write-Host "[2/3] $taskName ..." -ForegroundColor Yellow

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $USERNAME
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$wrapperDir\scheduler.vbs""" `
    -WorkingDirectory $PROJECT
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 30) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId $USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName `
    -Trigger $trigger -Action $action -Settings $settings -Principal $principal `
    -Description "Scheduled data updates for US/KR/Crypto markets (auto-restart on failure)" | Out-Null

Write-Host "  $taskName registered (AtLogOn + RestartOnFailure)" -ForegroundColor Green

# ──────────────────────────────────────
# 3. Cloudflared Task
# ──────────────────────────────────────
$taskName = "MarketFlow-Cloudflared"
Write-Host "[3/3] $taskName ..." -ForegroundColor Yellow

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $USERNAME
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument """$wrapperDir\cloudflared.vbs""" `
    -WorkingDirectory $PROJECT
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Seconds 15) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)
$principal = New-ScheduledTaskPrincipal -UserId $USERNAME -LogonType Interactive -RunLevel Highest

Register-ScheduledTask -TaskName $taskName `
    -Trigger $trigger -Action $action -Settings $settings -Principal $principal `
    -Description "Cloudflare Tunnel for marketflow-api.bit-man.net (auto-restart on failure)" | Out-Null

Write-Host "  $taskName registered (AtLogOn + RestartOnFailure)" -ForegroundColor Green

# ──────────────────────────────────────
# 기존 NSSM 서비스 정리 (있으면)
# ──────────────────────────────────────
$nssm = "$PROJECT\nssm.exe"
if (Test-Path $nssm) {
    foreach ($svc in @("MarketFlow-Flask", "MarketFlow-Scheduler")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s) {
            Write-Host "`n  Removing old NSSM service: $svc" -ForegroundColor Gray
            & $nssm stop $svc confirm 2>$null
            & $nssm remove $svc confirm 2>$null
        }
    }
}

# ──────────────────────────────────────
# 기존 cloudflared Windows 서비스 제거 (SYSTEM 계정 문제)
# ──────────────────────────────────────
$cfSvc = Get-Service -Name "Cloudflared" -ErrorAction SilentlyContinue
if ($cfSvc) {
    Write-Host "  Stopping old Cloudflared Windows Service..." -ForegroundColor Gray
    Stop-Service Cloudflared -Force -ErrorAction SilentlyContinue
    & sc.exe delete Cloudflared 2>$null
    Write-Host "  Old Cloudflared service removed (replaced by Task)" -ForegroundColor Green
}

# ──────────────────────────────────────
# 확인
# ──────────────────────────────────────
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Registered Tasks" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Get-ScheduledTask -TaskName "MarketFlow-*" | Format-Table TaskName, State -AutoSize

Write-Host @"

Done! Tasks will auto-start on next login.
To start NOW: run each task manually in Task Scheduler,
or reboot to verify full auto-start.

To check status: .\scripts\service_status.ps1
"@ -ForegroundColor Cyan
