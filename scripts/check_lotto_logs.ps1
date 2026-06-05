# Search scheduler logs for lotto-related entries
$ErrorActionPreference = "SilentlyContinue"
$logs = @(
    "C:\bitman_marketfloww\logs\scheduler.log",
    "C:\bitman_marketfloww\logs\scheduler.log.1",
    "C:\bitman_marketfloww\logs\scheduler.log.2"
)
foreach ($log in $logs) {
    if (Test-Path $log) {
        Write-Host "===== $log ====="
        $matches = Get-Content $log | Select-String -Pattern "lotto|run_lotto|21:30|lotto_analysis"
        if ($matches) {
            $matches | Select-Object -Last 15
        } else {
            Write-Host "  (no matches)"
        }
    }
}
