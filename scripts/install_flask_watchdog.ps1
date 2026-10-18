# Run elevated on the MiniPC. Update existing task identities/triggers in place.
$ErrorActionPreference = 'Stop'
$Project = 'C:\bitman_marketfloww'
if ($env:COMPUTERNAME -ne 'MINIPC-NQYLP') {
    throw 'MarketFlow watchdog installation is MiniPC-only.'
}

$definitions = @(
    @{ Name='MarketFlow-Flask-Watchdog'; Script='flask_watchdog_v2.ps1'; Mode='Primary' },
    @{ Name='MarketFlow-Legacy-Flask-Watchdog'; Script='flask_watchdog_v2.ps1'; Mode='Legacy' },
    @{ Name='MarketFlow-Tunnel-Watchdog'; Script='tunnel_watchdog.ps1'; Mode='' }
)
foreach ($definition in $definitions) {
    $scriptPath = Join-Path $Project ('scripts\' + $definition.Script)
    if (-not (Test-Path -LiteralPath $scriptPath)) { throw 'Watchdog script is missing.' }
    $arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $scriptPath + '"'
    if ($definition.Mode) { $arguments += ' -Mode ' + $definition.Mode }
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $Project
    $existing = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
    if ($existing) {
        # Preserve principal, triggers, enabled state and other operating policy.
        $settings = $existing.Settings
        $settings.ExecutionTimeLimit = 'PT4M'
        # The PowerShell enum omits StopExisting; the native CIM policy supports it.
        $settings.CimInstanceProperties['MultipleInstances'].Value = [uint32]3
        Set-ScheduledTask -TaskName $definition.Name -Action $action -Settings $settings -ErrorAction Stop | Out-Null
    } else {
        $triggers = @(
            (New-ScheduledTaskTrigger -AtStartup),
            (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650))
        )
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
        $settings.CimInstanceProperties['MultipleInstances'].Value = [uint32]3
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $definition.Name -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description ('MarketFlow bounded ' + $definition.Mode + ' health recovery; independent five-minute monitoring.') -ErrorAction Stop | Out-Null
    }
    Write-Host ('Configured: ' + $definition.Name)
}
