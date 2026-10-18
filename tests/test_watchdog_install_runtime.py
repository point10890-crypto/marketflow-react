"""Run the real installer against in-memory Task Scheduler adapters only."""
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PS51 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
pytestmark = pytest.mark.skipif(not PS51.exists(), reason='Windows PowerShell 5.1 runtime')


def test_installer_preserves_existing_task_identity_and_triggers_but_bounds_zombies():
    installer = ROOT / 'scripts' / 'install_flask_watchdog.ps1'
    command = f"""
        $env:COMPUTERNAME='MINIPC-NQYLP'
        $global:updated = [System.Collections.Generic.List[object]]::new()
        $global:created = [System.Collections.Generic.List[object]]::new()
        function Test-Path {{ return $true }}
        function Get-ScheduledTask {{ param($TaskName,$ErrorAction)
            if ($TaskName -eq 'MarketFlow-Legacy-Flask-Watchdog') {{ return $null }}
            return [pscustomobject]@{{ Settings=[pscustomobject]@{{ ExecutionTimeLimit='PT72H'; MultipleInstances=2 }}; Principal='original-account'; Triggers='original-triggers' }}
        }}
        function Unregister-ScheduledTask {{ throw 'existing identity must not be unregistered' }}
        function New-ScheduledTaskAction {{ param($Execute,$Argument,$WorkingDirectory) return [pscustomobject]@{{ Execute=$Execute; Arguments=$Argument }} }}
        function New-ScheduledTaskTrigger {{ param([switch]$AtStartup,[switch]$Once,$At,$RepetitionInterval,$RepetitionDuration) return 'new-trigger' }}
        function New-ScheduledTaskSettingsSet {{ param([switch]$AllowStartIfOnBatteries,[switch]$DontStopIfGoingOnBatteries,[switch]$StartWhenAvailable,$ExecutionTimeLimit,$MultipleInstances)
            return [pscustomobject]@{{ ExecutionTimeLimit='PT4M'; MultipleInstances=3 }}
        }}
        function New-ScheduledTaskPrincipal {{ param($UserId,$LogonType,$RunLevel) return 'SYSTEM' }}
        function Set-ScheduledTask {{ param($TaskName,$Action,$Settings,$Principal,$Trigger,$ErrorAction)
            if ($Principal -or $Trigger) {{ throw 'existing principal/triggers changed' }}
            $global:updated.Add([pscustomobject]@{{ name=$TaskName; limit=$Settings.ExecutionTimeLimit; instances=$Settings.MultipleInstances; arguments=$Action.Arguments }})
        }}
        function Register-ScheduledTask {{ param($TaskName,$Action,$Trigger,$Settings,$Principal,$Description,$ErrorAction)
            $global:created.Add([pscustomobject]@{{ name=$TaskName; arguments=$Action.Arguments; principal=$Principal }})
        }}
        & '{installer.as_posix()}' | Out-Null
        @{{ updated=@($global:updated); created=@($global:created) }} | ConvertTo-Json -Compress -Depth 5
    """
    response = subprocess.run([str(PS51), '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, text=True, timeout=8)
    assert response.returncode == 0, response.stderr[:300]
    payload = json.loads(response.stdout[response.stdout.index('{'):])
    updates = {item['name']: item for item in payload['updated']}
    assert set(updates) == {'MarketFlow-Flask-Watchdog', 'MarketFlow-Tunnel-Watchdog'}
    assert all(item['limit'] == 'PT4M' and item['instances'] == 3 for item in updates.values())
    assert '-Mode Primary' in updates['MarketFlow-Flask-Watchdog']['arguments']
    assert payload['created'][0]['name'] == 'MarketFlow-Legacy-Flask-Watchdog'
    assert '-Mode Legacy' in payload['created'][0]['arguments']


@pytest.mark.parametrize('reason,healthy,aborted', [
    ('healthy', True, False), ('deadline_exceeded', False, False),
    ('probe_unavailable', False, True), ('cleanup_failed', False, True),
])
def test_tunnel_probe_infrastructure_failure_aborts_instead_of_reporting_origin_failure(reason, healthy, aborted):
    source = ROOT / 'scripts' / 'tunnel_watchdog.ps1'
    command = f"""
        $tree = [System.Management.Automation.Language.Parser]::ParseFile('{source.as_posix()}',[ref]$null,[ref]$null)
        $definition = $tree.Find({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-Url' }}, $true)
        Invoke-Expression $definition.Extent.Text
        function Write-Log($message) {{ }}
        function Invoke-BoundedHealthProbe {{ param($Uri,$TimeoutSeconds)
            return [pscustomobject]@{{ healthy=${str(healthy).lower()}; reason='{reason}' }}
        }}
        try {{ $value=Test-Url 'http://127.0.0.1:1/healthz'; @{{healthy=$value;aborted=$false}} | ConvertTo-Json -Compress }}
        catch {{ @{{healthy=$false;aborted=$true}} | ConvertTo-Json -Compress }}
    """
    response = subprocess.run([str(PS51), '-NoProfile', '-NonInteractive', '-Command', command],
                              capture_output=True, text=True, timeout=8)
    assert response.returncode == 0, response.stderr[:300]
    assert json.loads(response.stdout) == {'healthy': healthy, 'aborted': aborted}
