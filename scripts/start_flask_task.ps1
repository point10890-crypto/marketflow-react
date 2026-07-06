$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $Root "logs"
$ControlLog = Join-Path $LogDir "flask_task.control.log"
$OutLog = Join-Path $LogDir "flask_server.out.log"
$ErrLog = Join-Path $LogDir "flask_server.err.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUNBUFFERED = "1"
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

Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) starting flask_app.py detached via start_flask_task.ps1"

$flaskProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("flask_app.py") `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -PassThru

Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) started flask_app.py pid=$($flaskProcess.Id)"

$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Seconds 2

    $current = Get-Process -Id $flaskProcess.Id -ErrorAction SilentlyContinue
    if ($null -eq $current) {
        Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask_app.py exited before health check attempt=$attempt"
        exit 1
    }

    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:5001/healthz"
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz reachable status=$($response.StatusCode)"
            $healthy = $true
            break
        }
    } catch {
        if ($attempt -eq 30) {
            Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask healthz failed after attempts: $($_.Exception.Message)"
            exit 1
        }
    }
}

if ($healthy) {
    Wait-Process -Id $flaskProcess.Id
    Add-Content -Path $ControlLog -Encoding UTF8 -Value "$(Get-Date -Format o) flask_app.py exited pid=$($flaskProcess.Id)"
    exit 0
}
