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
    # 2026-05-15 miniPC 홈서버 운영 시점 — watchdog 역할 최소화.
    # 본PC 잦은 재부팅 시대의 공격적 감시 정책 폐기. 진짜 OOM 또는
    # 완전 hang 만 잡고, 평소는 손대지 않는다.
    #
    # - RSS 임계 12 GB (정말 OOM 직전만 — miniPC 16 GB 기준)
    # - healthz timeout 30s (cold cache build + GC pause 충분 허용)
    # - 30초 timeout 2회 연속 실패 + 30초 간격 = 진짜 hang 일 때만 죽임
    # - TCP listen 도 같은 패턴
    $rssMB = Get-FlaskRSSMB
    if ($rssMB -gt 12000) {
        return @{ Alive = $false; Reason = ("rss_overflow_" + [int]$rssMB + "MB"); RSS = $rssMB }
    }

    # TCP listen 체크 (1차)
    $tcp = Test-NetConnection -ComputerName 'localhost' -Port $Port `
                              -WarningAction SilentlyContinue `
                              -InformationLevel Quiet
    if (-not $tcp) {
        Start-Sleep -Seconds 30  # 진짜 hang 확정 위해 30초 대기
        $tcp = Test-NetConnection -ComputerName 'localhost' -Port $Port `
                                  -WarningAction SilentlyContinue `
                                  -InformationLevel Quiet
        if (-not $tcp) {
            return @{ Alive = $false; Reason = "tcp_${Port}_unreachable"; RSS = $rssMB }
        }
    }

    # healthz 응답 체크 (30s timeout, 2번 연속 실패 시만 죽임)
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        try {
            $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 30 `
                                      -UseBasicParsing -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                return @{ Alive = $true; Reason = 'ok'; RSS = $rssMB }
            }
            if ($attempt -eq 2) {
                return @{ Alive = $false; Reason = "healthz_status_$($resp.StatusCode)"; RSS = $rssMB }
            }
        } catch {
            $msg = $_.Exception.Message
            if ($msg -match '404') {
                return @{ Alive = $true; Reason = 'tcp_ok_healthz_404_transitional'; RSS = $rssMB }
            }
            if ($attempt -eq 2) {
                return @{ Alive = $false; Reason = "healthz_$($msg -replace '[^a-zA-Z0-9_]','_' | Select-Object -First 50)"; RSS = $rssMB }
            }
        }
        Start-Sleep -Seconds 30  # 진짜 hang 인지 30초 후 재확인
    }

    return @{ Alive = $false; Reason = 'unknown'; RSS = $rssMB }
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
        # Phase A-G 추가 + tracemalloc + entities.db (2760 row) 로드로
        # cold start 30-60s 가능. 60s 까지 polling 으로 기다려 가짜 FAILED 방지.
        Write-Log "Start-ScheduledTask issued; polling up to 60s for boot..."
        $deadline = (Get-Date).AddSeconds(60)
        $booted = $false
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            try {
                $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 3 `
                                          -UseBasicParsing -ErrorAction Stop
                if ($resp.StatusCode -eq 200) {
                    $booted = $true
                    Write-Log "Flask responded healthy during boot wait"
                    break
                }
            } catch {
                # 아직 안 올라옴 — 계속 대기
            }
        }
        if (-not $booted) {
            Write-Log "60s boot wait elapsed without healthz; falling through to recheck"
        }
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
    # FAILURE 텔레그램 알림 비활성화 (사용자 요청 2026-07-09 — 반복 알림 중단).
    # watchdog 의 재기동 시도 자체는 그대로 유지, 로그만 남김.
    # $message = @(
    #     "[ALERT] Flask watchdog FAILED"
    #     ("reason: " + $status.Reason)
    #     ("after_restart: " + $after.Reason)
    #     "manual check required"
    # ) -join "`n"
    # Send-Telegram $message
}
