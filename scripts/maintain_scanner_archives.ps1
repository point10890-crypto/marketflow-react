# Local launcher only. Task registration belongs to the operator.
# Keeps seven recent days intact; compresses older completed JSONs in place.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = 'C:\bitman_marketfloww'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$helperPath = Join-Path $projectRoot 'scripts\compact_scanner_archives.py'
$logPath = Join-Path $projectRoot 'logs\scanner_archive_maintenance.log'
$manifestDirectory = Join-Path $projectRoot 'data\operations\scanner_archive_compaction'
$before = (Get-Date).Date.AddDays(-7).ToString('yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)
$compactArgs = @(
    $helperPath,
    '--root', $projectRoot,
    '--before', $before,
    '--apply',
    '--target-free-gib', '20',
    '--max-runs', '10000'
)

function Get-ResultField {
    param([object]$Result, [string]$Name)
    if ($null -eq $Result) { return $null }
    $property = $Result.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function Write-MaintenanceRecord {
    param([hashtable]$Record)
    $Record['recorded_at'] = [DateTime]::UtcNow.ToString('o')
    $json = $Record | ConvertTo-Json -Compress -Depth 3
    Add-Content -LiteralPath $logPath -Value $json -Encoding UTF8 -ErrorAction Stop
}

$exitCode = 2
$summary = $null
$invalidLines = 0
$lastProgressBatch = -20
try {
    $logDirectory = Split-Path -Parent $logPath
    if (-not (Test-Path -LiteralPath $logDirectory -PathType Container)) {
        $null = New-Item -ItemType Directory -Path $logDirectory -Force
    }
    Write-MaintenanceRecord @{
        event = 'started'; before = $before; target_free_gib = 20; max_runs = 10000
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $helperPath -PathType Leaf)) {
        throw 'maintenance_dependency_missing'
    }

    # Only whitelist counts/status from helper JSON. Native stderr and arbitrary
    # text are discarded, never copied to logs or sent anywhere.
    & $pythonPath @compactArgs 2>&1 | ForEach-Object {
        $parsed = $null
        try {
            $parsed = $_.ToString() | ConvertFrom-Json -ErrorAction Stop
        } catch {
            $invalidLines += 1
        }
        if ($null -ne $parsed -and (Get-ResultField $parsed 'operation') -eq 'scanner_archive_lzx') {
            if ($null -ne (Get-ResultField $parsed 'status')) {
                $summary = $parsed
            } else {
                $batch = [long](Get-ResultField $parsed 'batches')
                if ($batch - $lastProgressBatch -ge 20) {
                    Write-MaintenanceRecord @{
                        event = 'progress'; batches = $batch
                        verified_files = [long](Get-ResultField $parsed 'verified_files')
                        eligible_files = [long](Get-ResultField $parsed 'eligible_files')
                        free_bytes = [long](Get-ResultField $parsed 'free_bytes_after')
                    }
                    $lastProgressBatch = $batch
                }
            }
        }
    }
    $nativeExit = $LASTEXITCODE
    $exitCode = $nativeExit
    if ($nativeExit -ne 0) {
        Write-MaintenanceRecord @{
            event = 'failed'; reason = 'helper_nonzero_exit'; native_exit = $nativeExit
            invalid_output_lines = $invalidLines
        }
    } elseif ($null -eq $summary -or
        (Get-ResultField $summary 'apply') -ne $true -or
        (Get-ResultField $summary 'before') -ne $before -or
        (Get-ResultField $summary 'status') -notin @('completed', 'target_reached') -or
        $null -ne (Get-ResultField $summary 'error') -or
        $null -ne (Get-ResultField $summary 'manifest_error')) {
        $exitCode = 2
        Write-MaintenanceRecord @{ event = 'failed'; reason = 'invalid_helper_summary' }
    } else {
        $manifest = [string](Get-ResultField $summary 'manifest')
        $manifestPath = [IO.Path]::GetFullPath($manifest)
        $allowedPrefix = [IO.Path]::GetFullPath($manifestDirectory).TrimEnd('\') + '\'
        if (-not $manifestPath.StartsWith($allowedPrefix, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($manifestPath) -notmatch '^compaction_\d{8}T\d{12}Z\.json$') {
            throw 'manifest_outside_expected_directory'
        }
        $manifestFile = Get-Item -LiteralPath $manifestPath
        if ($manifestFile.PSIsContainer -or $manifestFile.Length -gt 65536 -or
            ($manifestFile.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'manifest_not_a_bounded_regular_file'
        }
        $saved = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($field in @('operation', 'apply', 'before', 'status', 'verified_files', 'batches', 'target_free_bytes', 'free_bytes_after')) {
            if ((Get-ResultField $saved $field) -ne (Get-ResultField $summary $field)) {
                throw 'manifest_summary_mismatch'
            }
        }
        $freeBytes = [long](Get-ResultField $summary 'free_bytes_after')
        $targetBytes = [long](Get-ResultField $summary 'target_free_bytes')
        $event = 'completed'
        if ($freeBytes -lt $targetBytes) {
            $exitCode = 3
            $event = 'target_not_reached'
        }
        Write-MaintenanceRecord @{
            event = $event; native_exit = $nativeExit; exit_code = $exitCode
            before = $before; verified_files = [long](Get-ResultField $summary 'verified_files')
            batches = [long](Get-ResultField $summary 'batches')
            free_bytes = $freeBytes; target_free_bytes = $targetBytes
            reclaimed_bytes = [long](Get-ResultField $summary 'reclaimed_bytes')
            invalid_output_lines = $invalidLines
        }
    }
} catch {
    $exitCode = 2
    # Keep exception/provider text out of the storage log.
    try {
        Write-MaintenanceRecord @{ event = 'failed'; reason = 'launcher_validation_or_io_error' }
    } catch {
        # A full disk can also prevent the dedicated failure record.
    }
}
exit $exitCode
