$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$OutLog = Join-Path $LogDir "flask_task.out.log"
$ErrLog = Join-Path $LogDir "flask_task.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"
$env:HOME_SERVER = "1"
$env:FLASK_PORT = "5001"
$env:WERKZEUG_RUN_MAIN = $null

$existing = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like "*flask_app.py*"
}

foreach ($proc in $existing) {
    try {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) stopped stale flask_app.py pid=$($proc.ProcessId)"
    } catch {
        Add-Content -Path $ErrLog -Encoding UTF8 -Value "$(Get-Date -Format o) failed to stop pid=$($proc.ProcessId): $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 2

$portOwner = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($ownerPid in $portOwner) {
    try {
        Stop-Process -Id $ownerPid -Force -ErrorAction Stop
        Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) stopped stale port 5001 pid=$ownerPid"
    } catch {
        Add-Content -Path $ErrLog -Encoding UTF8 -Value "$(Get-Date -Format o) failed to stop port pid=${ownerPid}: $($_.Exception.Message)"
    }
}

Start-Sleep -Seconds 1

Start-Process `
    -FilePath $Python `
    -ArgumentList "flask_app.py" `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog

Add-Content -Path $OutLog -Encoding UTF8 -Value "$(Get-Date -Format o) started flask_app.py via start_flask_task.ps1"
