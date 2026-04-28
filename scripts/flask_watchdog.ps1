# MarketFlow Flask Watchdog
# ------------------------------------------------------------------
# Purpose : Restart Flask (MarketFlow-Flask scheduled task) when port
#           5001 is unreachable or /healthz endpoint times out.
#
# Schedule: Run every 5 minutes via Task Scheduler
#           (MarketFlow-Flask-Watchdog).
#
# Why this exists:
#   2026-04-24 20:07: Flask silent death, undetected for 24h+.
#   The Scheduler watchdog only monitors scheduler.py — Flask had
#   no liveness check. This closes that gap.
#
# Liveness criteria:
#   1) TCP connect to localhost:5001 succeeds (< 3s)
#   2) /healthz returns HTTP 200 within 5s
#   Either failure → restart MarketFlow-Flask scheduled task.
# ------------------------------------------------------------------

$ErrorActionPreference = 'Continue'

$Project   = 'C:\bitman_marketfloww'
$LogFile   = Join-Path $Project 'logs\flask_watchdog.log'
$TaskName  = 'MarketFlow-Flask'
$Port      = 5001
$HealthUrl = "http://localhost:$Port/healthz"

function Write-Log($msg) {
    $line = "{0} | {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Send-Telegram($msg) {
    try {
        $envFile = Join-Path $Project '.env'
        if (-not (Test-Path $envFile)) { return }
        $token = $null; $chat = $null
        Get-Content $envFile | ForEach-Object {
            if ($_ -match '^TELEGRAM_BOT_TOKEN=(.+)$') { $token = $Matches[1].Trim() }
            if ($_ -match '^TELEGRAM_CHAT_ID=(.+)$')   { $chat  = $Matches[1].Trim() }
        }
        if (-not $token -or -not $chat) { return }
        $body = @{
            chat_id    = $chat
            text       = $msg
            parse_mode = 'HTML'
        }
        Invoke-RestMethod -Uri "https://api.telegram.org/bot$token/sendMessage" `
                          -Method Post -Body $body -TimeoutSec 10 | Out-Null
    } catch {
        Write-Log ("Telegram send failed: " + $_.Exception.Message)
    }
}

function Test-FlaskAlive {
    # 1) TCP probe (faster fail than HTTP)
    $tcp = Test-NetConnection -ComputerName 'localhost' -Port $Port `
                              -WarningAction SilentlyContinue `
                              -InformationLevel Quiet
    if (-not $tcp) {
        return @{ Alive = $false; Reason = "tcp_${Port}_unreachable" }
    }

    # 2) /healthz HTTP probe (catches hung-but-listening)
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 `
                                  -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -ne 200) {
            return @{ Alive = $false; Reason = "healthz_status_$($resp.StatusCode)" }
        }
    } catch {
        # If /healthz not deployed yet, fall back to any TCP listener counts as alive
        $msg = $_.Exception.Message
        if ($msg -match '404') {
            # Endpoint not deployed — treat TCP success as alive (transitional)
            return @{ Alive = $true; Reason = 'tcp_ok_healthz_404_transitional' }
        }
        return @{ Alive = $false; Reason = "healthz_$($msg -replace '[^a-zA-Z0-9_]','_' | Select-Object -First 50)" }
    }

    return @{ Alive = $true; Reason = 'ok' }
}

function Restart-Flask {
    Write-Log "Restarting MarketFlow-Flask task..."
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 3
        # Kill any orphan Flask processes for this project
        $flaskAppPath = Join-Path $Project 'flask_app.py'
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
            | Where-Object {
                $_.CommandLine -like ('*' + $flaskAppPath + '*')
            } `
            | ForEach-Object {
                Write-Log ("Killing orphan Flask PID " + $_.ProcessId)
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $TaskName
        Write-Log "Start-ScheduledTask issued; waiting 8s for boot..."
        Start-Sleep -Seconds 8
    } catch {
        Write-Log ("Restart command failed: " + $_.Exception.Message)
    }
}

# ── Main ──
$status = Test-FlaskAlive
if ($status.Alive) {
    # Healthy — silent (don't spam logs every 5 min)
    exit 0
}

Write-Log ("FLASK DOWN: " + $status.Reason + " — restarting")
Restart-Flask

# Verify
Start-Sleep -Seconds 3
$after = Test-FlaskAlive
if ($after.Alive) {
    Write-Log "Restart confirmed — Flask healthy."
    Send-Telegram ("&#x1F501; <b>Flask watchdog</b>`n사유: " + $status.Reason + "`n조치: Flask 재기동 완료")
} else {
    Write-Log ("Restart FAILED — still: " + $after.Reason)
    Send-Telegram ("&#x1F6A8; <b>Flask watchdog FAILED</b>`n사유: " + $status.Reason + "`n재기동 후에도: " + $after.Reason + "`n수동 확인 필요")
}
