$ErrorActionPreference = "Stop"

$Root = "C:\bitman_marketfloww"
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$BackupScript = Join-Path $Root "scripts\backup_marketflow_data.py"
$LogDir = Join-Path $Root "logs"
$LogPath = Join-Path $LogDir "durable_backup.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$started = Get-Date -Format "o"
Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$started backup task started"

try {
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $Python $BackupScript `
        --root $Root `
        --prefix durable `
        --retention-days 30 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorPreference
    foreach ($line in $output) {
        Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ([string]$line)
    }
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$(Get-Date -Format o) backup task exit=$exitCode"
    exit $exitCode
} catch {
    Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value "$(Get-Date -Format o) backup task exception=$($_.Exception.GetType().Name)"
    exit 1
}
