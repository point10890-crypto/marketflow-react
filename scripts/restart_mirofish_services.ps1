# restart_mirofish_services.ps1
# miniPC 의 Flask + mirofish-mcp 두 서비스 재시작
# git reset --hard 가 이미 완료된 상태에서 실행

$Root = "C:\bitman_marketfloww"
$Py = "$Root\.venv\Scripts\python.exe"

Write-Host "=== Flask :5001 재시작 ==="
$flaskPids = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($p in $flaskPids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "  killed Flask PID $p"
}

# pyc cache 정리
Get-ChildItem -Recurse "$Root\app\services\mirofish\__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "MarketFlow-Flask"
Start-Sleep -Seconds 10
$newFlask = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
Write-Host "  new Flask PID: $($newFlask -join ',')"

Write-Host ""
Write-Host "=== mirofish-mcp :8765 재시작 ==="
$mcpPids = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
foreach ($p in $mcpPids) {
    Stop-Process -Id $p -Force -ErrorAction SilentlyContinue
    Write-Host "  killed MCP PID $p"
}
Start-Sleep -Seconds 2

# Restart with same args
Start-Process -FilePath $Py `
    -ArgumentList 'mirofish_mcp_server.py', '--transport', 'streamable-http', '--host', '127.0.0.1', '--port', '8765', '--path', '/mcp' `
    -WorkingDirectory $Root `
    -WindowStyle Hidden

Start-Sleep -Seconds 6
$newMcp = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
Write-Host "  new MCP PID: $($newMcp -join ',')"

Write-Host ""
Write-Host "=== 응답 검증 ==="
try {
    $r1 = Invoke-WebRequest -Uri http://localhost:5001/api/admin/mirofish/status -UseBasicParsing -TimeoutSec 5
    Write-Host "  Flask 5001 HTTP $($r1.StatusCode)"
} catch {
    Write-Host "  Flask 5001 status: $($_.Exception.Response.StatusCode.value__)"
}

# MCP initialize call
try {
    $body = @{ jsonrpc='2.0'; method='initialize'; id=1; params=@{ protocolVersion='2024-11-05'; capabilities=@{}; clientInfo=@{ name='restart-verify'; version='0.1' } } } | ConvertTo-Json -Depth 5
    $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:8765/mcp" -Method POST -ContentType "application/json" -Headers @{ Accept = "application/json, text/event-stream" } -Body $body -UseBasicParsing -TimeoutSec 8
    if ($r2.Content -match 'protocolVersion') {
        Write-Host "  MCP 8765 initialize OK"
    } else {
        Write-Host "  MCP 8765 unexpected: $($r2.Content.Substring(0, [Math]::Min(200, $r2.Content.Length)))"
    }
} catch {
    Write-Host "  MCP 8765 error: $($_.Exception.Message)"
}
