# Shared attribution for the 5003 launcher and watchdog; never log command lines.
function Test-MarketFlowFlaskProcess {
    param($Candidate, [Parameter(Mandatory = $true)][string]$Project)
    if (-not $Candidate -or -not $Candidate.CommandLine) { return $false }
    if ($Candidate.Name -notin @('python.exe', 'pythonw.exe')) { return $false }
    $pythonPattern = [regex]::Escape((Join-Path $Project '.venv\Scripts\python.exe'))
    $absoluteScript = [regex]::Escape((Join-Path $Project 'flask_app.py'))
    $command = [string]$Candidate.CommandLine
    # Both supported launchers invoke exactly Python + script, without flags.
    # Matching a later argument could attribute "unrelated.py flask_app.py".
    $venvToken = '(?:"' + $pythonPattern + '"|' + $pythonPattern + ')'
    $scriptToken = '(?:"flask_app\.py"|flask_app\.py|"' + $absoluteScript + '"|' + $absoluteScript + ')'
    $venvInvocation = '^\s*' + $venvToken + '\s+' + $scriptToken + '\s*$'
    if ($command -match $venvInvocation) { return $true }
    $pythonToken = '(?:"[^"\r\n]*\\pythonw?\.exe"|[^\s"]*\\pythonw?\.exe|pythonw?\.exe)'
    $absoluteInvocation = '^\s*' + $pythonToken + '\s+(?:"' + $absoluteScript + '"|' + $absoluteScript + ')\s*$'
    if ($command -match $absoluteInvocation) { return $true }
    $relativeInvocation = '^\s*' + $pythonToken + '\s+(?:"flask_app\.py"|flask_app\.py)\s*$'
    if ($command -match $relativeInvocation -and $Candidate.ParentProcessId) {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($Candidate.ParentProcessId)" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
        return [bool]($parent -and $parent.Name -in @('python.exe', 'pythonw.exe') -and $parent.CommandLine -match $venvInvocation)
    }
    return $false
}

function Get-MarketFlowLegacyProtectedPids {
    param([Parameter(Mandatory = $true)][string]$Project)
    $ids = [System.Collections.Generic.HashSet[int]]::new()
    foreach ($owner in @(Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue)) {
        [void]$ids.Add([int]$owner.OwningProcess)
        $child = Get-CimInstance Win32_Process -Filter "ProcessId=$($owner.OwningProcess)" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
        if ($child -and $child.ParentProcessId) {
            $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($child.ParentProcessId)" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
            if ($parent -and (Test-MarketFlowFlaskProcess -Candidate $parent -Project $Project)) {
                [void]$ids.Add([int]$parent.ProcessId)
            }
        }
    }
    return @($ids)
}

function Assert-MarketFlowPrimaryCandidates {
    param([object[]]$Candidates, [Parameter(Mandatory = $true)][string]$Project)
    $protected = @(Get-MarketFlowLegacyProtectedPids -Project $Project)
    foreach ($candidate in $Candidates) {
        if ($protected -contains [int]$candidate.ProcessId) { throw 'legacy_5001_protected' }
        if (-not (Test-MarketFlowFlaskProcess -Candidate $candidate -Project $Project)) { throw 'unverified_process' }
    }
}

function Stop-MarketFlowPrimaryTree {
    param($Snapshot, [Parameter(Mandatory = $true)][string]$Project)
    if (-not $Snapshot -or -not $Snapshot.ProcessId) { throw 'missing_process_snapshot' }
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($Snapshot.ProcessId)" -OperationTimeoutSec 3 -ErrorAction SilentlyContinue
    if (-not $current) { return }
    if (-not $Snapshot.CreationDate -or -not $current.CreationDate -or
        $current.CreationDate -ne $Snapshot.CreationDate -or
        $current.CommandLine -cne $Snapshot.CommandLine -or $current.Name -cne $Snapshot.Name) {
        throw 'process_identity_changed'
    }
    # Recheck both attribution and current 5001 protection immediately before
    # terminating the exact original incarnation, after task-stop delays.
    Assert-MarketFlowPrimaryCandidates -Candidates @($current) -Project $Project
    & taskkill.exe /F /T /PID $current.ProcessId 2>&1 | Out-Null
}
