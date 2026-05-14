# MarketFlow Flask Watchdog
# Restarts the MarketFlow-Flask task when port 5001 or /healthz is unavailable.

$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Project   = 'C:\bitman_marketfloww'
$LogFile   = Join-Path $Project 'logs\flask_watchdog.log'
$TaskName  = 'MarketFlow-Flask'
$Port      = 5001
$HealthUrl = "http://localhost:$Port/healthz"

function Write-Log($msg) {
    $line = "{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Read-EnvValue($name) {
    $envFile = Join-Path $Project '.env'
    if (-not (Test-Path $envFile)) { return $null }
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        if ($line -match ("^" + [regex]::Escape($name) + "=(.+)$")) {
            $value = $Matches[1].Trim()
            $value = $value.Trim('"')
            $value = $value.Trim("'")
            return $value
        }
    }
    return $null
}

function Send-Telegram($msg) {
    try {
        $token = Read-EnvValue 'TELEGRAM_BOT_TOKEN'
        $chat = Read-EnvValue 'TELEGRAM_CHAT_ID'
        if (-not $token -or -not $chat) { return }

        $payload = @{
            chat_id    = $chat
            text       = $msg
            parse_mode = 'HTML'
        } | ConvertTo-Json -Depth 4 -Compress
        $body = [System.Text.Encoding]::UTF8.GetBytes($payload)

        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                          -Method Post `
                          -ContentType 'application/json; charset=utf-8' `
                          -Body $body `
                          -TimeoutSec 10 | Out-Null
    } catch {
        Write-Log ("Telegram send failed: " + $_.Exception.Message)
    }
}

function Get-FlaskRSSMB {
    # Flask process RSS 측정 (MB). 미발견 시 0.
    try {
        $flaskAppPath = Join-Path $Project 'flask_app.py'
        $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
            | Where-Object { $_.CommandLine -like ('*' + $flaskAppPath + '*') } `
            | Select-Object -First 1
        if (-not $proc) { return 0 }
        $p = Get-Process -Id $proc.ProcessId -ErrorAction SilentlyContinue
        if (-not $p) { return 0 }
        return [math]::Round($p.WorkingSet64 / 1MB, 1)
    } catch {
        return 0
    }
}

function Test-FlaskAlive {
    # 1) RSS 임계 (3 GB 초과 → 강제 종료 트리거). healthz 살아있어도 누수로 hang
    #    하는 패턴 (사용자 보고: 8 GB / 1h 17m, 모든 endpoint 30s+ timeout).
    $rssMB = Get-FlaskRSSMB
    if ($rssMB -gt 3000) {
        return @{ Alive = $false; Reason = ("rss_overflow_" + [int]$rssMB + "MB"); RSS = $rssMB }
    }

    # 2) TCP listen 체크
    $tcp = Test-NetConnection -ComputerName 'localhost' -Port $Port `
                              -WarningAction SilentlyContinue `
                              -InformationLevel Quiet
    if (-not $tcp) {
        return @{ Alive = $false; Reason = "tcp_${Port}_unreachable"; RSS = $rssMB }
    }

    # 3) healthz 응답 체크
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 `
                                  -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -ne 200) {
            return @{ Alive = $false; Reason = "healthz_status_$($resp.StatusCode)"; RSS = $rssMB }
        }
    } catch {
        $msg = $_.Exception.Message
        if ($msg -match '404') {
            return @{ Alive = $true; Reason = 'tcp_ok_healthz_404_transitional'; RSS = $rssMB }
        }
        return @{ Alive = $false; Reason = "healthz_$($msg -replace '[^a-zA-Z0-9_]','_' | Select-Object -First 50)"; RSS = $rssMB }
    }

    return @{ Alive = $true; Reason = 'ok'; RSS = $rssMB }
}

function Restart-Flask {
    Write-Log "Restarting MarketFlow-Flask task..."
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        # taskkill /F /T 로 부모+자식 모두 강제 종료 (orphan 방지)
        $flaskAppPath = Join-Path $Project 'flask_app.py'
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
            | Where-Object {
                $_.CommandLine -like ('*' + $flaskAppPath + '*')
            } `
            | ForEach-Object {
                Write-Log ("taskkill /F /T PID " + $_.ProcessId)
                & taskkill.exe /F /T /PID $_.ProcessId 2>&1 | Out-Null
            }
        Start-Sleep -Seconds 3
        Start-ScheduledTask -TaskName $TaskName
        # Phase A-G 추가로 startup 15-25s 필요 (graphrag entities.db 로드 등).
        # 8s -> 30s 로 늘려 가짜 FAILED 알람 차단.
        Write-Log "Start-ScheduledTask issued; waiting 30s for boot..."
        Start-Sleep -Seconds 30
    } catch {
        Write-Log ("Restart command failed: " + $_.Exception.Message)
    }
}

$status = Test-FlaskAlive
if ($status.Alive) {
    exit 0
}

Write-Log ("FLASK DOWN: " + $status.Reason + " - restarting")
Restart-Flask

Start-Sleep -Seconds 3
$after = Test-FlaskAlive
if ($after.Alive) {
    # SUCCESS notification 비활성화 (사용자 요청 — 깨진 한글 알림 중단)
    # watchdog 의 재기동 동작 자체는 그대로 유지, 로그만 남김.
    Write-Log "Restart confirmed - Flask healthy. (telegram suppressed)"
} else {
    Write-Log ("Restart FAILED - still: " + $after.Reason)
    # FAILURE 만 영문으로 (인코딩 깨짐 방지) 전송 — 진짜 장애는 알아야 함.
    $message = @(
        "[ALERT] Flask watchdog FAILED"
        ("reason: " + $status.Reason)
        ("after_restart: " + $after.Reason)
        "manual check required"
    ) -join "`n"
    Send-Telegram $message
}
