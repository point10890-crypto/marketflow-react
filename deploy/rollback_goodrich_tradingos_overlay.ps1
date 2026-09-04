param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$GoodrichRoot = 'C:\GoodrichTradingOS',
    [switch]$SkipServiceRestart
)

$ErrorActionPreference = 'Stop'
$taskName = 'Goodrich-TradingOS'

function Get-GoodrichListenerPids {
    return @(
        Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 `
            -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

function Stop-GoodrichTaskAndWait {
    $previousPids = @(Get-GoodrichListenerPids)
    $previousStartTicks = @{}
    foreach ($processId in $previousPids) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            $previousStartTicks[[string]$processId] = $process.StartTime.ToUniversalTime().Ticks
        }
    }
    Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop | Out-Null
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -ne 'Running') {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    foreach ($processId in $previousPids) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $expectedTicks = $previousStartTicks[[string]$processId]
        if (
            $process -and
            $expectedTicks -and
            $process.StartTime.ToUniversalTime().Ticks -eq $expectedTicks
        ) {
            & taskkill.exe /PID $processId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) {
                throw "Could not terminate the previous Goodrich process tree: $processId"
            }
        }
    }
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        if ($task.State -ne 'Running' -and @(Get-GoodrichListenerPids).Count -eq 0) {
            return $previousPids
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Goodrich TradingOS port 8000 did not stop cleanly.'
}

function Start-GoodrichTaskAndVerify([int[]]$PreviousPids) {
    $startedAfter = Get-Date
    Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-RestMethod -TimeoutSec 3 `
                -Uri 'http://127.0.0.1:8000/health'
            $listenerPids = @(Get-GoodrichListenerPids)
            $freshPids = @(
                $listenerPids | Where-Object {
                    $processId = $_
                    if ($PreviousPids -contains $processId) {
                        return $false
                    }
                    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
                    return $process -and $process.StartTime -ge $startedAfter.AddSeconds(-2)
                }
            )
            $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
            $taskInfo = Get-ScheduledTaskInfo -TaskName $taskName -ErrorAction Stop
            $confirmedPids = @(Get-GoodrichListenerPids)
            if (
                $response.status -eq 'ok' -and
                $response.environment -eq 'production' -and
                $task.State -eq 'Running' -and
                $taskInfo.LastRunTime -ge $startedAfter.AddSeconds(-2) -and
                $freshPids.Count -gt 0 -and
                @($confirmedPids | Where-Object { $freshPids -contains $_ }).Count -gt 0
            ) {
                return
            }
        } catch {
            # Continue bounded readiness polling.
        }
    }
    [void](Stop-GoodrichTaskAndWait)
    throw 'Goodrich TradingOS did not start as a fresh healthy production process.'
}

$backupBase = [IO.Path]::GetFullPath((Join-Path $GoodrichRoot 'backups'))
$resolvedBackup = [IO.Path]::GetFullPath((Resolve-Path -LiteralPath $BackupPath).Path)
$requiredPrefix = $backupBase.TrimEnd('\') + '\'
if (-not $resolvedBackup.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BackupPath must stay inside the GoodrichTradingOS backups directory.'
}

$manifestPath = Join-Path $resolvedBackup 'backup-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    throw 'The selected Goodrich backup has no backup-manifest.json.'
}
$records = @(Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json)
if (-not $records) {
    throw 'The selected Goodrich backup manifest is empty.'
}

# Validate every target and required backup before stopping the live service.
$plans = @()
$rootPrefix = [IO.Path]::GetFullPath($GoodrichRoot).TrimEnd('\') + '\'
$seenTargets = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
$seenBackupLeaves = [Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($record in $records) {
    if (-not ($record.existed -is [bool])) {
        throw 'Backup manifest existed flag must be a JSON boolean.'
    }
    $relative = ([string]$record.target).Replace('/', '\')
    if ([string]::IsNullOrWhiteSpace($relative)) {
        throw 'Backup manifest target is empty.'
    }
    $target = [IO.Path]::GetFullPath((Join-Path $GoodrichRoot $relative))
    if (-not $target.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Backup manifest target escapes GoodrichRoot: $relative"
    }
    if (-not $seenTargets.Add($target)) {
        throw "Backup manifest target is duplicated: $relative"
    }

    $backupFile = $null
    $expectedHash = $null
    if ($record.existed -eq $true) {
        $leaf = Split-Path $target -Leaf
        if (-not $seenBackupLeaves.Add($leaf)) {
            throw "Backup manifest filename is duplicated: $leaf"
        }
        $backupFile = Join-Path $resolvedBackup $leaf
        $expectedHash = ([string]$record.sha256).ToLowerInvariant()
        if ($expectedHash -notmatch '^[0-9a-f]{64}$') {
            throw "Backup manifest hash is invalid: $relative"
        }
        if (-not (Test-Path -LiteralPath $backupFile -PathType Leaf)) {
            throw "Backup file is missing: $leaf"
        }
        $actualHash = (Get-FileHash -LiteralPath $backupFile -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "Backup file hash mismatch: $relative"
        }
    }
    $plans += [pscustomobject]@{
        relative = $relative
        target = $target
        backup = $backupFile
        existed = [bool]$record.existed
        sha256 = $expectedHash
    }
}

$previousPids = @()
if (-not $SkipServiceRestart) {
    $previousPids = @(Stop-GoodrichTaskAndWait)
}

try {
    foreach ($plan in $plans) {
        if ($plan.existed) {
            Copy-Item -LiteralPath $plan.backup -Destination $plan.target -Force
        } elseif (Test-Path -LiteralPath $plan.target) {
            Remove-Item -LiteralPath $plan.target -Force
        }
    }
    foreach ($plan in $plans) {
        if ($plan.existed) {
            $actualHash = (Get-FileHash -LiteralPath $plan.target -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne $plan.sha256) {
                throw "Restored file hash mismatch: $($plan.relative)"
            }
        } elseif (Test-Path -LiteralPath $plan.target) {
            throw "Rollback could not remove an originally absent file: $($plan.relative)"
        }
    }
} catch {
    if (-not $SkipServiceRestart) {
        Write-Error 'Rollback failed after shutdown; Goodrich TradingOS remains stopped.'
    }
    throw
}

if (-not $SkipServiceRestart) {
    Start-GoodrichTaskAndVerify -PreviousPids $previousPids
}

Write-Output "Goodrich overlay rollback completed from $resolvedBackup"
