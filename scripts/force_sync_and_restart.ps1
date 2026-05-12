# Force git sync to origin/main + restart Flask + mirofish-mcp 8765
$Root = "C:\bitman_marketfloww"
$Py = "$Root\.venv\Scripts\python.exe"

Set-Location $Root

Write-Host "=== git fetch + hard reset ==="
git fetch origin 2>&1
git reset --hard origin/main 2>&1
Write-Host ""
Write-Host "=== current HEAD ==="
git log --oneline -1

Write-Host ""
Write-Host "=== mcp_server.py 신규 도구 확인 ==="
$cnt = (Select-String -Path "$Root\app\services\mirofish\mcp_server.py" -Pattern "search_news_perplexity|scrape_naver_finance|get_backtest_summary|resolve_target|search_targets").Count
Write-Host "신규 도구 정의 라인 매칭: $cnt (5+ 기대)"

Write-Host ""
Write-Host "=== pyc 캐시 정리 ==="
Get-ChildItem -Recurse "$Root\app\services\mirofish\__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Flask :5001 재시작 ==="
Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    Write-Host "  killed Flask PID $_"
}
Start-Sleep 2
Start-ScheduledTask -TaskName "MarketFlow-Flask"
Start-Sleep 8
$fp = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
Write-Host "  new Flask PID: $($fp -join ',')"

Write-Host ""
Write-Host "=== mirofish-mcp :8765 재시작 ==="
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    Write-Host "  killed MCP PID $_"
}
Start-Sleep 2
Start-Process -FilePath $Py `
    -ArgumentList 'mirofish_mcp_server.py', '--transport', 'streamable-http', '--host', '127.0.0.1', '--port', '8765', '--path', '/mcp' `
    -WorkingDirectory $Root `
    -WindowStyle Hidden
Start-Sleep 6
$mp = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
Write-Host "  new MCP PID: $($mp -join ',')"

Write-Host ""
Write-Host "=== MCP tools/list 응답 ==="
try {
    $body = @{ jsonrpc='2.0'; method='tools/list'; params=@{}; id=1 } | ConvertTo-Json -Depth 5
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8765/mcp" -Method POST -ContentType "application/json" -Headers @{ Accept="application/json, text/event-stream" } -Body $body -UseBasicParsing -TimeoutSec 10
    $content = $r.Content
    if ($content -match "data: (.*)") {
        $content = $matches[1]
    }
    $j = $content | ConvertFrom-Json
    Write-Host "  tools count: $($j.result.tools.Count)"
    $names = $j.result.tools | Select-Object -ExpandProperty name
    $new = @('search_news_perplexity', 'scrape_naver_finance', 'get_backtest_summary', 'resolve_target', 'search_targets')
    foreach ($t in $new) {
        $mark = if ($names -contains $t) { 'OK' } else { 'XX' }
        Write-Host "    $mark $t"
    }
} catch {
    Write-Host "  ERROR: $($_.Exception.Message)"
}
