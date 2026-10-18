"""Execute watchdog functions with OS mutations replaced by recording adapters."""
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PS51 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
pytestmark = pytest.mark.skipif(not PS51.exists(), reason='Windows PowerShell 5.1 runtime')


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run_guard(tmp_path, scenario):
    source = ROOT / 'scripts' / 'flask_watchdog_v2.ps1'
    assert 'function Invoke-PrimaryFlaskWatchdog' in source.read_text(encoding='utf-8'), 'primary recovery is not isolated from legacy'
    script = f"""
        . '{(ROOT / 'scripts' / 'flask_process_guard.ps1').as_posix()}'
        $tree = [System.Management.Automation.Language.Parser]::ParseFile({quote(source)}, [ref]$null, [ref]$null)
        $tree.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }}, $true) | ForEach-Object {{ Invoke-Expression $_.Extent.Text }}
        $Project = {quote(tmp_path)}
        $TaskName = 'MarketFlow-Flask'
        $RestartRequestFile = Join-Path $Project 'flask_restart.request'
        $PidFile = Join-Path $Project 'flask_5003.pid'
        $FailureThreshold = 3
        $script:events = [System.Collections.Generic.List[string]]::new()
        $script:probes = 0
        function Write-Log($message) {{ }}
        function Write-State($failures) {{ $script:events.Add("state:$failures") }}
        function Read-Failures {{ return 0 }}
        function Test-FlaskStarting {{ return $false }}
        function Get-FlaskProcesses {{ return @() }}
        function Get-MarketFlowLegacyProtectedPids {{ return @() }}
        function Get-NetTCPConnection {{ param($LocalPort,$State,$ErrorAction) return @() }}
        function Test-Health {{ $script:events.Add('primary_probe'); $script:probes++; return $script:probes -gt 1 }}
        function Stop-ScheduledTask {{ param($TaskName, $ErrorAction) $script:events.Add("stop:$TaskName") }}
        function Start-ScheduledTask {{ param($TaskName, $ErrorAction) $script:events.Add("start:$TaskName") }}
        function Start-Sleep {{ param($Seconds, $Milliseconds) }}
        function taskkill.exe {{ $script:events.Add('kill') }}
        function Invoke-LegacyProducerWatchdog {{ $script:events.Add('legacy'); throw 'legacy blocked' }}
        {scenario}
        @{{ code = $code; events = @($script:events) }} | ConvertTo-Json -Compress
    """
    response = subprocess.run([str(PS51), '-NoProfile', '-NonInteractive', '-Command', script],
                              capture_output=True, text=True, timeout=10)
    assert response.returncode == 0, response.stderr[:300]
    return json.loads(response.stdout)


def test_primary_mode_recovers_5003_without_touching_a_stalled_legacy(tmp_path):
    result = run_guard(tmp_path, "$code = Invoke-FlaskWatchdog -Mode Primary")
    assert result['code'] == 0
    assert result['events'] == ['primary_probe', 'stop:MarketFlow-Flask', 'start:MarketFlow-Flask', 'primary_probe', 'state:0']


def test_combined_mode_attempts_primary_recovery_before_legacy_failure(tmp_path):
    result = run_guard(tmp_path, "$code = Invoke-FlaskWatchdog -Mode All")
    assert result['code'] == 1
    assert result['events'][-1] == 'legacy'
    assert result['events'].index('start:MarketFlow-Flask') < result['events'].index('legacy')


def test_force_restart_request_is_consumed_once_before_start(tmp_path):
    marker = tmp_path / 'flask_restart.request'
    marker.write_text('restart', encoding='ascii')
    result = run_guard(tmp_path, "$code = Invoke-FlaskWatchdog -Mode Primary")
    assert result['code'] == 0
    assert not marker.exists()
    assert result['events'].count('start:MarketFlow-Flask') == 1


def test_foreign_pid_blocks_restart_before_launcher_can_terminate_it(tmp_path):
    result = run_guard(tmp_path, """
        function Get-FlaskProcesses { return @([pscustomobject]@{ ProcessId=42; CommandLine='C:\\other\\python.exe unrelated.py' }) }
        $code = Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 1
    assert not any(event.startswith(('start:', 'stop:')) for event in result['events'])


def test_startup_grace_does_not_restart_a_recent_primary(tmp_path):
    result = run_guard(tmp_path, """
        function Test-FlaskStarting { return $true }
        $code = Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 0
    assert result['events'] == ['primary_probe']


def test_stale_primary_pid_file_must_not_stop_the_legacy_5001_forwarder(tmp_path):
    result = run_guard(tmp_path, """
        function Get-FlaskProcesses { return @([pscustomobject]@{ ProcessId=42; Name='python.exe'; CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe') + ' flask_app.py') }) }
        function Get-MarketFlowLegacyProtectedPids { return @(42,43) }
        $code = Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 1
    assert not any(event.startswith(('start:', 'stop:')) for event in result['events'])


@pytest.mark.parametrize('name', ['Test-Health', 'Test-LegacyProducerHealth'])
def test_probe_cleanup_failure_is_monitor_error_and_never_service_down(name):
    source = ROOT / 'scripts' / 'flask_watchdog_v2.ps1'
    script = f"""
        $tree=[System.Management.Automation.Language.Parser]::ParseFile('{source.as_posix()}',[ref]$null,[ref]$null)
        foreach($d in $tree.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$true)) {{Invoke-Expression $d.Extent.Text}}
        function Invoke-BoundedHealthProbe {{param($Uri,$TimeoutSeconds) return [pscustomobject]@{{healthy=$false;reason='cleanup_failed'}}}}
        function Write-Log {{}}
        $thrown=$false
        try {{$value={name}}} catch {{$thrown=$true}}
        $thrown | ConvertTo-Json
    """
    result=subprocess.run([str(PS51),'-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=8)
    assert result.returncode == 0
    assert json.loads(result.stdout) is True


@pytest.mark.parametrize('current', ['reused', 'gone'])
def test_primary_skips_expired_identity_without_killing_it_and_restarts_on_a_free_port(tmp_path, current):
    result = run_guard(tmp_path, f"""
        function Get-FlaskProcesses {{ return @([pscustomobject]@{{ ProcessId=42; Name='python.exe'; CreationDate='2026-10-19T00:00:00'; CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe') + ' flask_app.py') }}) }}
        function Get-CimInstance {{ param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            if ('{current}' -eq 'gone') {{ return $null }}
            return [pscustomobject]@{{ ProcessId=42; Name='python.exe'; CreationDate='2026-10-19T01:00:00'; CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe') + ' flask_app.py') }}
        }}
        $code = Invoke-FlaskWatchdog -Mode Primary
    """)
    assert 'kill' not in result['events']
    assert result['code'] == 0
    assert 'start:MarketFlow-Flask' in result['events']


def test_prevalidated_forwarded_child_can_be_recovered_after_task_stop_exits_its_parent(tmp_path):
    result = run_guard(tmp_path, """
        $script:parentAlive=$true
        $script:parentSnapshot=[pscustomobject]@{ProcessId=41;Name='python.exe';CreationDate='2026-10-19T00:00:00';CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe')+' flask_app.py')}
        $script:childSnapshot=[pscustomobject]@{ProcessId=42;ParentProcessId=41;Name='python.exe';CreationDate='2026-10-19T00:00:01';CommandLine='C:\\Python313\\python.exe flask_app.py'}
        function Get-FlaskProcesses { return @($script:parentSnapshot,$script:childSnapshot) }
        function Get-CimInstance { param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            if($Filter -eq 'ProcessId=41' -and $script:parentAlive) {return $script:parentSnapshot}
            if($Filter -eq 'ProcessId=42') {return $script:childSnapshot}
            return $null
        }
        function Stop-ScheduledTask { param($TaskName,$ErrorAction) $script:events.Add("stop:$TaskName");$script:parentAlive=$false }
        $code=Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 0
    assert result['events'] == ['primary_probe', 'stop:MarketFlow-Flask', 'kill',
                                'start:MarketFlow-Flask', 'primary_probe', 'state:0']


@pytest.mark.parametrize('reason,expected', [
    ('unverified_process', 'unverified_process'),
    ('process_identity_changed', 'process_identity_changed'),
    ('private_api_key=never_emit', 'unexpected_failure'),
])
def test_primary_failure_logs_only_allowlisted_reason_and_source_line(tmp_path, reason, expected):
    result = run_guard(tmp_path, f"""
        function Write-Log($message) {{ $script:events.Add([string]$message) }}
        function Invoke-PrimaryFlaskWatchdog {{ throw '{reason}' }}
        $code=Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 1
    assert len(result['events']) == 1
    assert f'reason={expected}' in result['events'][0]
    assert 'line=' in result['events'][0]
    assert 'never_emit' not in result['events'][0]


@pytest.mark.parametrize('process_state', ['exited', 'live', 'inspection_error'])
def test_post_stop_confirmed_exit_proceeds_but_a_bound_port_or_inspection_failure_blocks_start(tmp_path, process_state):
    result = run_guard(tmp_path, f"""
        function Get-FlaskProcesses {{ return @([pscustomobject]@{{ProcessId=42;Name='python.exe';CreationDate='2026-10-19T00:00:00';CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe')+' flask_app.py')}}) }}
        function Get-CimInstance {{ param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            return [pscustomobject]@{{ProcessId=42;Name='python.exe';CreationDate='2026-10-19T00:00:00';CommandLine=$null}}
        }}
        function Get-Process {{ param($Id,$ErrorAction)
            if('{process_state}' -eq 'inspection_error') {{throw 'private_api_key=never_emit'}}
            $p=[pscustomobject]@{{Id=$Id;HasExited=('{process_state}' -eq 'exited')}}
            $p|Add-Member ScriptMethod WaitForExit {{param($milliseconds) return $false}}
            return $p
        }}
        function Get-NetTCPConnection {{ param($LocalPort,$State,$ErrorAction)
            if('{process_state}' -eq 'inspection_error') {{throw 'private_port_probe_error'}}
            if('{process_state}' -eq 'live') {{return [pscustomobject]@{{LocalPort=5003}}}}
            return @()
        }}
        $code=Invoke-FlaskWatchdog -Mode Primary
    """)
    assert 'kill' not in result['events']
    assert result['code'] == (0 if process_state == 'exited' else 1)
    assert ('start:MarketFlow-Flask' in result['events']) is (process_state == 'exited')


@pytest.mark.parametrize('reason,port,allowed', [
    ('process_identity_changed', 'free', True), ('unverified_process', 'free', True),
    ('process_identity_changed', 'occupied', False), ('unverified_process', 'occupied', False),
    ('process_identity_changed', 'inspection_error', False),
    ('legacy_5001_protected', 'free', False), ('unknown_failure', 'free', False),
])
def test_post_stop_cleanup_refusal_never_kills_and_only_known_reasons_can_restart_on_a_free_port(tmp_path, reason, port, allowed):
    result = run_guard(tmp_path, f"""
        function Get-FlaskProcesses {{ return @([pscustomobject]@{{ProcessId=42;Name='python.exe';CreationDate='2026-10-19T00:00:00';CommandLine=((Join-Path $Project '.venv\\Scripts\\python.exe')+' flask_app.py')}}) }}
        function Stop-MarketFlowPrimaryTree {{param($Snapshot,$Project) throw '{reason}'}}
        function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction)
            if('{port}' -eq 'inspection_error') {{throw 'private_port_probe_error'}}
            if('{port}' -eq 'occupied') {{return [pscustomobject]@{{LocalPort=5003}}}}
            return @()
        }}
        $code=Invoke-FlaskWatchdog -Mode Primary
    """)
    assert 'kill' not in result['events']
    assert result['code'] == (0 if allowed else 1)
    assert ('start:MarketFlow-Flask' in result['events']) is allowed


def test_primary_preserves_a_pid_reference_changed_during_task_stop(tmp_path):
    marker = tmp_path / 'flask_5003.pid'
    marker.write_text('42', encoding='ascii')
    result = run_guard(tmp_path, """
        function Stop-ScheduledTask {param($TaskName,$ErrorAction) $script:events.Add("stop:$TaskName");Set-Content -LiteralPath $PidFile -Value '99' -Encoding ASCII}
        $code=Invoke-FlaskWatchdog -Mode Primary
    """)
    assert result['code'] == 1
    assert 'start:MarketFlow-Flask' not in result['events']
    assert marker.read_text(encoding='ascii').strip() == '99'
