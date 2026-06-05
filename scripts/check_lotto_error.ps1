# Search for lotto errors and surrounding context
$ErrorActionPreference = "SilentlyContinue"
$log = "C:\bitman_marketfloww\logs\scheduler.log"
if (Test-Path $log) {
    # Find all lotto-related lines with context
    $lines = Get-Content $log
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "lotto") {
            Write-Host "----- L$($i+1) -----"
            $start = [Math]::Max(0, $i - 5)
            $end = [Math]::Min($lines.Count - 1, $i + 8)
            for ($j = $start; $j -le $end; $j++) {
                Write-Host $lines[$j]
            }
        }
    }
}
