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

function Test-FlaskAlive {
    $tcp = Test-NetConnection -ComputerName 'localhost' -Port $Port `
                              -WarningAction SilentlyContinue `
                              -InformationLevel Quiet
    if (-not $tcp) {
        return @{ Alive = $false; Reason = "tcp_${Port}_unreachable" }
    }

    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 5 `
                                  -UseBasicParsing -ErrorAction Stop
        if ($resp.StatusCode -ne 200) {
            return @{ Alive = $false; Reason = "healthz_status_$($resp.StatusCode)" }
        }
    } catch {
        $msg = $_.Exception.Message
        if ($msg -match '404') {
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

$status = Test-FlaskAlive
if ($status.Alive) {
    exit 0
}

Write-Log ("FLASK DOWN: " + $status.Reason + " - restarting")
Restart-Flask

Start-Sleep -Seconds 3
$after = Test-FlaskAlive
if ($after.Alive) {
    Write-Log "Restart confirmed - Flask healthy."
    $message = @(
        "&#x1F501; <b>Flask watchdog</b>"
        ("사유: " + $status.Reason)
        "조치: Flask 재기동 완료"
    ) -join "`n"
    Send-Telegram $message
} else {
    Write-Log ("Restart FAILED - still: " + $after.Reason)
    $message = @(
        "&#x1F6A8; <b>Flask watchdog FAILED</b>"
        ("사유: " + $status.Reason)
        ("재기동 후에도: " + $after.Reason)
        "수동 확인 필요"
    ) -join "`n"
    Send-Telegram $message
}
