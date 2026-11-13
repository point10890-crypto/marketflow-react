# Install the Forecast League drain task. It empties the job queue in league.db and exits.
# Preview on any machine: powershell -NoProfile -File deploy/register_league_worker_task.ps1 -Plan
# Apply on the MiniPC in an elevated shell after the tests pass.
[CmdletBinding(SupportsShouldProcess=$true)]
param([switch]$Plan)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Project = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\')
$ExpectedRoot = 'C:\bitman_marketfloww'
$Python = Join-Path $Project '.venv\Scripts\python.exe'
$Name = 'MarketFlow-LeagueWorker'
$Arguments = '-X utf8 -m app.services.league_worker drain'
$EveryMinutes = 5
$LimitMinutes = 30
$task = [pscustomobject]@{
    Name=$Name; EveryMinutes=$EveryMinutes; LimitMinutes=$LimitMinutes
    Execute=$Python; WorkingDirectory=$Project; Arguments=$Arguments
}
if ($Plan) { $task | ConvertTo-Json -Depth 3; return }
if ($env:COMPUTERNAME -ne 'MINIPC-NQYLP' -or $Project -ne $ExpectedRoot) {
    throw 'Registration is restricted to MINIPC-NQYLP at C:\bitman_marketfloww.'
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw 'Project virtualenv Python is missing.' }
if (-not (Test-Path -LiteralPath (Join-Path $Project 'app\services\league_worker\__main__.py') -PathType Leaf)) {
    throw 'League worker source is missing.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$role = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Registration needs an elevated administrator shell for the SYSTEM task principal.'
}
# Never replace a task that someone else owns.
$existing = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
if ($existing) {
    $actions = @($existing.Actions)
    if ($actions.Count -ne 1 -or $actions[0].Execute -ne $Python -or
        $actions[0].WorkingDirectory -ne $Project -or $actions[0].Arguments -ne $Arguments) {
        throw "Existing task $Name has a different owner or command; it was not replaced."
    }
}
if (-not $PSCmdlet.ShouldProcess($Name, 'Register Forecast League drain task')) { return }
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Project
$startup = New-ScheduledTaskTrigger -AtStartup
$startup.Delay = 'PT4M'
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(4) `
    -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -Hidden -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes $LimitMinutes)
Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($startup, $repeat) `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output "Registered ${Name}: every $EveryMinutes min, limit $LimitMinutes min."
