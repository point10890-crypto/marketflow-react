# Register MarketFlow-Claw (resident loop) + MarketFlow-Claw-Watchdog in Windows Task Scheduler.
# Run ONCE as Administrator on the MiniPC. Idempotent: safe to re-run.
#
#   Start-Process powershell -Verb RunAs -ArgumentList '-ExecutionPolicy Bypass -File C:\bitman_marketfloww\deploy\register_claw_task.ps1'
#
# Both tasks run as NT AUTHORITY\SYSTEM (same as MarketFlow-Scheduler / -Flask), AtStartup.
# The watchdog additionally repeats every 5 minutes and restarts the loop if data\claw\heartbeat.json is stale.
# MiniPC-only guard: set MARKETFLOW_ALLOW_CLAW=1 to register on another host intentionally.

$ErrorActionPreference = 'Stop'

$Project      = $env:MARKETFLOW_PROJECT_DIR
if ([string]::IsNullOrWhiteSpace($Project)) { $Project = 'C:\bitman_marketfloww' }
$AllowedHosts = @('MINIPC-NQYLP')
$LoopTask     = 'MarketFlow-Claw'
$WatchTask    = 'MarketFlow-Claw-Watchdog'
$Vbs          = Join-Path $Project 'deploy\start_claw.vbs'
$Watchdog     = Join-Path $Project 'scripts\claw_watchdog.ps1'

if (($AllowedHosts -notcontains $env:COMPUTERNAME) -and ($env:MARKETFLOW_ALLOW_CLAW -ne '1')) {
    Write-Host "Skip: $LoopTask is MiniPC-only. Current host: $env:COMPUTERNAME" -ForegroundColor Yellow
    Write-Host "Set MARKETFLOW_ALLOW_CLAW=1 only for an intentional host migration."
    exit 0
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$role = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $role.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "register_claw_task.ps1 must run elevated (SYSTEM principal)."
}
foreach ($f in @($Vbs, $Watchdog)) { if (-not (Test-Path $f)) { throw "Missing file: $f" } }
New-Item -ItemType Directory -Force (Join-Path $Project 'logs') | Out-Null
New-Item -ItemType Directory -Force (Join-Path $Project 'data\claw') | Out-Null

foreach ($t in @($LoopTask, $WatchTask)) {
    Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue
}

$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest

# 1) resident loop
$loopAction = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument "`"$Vbs`"" -WorkingDirectory $Project
$loopSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $LoopTask -Action $loopAction -Trigger (New-ScheduledTaskTrigger -AtStartup) `
    -Settings $loopSettings -Principal $principal -Force | Out-Null
Write-Host "[OK] $LoopTask registered (SYSTEM, AtStartup)"

# 2) watchdog: AtStartup + every 5 minutes
$wdAction = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Watchdog`"" -WorkingDirectory $Project
$wdTrigger1 = New-ScheduledTaskTrigger -AtStartup
$wdTrigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$wdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $WatchTask -Action $wdAction -Trigger @($wdTrigger1, $wdTrigger2) `
    -Settings $wdSettings -Principal $principal -Force | Out-Null
Write-Host "[OK] $WatchTask registered (SYSTEM, AtStartup + 5 min)"

Start-ScheduledTask -TaskName $LoopTask
Write-Host "[OK] $LoopTask started. Verify: .venv\Scripts\python.exe -m marketflow_claw status"
