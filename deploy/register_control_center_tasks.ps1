# Install independent observation tasks. No business writes, repair, or alerts.
# Preview on any machine: powershell -NoProfile -File deploy/register_control_center_tasks.ps1 -Plan
# Apply on the MiniPC in an elevated shell after tests and one no-alert run.
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$Plan)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$ExpectedRoot = 'C:\bitman_marketfloww'
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$tiers = @(
    @{ Name='MarketFlow-ControlCenter-Fast'; Tier='fast'; Every=1; Limit=4; Delay=1 },
    @{ Name='MarketFlow-ControlCenter-Standard'; Tier='standard'; Every=10; Limit=9; Delay=2 },
    @{ Name='MarketFlow-ControlCenter-Deep'; Tier='deep'; Every=60; Limit=15; Delay=3 }
)
$plans = @($tiers | ForEach-Object {
    [pscustomobject]@{
        Name=$_.Name; Tier=$_.Tier; EveryMinutes=$_.Every; LimitMinutes=$_.Limit
        DelayMinutes=$_.Delay; Execute=$Python; WorkingDirectory=$Project
        Arguments="-X utf8 -m app.services.control_center run --tier $($_.Tier) --no-alerts"
    }
})
if ($Plan) { $plans | ConvertTo-Json -Depth 4; return }
if ($env:COMPUTERNAME -ne 'MINIPC-NQYLP' -or $Project -ne $ExpectedRoot) {
    throw 'Registration is restricted to MINIPC-NQYLP at C:\bitman_marketfloww.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Project virtualenv Python is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $Project 'app\services\control_center\__main__.py') -PathType Leaf)) {
    throw 'Control Center source is missing.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$role = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Registration needs an elevated administrator shell for the SYSTEM task principal.'
}
# Validate all existing tasks before modifying any. Never remove a task first.
foreach ($p in $plans) {
    $existing = Get-ScheduledTask -TaskName $p.Name -ErrorAction SilentlyContinue
    if ($existing) {
        $actions = @($existing.Actions)
        if ($actions.Count -ne 1 -or $actions[0].Execute -ne $p.Execute -or
            $actions[0].WorkingDirectory -ne $Project -or
            $actions[0].Arguments -notmatch '^(-X utf8 )?-m app\.services\.control_center run --tier (fast|standard|deep)( --no-alerts)?$') {
            throw "Existing task $($p.Name) has a different owner or command; no task was replaced."
        }
    }
}
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
foreach ($p in $plans) {
    if (-not $PSCmdlet.ShouldProcess($p.Name, 'Register quiet Control Center observation task')) { continue }
    $action = New-ScheduledTaskAction -Execute $p.Execute -Argument $p.Arguments -WorkingDirectory $Project
    $startup = New-ScheduledTaskTrigger -AtStartup
    $startup.Delay = "PT$($p.DelayMinutes)M"
    $repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes($p.DelayMinutes) `
        -RepetitionInterval (New-TimeSpan -Minutes $p.EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $p.LimitMinutes)
    Register-ScheduledTask -TaskName $p.Name -Action $action -Trigger @($startup,$repeat) `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Output "Registered $($p.Name): every $($p.EveryMinutes) min, alerts disabled."
}
