param([string]$RepoRoot = 'C:\bitman_marketfloww')
$ErrorActionPreference = 'Stop'
$resolvedRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
$python = Join-Path $resolvedRoot '.venv\Scripts\python.exe'
$script = Join-Path $resolvedRoot 'scripts\mirofish_semantic_shadow.py'
$output = Join-Path $resolvedRoot 'data\admin_mirofish\semantic_decisions\worker_last_invocation.json'
if (!(Test-Path -LiteralPath $python) -or !(Test-Path -LiteralPath $script)) { throw 'Required files missing' }
$action = New-ScheduledTaskAction -Execute $python -Argument ('"'+$script+'" worker --output "'+$output+'"') -WorkingDirectory $resolvedRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$account = (Get-ScheduledTask -TaskName 'MarketFlow-Flask').Principal.UserId
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName 'MarketFlow-Semantic-Shadow' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Bounded DeepSeek semantic shadow evaluation; no live ranking or orders' -Force | Select-Object TaskName, State
