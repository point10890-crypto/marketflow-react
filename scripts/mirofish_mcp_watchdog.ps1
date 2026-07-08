# MarketFlow MiroFish MCP Watchdog
# Restarts the MarketFlow-MiroFish-MCP task when the local MCP HTTP endpoint is unavailable.

$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$Project   = 'C:\bitman_marketfloww'
$LogFile   = Join-Path $Project 'logs\mirofish_mcp_watchdog.log'
$TaskName  = 'MarketFlow-MiroFish-MCP'
$Port      = 8765
$McpUrl    = "http://127.0.0.1:$Port/mcp"

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

function Test-McpAlive {
    $tcp = Test-NetConnection -ComputerName '127.0.0.1' -Port $Port `
                              -WarningAction SilentlyContinue `
                              -InformationLevel Quiet
    if (-not $tcp) {
        return @{ Alive = $false; Reason = "tcp_${Port}_unreachable" }
    }

    $payload = @{
        jsonrpc = '2.0'
        id = 1
        method = 'initialize'
        params = @{
            protocolVersion = '2024-11-05'
            capabilities = @{}
            clientInfo = @{
                name = 'marketflow-mcp-watchdog'
                version = '1.0'
            }
        }
    } | ConvertTo-Json -Depth 6 -Compress

    try {
        $resp = Invoke-WebRequest -Uri $McpUrl `
                                  -Method Post `
                                  -Headers @{ Accept = 'application/json, text/event-stream' } `
                                  -ContentType 'application/json; charset=utf-8' `
                                  -Body ([System.Text.Encoding]::UTF8.GetBytes($payload)) `
                                  -TimeoutSec 8 `
                                  -UseBasicParsing `
                                  -ErrorAction Stop
        if ($resp.StatusCode -ne 200) {
            return @{ Alive = $false; Reason = "mcp_status_$($resp.StatusCode)" }
        }
        if ([string]$resp.Content -notmatch 'MarketFlow MiroFish Autonomous MCP') {
            return @{ Alive = $false; Reason = 'mcp_unexpected_response' }
        }
    } catch {
        $msg = $_.Exception.Message -replace '[^a-zA-Z0-9_]', '_'
        if ($msg.Length -gt 80) { $msg = $msg.Substring(0, 80) }
        return @{ Alive = $false; Reason = "mcp_http_$msg" }
    }

    return @{ Alive = $true; Reason = 'ok' }
}

function Restart-Mcp {
    Write-Log "Restarting MarketFlow-MiroFish-MCP task..."
    try {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" `
            | Where-Object {
                $_.CommandLine -like '*mirofish_mcp_server.py*'
            } `
            | ForEach-Object {
                Write-Log ("Killing orphan MCP PID " + $_.ProcessId)
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $TaskName
        Write-Log "Start-ScheduledTask issued; waiting 8s for MCP boot..."
        Start-Sleep -Seconds 8
    } catch {
        Write-Log ("Restart command failed: " + $_.Exception.Message)
    }
}

$status = Test-McpAlive
if ($status.Alive) {
    exit 0
}

Write-Log ("MCP DOWN: " + $status.Reason + " - restarting")
Restart-Mcp

Start-Sleep -Seconds 3
$after = Test-McpAlive
if ($after.Alive) {
    # SUCCESS notification 비활성화 (사용자 요청 — 깨진 한글 알림 중단)
    # watchdog 의 재기동 동작 자체는 그대로 유지, 로그만 남김.
    Write-Log "Restart confirmed - MCP healthy. (telegram suppressed)"
} else {
    Write-Log ("Restart FAILED - still: " + $after.Reason)
    # FAILURE 텔레그램 알림도 비활성화 (사용자 요청 2026-07-09 — watchdog 알림 기능 전체 중단).
    # $message = @(
    #     "[ALERT] MiroFish MCP watchdog FAILED"
    #     ("reason: " + $status.Reason)
    #     ("after_restart: " + $after.Reason)
    #     "manual check required"
    # ) -join "`n"
    # Send-Telegram $message
}
