[CmdletBinding()]
param(
    [Parameter()]
    [string]$DestinationRoot
)

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $repositoryRoot 'skills\marketflow-openclaw-ops'
if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    throw 'Committed skill source is unavailable.'
}
$sourceResolved = (Resolve-Path -LiteralPath $source -ErrorAction Stop).Path

if ([string]::IsNullOrWhiteSpace($DestinationRoot)) {
    $profileRoot = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    $DestinationRoot = Join-Path $profileRoot '.codex\skills'
}
$destinationRootResolved = [System.IO.Path]::GetFullPath($DestinationRoot)
$destination = Join-Path $destinationRootResolved 'marketflow-openclaw-ops'

if (Test-Path -LiteralPath $destination) {
    $existing = Get-Item -LiteralPath $destination -Force -ErrorAction Stop
    if (($existing.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -eq 0) {
        throw 'Refusing unrelated skill destination.'
    }
    if (-not [string]::Equals([string]$existing.LinkType, 'Junction', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing non-junction skill destination.'
    }
    $target = @($existing.Target)[0]
    if ([string]::IsNullOrWhiteSpace($target)) {
        throw 'Refusing unresolved skill junction.'
    }
    if (-not [System.IO.Path]::IsPathRooted($target)) {
        $target = Join-Path (Split-Path -Parent $destination) $target
    }
    $targetResolved = (Resolve-Path -LiteralPath $target -ErrorAction Stop).Path
    if (-not [string]::Equals($targetResolved, $sourceResolved, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Refusing unrelated skill junction.'
    }
    Write-Output 'status=existing-junction'
    exit 0
}

New-Item -ItemType Directory -Path $destinationRootResolved -Force -ErrorAction Stop | Out-Null
New-Item -ItemType Junction -Path $destination -Target $sourceResolved -ErrorAction Stop | Out-Null
Write-Output 'status=created-junction'
