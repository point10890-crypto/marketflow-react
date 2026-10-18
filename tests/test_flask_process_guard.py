"""Process attribution and launcher readiness without touching real services."""
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
PS51 = Path(r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe')
GUARD = ROOT / 'scripts' / 'flask_process_guard.ps1'
pytestmark = pytest.mark.skipif(not PS51.exists(), reason='Windows PowerShell 5.1 runtime')


def ps(script):
    response = subprocess.run([str(PS51), '-NoProfile', '-NonInteractive', '-Command', script],
                              capture_output=True, text=True, timeout=8)
    assert response.returncode == 0, response.stderr[:300]
    return json.loads(response.stdout)


@pytest.mark.parametrize('kind,expected', [('venv', True), ('absolute', True), ('forwarded', True), ('foreign', False), ('unproven', False), ('quoted_text', False), ('venv_prefix', False), ('base_script_argument', False), ('venv_script_argument', False)])
def test_process_owner_accepts_project_forwarder_but_refuses_unproven_relative_script(kind, expected):
    assert GUARD.exists(), 'shared Flask process attribution is missing'
    result = ps(f"""
        . '{GUARD.as_posix()}'
        $Project = 'C:\\bitman_marketfloww'
        function Get-CimInstance {{ param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            if ('{kind}' -eq 'forwarded') {{ return [pscustomobject]@{{ Name='python.exe'; CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py' }} }}
            return $null
        }}
        $commands = @{{
            venv='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py';
            absolute='C:\\Python311\\python.exe C:\\bitman_marketfloww\\flask_app.py';
            forwarded='C:\\Python311\\python.exe flask_app.py';
            foreign='C:\\other\\python.exe other.py';
            unproven='C:\\Python311\\python.exe flask_app.py';
            quoted_text='cmd.exe /c echo C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py';
            venv_prefix='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe.bad flask_app.py';
            base_script_argument='C:\\Python311\\python.exe unrelated.py C:\\bitman_marketfloww\\flask_app.py';
            venv_script_argument='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe unrelated.py flask_app.py'
        }}
        $p = [pscustomobject]@{{ Name='python.exe'; CommandLine=$commands['{kind}']; ProcessId=42; ParentProcessId=41 }}
        if ('{kind}' -eq 'quoted_text') {{ $p.Name='cmd.exe' }}
        Test-MarketFlowFlaskProcess -Candidate $p -Project $Project | ConvertTo-Json
    """)
    assert result is expected


def test_launcher_has_bounded_startup_readiness_function():
    source = ROOT / 'scripts' / 'start_flask_task.ps1'
    assert 'function Wait-FlaskStartup' in source.read_text(encoding='utf-8'), 'launcher still uses raw IWR polling'
    result = ps(f"""
        $tree = [System.Management.Automation.Language.Parser]::ParseFile('{source.as_posix()}',[ref]$null,[ref]$null)
        foreach ($d in $tree.FindAll({{ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }},$true)) {{ Invoke-Expression $d.Extent.Text }}
        $script:calls = 0
        function Get-Process {{ param($Id,$ErrorAction) return [pscustomobject]@{{ Id=$Id }} }}
        function Invoke-BoundedHealthProbe {{ param($Uri,$TimeoutSeconds)
            $script:calls++; return [pscustomobject]@{{ healthy=($script:calls -eq 2); reason='healthy' }}
        }}
        $r = Wait-FlaskStartup -ProcessId 42 -TimeoutSeconds 1 -PollSeconds 0
        @{{ ready=$r; calls=$script:calls }} | ConvertTo-Json -Compress
    """)
    assert result == {'ready': True, 'calls': 2}


def test_legacy_listener_and_its_venv_forwarder_are_both_protected():
    assert GUARD.exists()
    result = ps(f"""
        . '{GUARD.as_posix()}'
        function Get-NetTCPConnection {{ param($LocalPort,$State,$ErrorAction)
            if ($LocalPort -ne 5001) {{ throw 'wrong protection port' }}
            return [pscustomobject]@{{ OwningProcess=43 }}
        }}
        function Get-CimInstance {{ param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            if ($Filter -eq 'ProcessId=43') {{ return [pscustomobject]@{{ ParentProcessId=42 }} }}
            return [pscustomobject]@{{ ProcessId=42; Name='python.exe'; CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py' }}
        }}
        @(Get-MarketFlowLegacyProtectedPids -Project 'C:\\bitman_marketfloww') | Sort-Object | ConvertTo-Json -Compress
    """)
    assert result == [42, 43]


@pytest.mark.parametrize('kind,expected', [('foreign_cmd', False), ('forwarded_python', True)])
def test_legacy_recovery_uses_the_same_verified_process_attribution(kind, expected):
    source = ROOT / 'scripts' / 'flask_watchdog_v2.ps1'
    result = ps(f"""
        . '{GUARD.as_posix()}'
        $Project='C:\\bitman_marketfloww'
        $tree=[System.Management.Automation.Language.Parser]::ParseFile('{source.as_posix()}',[ref]$null,[ref]$null)
        foreach($d in $tree.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$true)) {{Invoke-Expression $d.Extent.Text}}
        function Get-CimInstance {{param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            return [pscustomobject]@{{Name='python.exe';CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py'}}
        }}
        $p=[pscustomobject]@{{Name='python.exe';CommandLine='C:\\Python313\\python.exe flask_app.py';ParentProcessId=41}}
        if ('{kind}' -eq 'foreign_cmd') {{$p.Name='cmd.exe';$p.CommandLine='cmd.exe /c echo C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py'}}
        Test-IsMarketFlowLegacyProducer $p | ConvertTo-Json
    """)
    assert result is expected


def test_launcher_does_not_spawn_more_probes_after_cleanup_failure():
    source = ROOT / 'scripts' / 'start_flask_task.ps1'
    result = ps(f"""
        $tree=[System.Management.Automation.Language.Parser]::ParseFile('{source.as_posix()}',[ref]$null,[ref]$null)
        foreach($d in $tree.FindAll({{param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$true)) {{Invoke-Expression $d.Extent.Text}}
        $script:calls=0
        function Get-Process {{return $true}}
        function Invoke-BoundedHealthProbe {{param($Uri,$TimeoutSeconds) $script:calls++;return [pscustomobject]@{{healthy=$false;reason='cleanup_failed'}}}}
        $r=Wait-FlaskStartup -ProcessId 42 -TimeoutSeconds 0.1 -PollSeconds 0
        @{{ready=$r;calls=$script:calls}} | ConvertTo-Json -Compress
    """)
    assert result == {'ready': False, 'calls': 1}


@pytest.mark.parametrize('case', ['foreign_tracked', 'foreign_listener', 'legacy_tracked'])
def test_real_launcher_refuses_all_candidates_before_any_kill_or_start(case):
    source = ROOT / 'scripts' / 'start_flask_task.ps1'
    result = ps(f"""
        $global:fixtureKills = [System.Collections.Generic.List[string]]::new()
        $global:fixtureLogs = [System.Collections.Generic.List[string]]::new()
        $global:fixtureStarts=0
        function New-Item {{ }}
        function Set-Location {{ }}
        function Add-Content {{ param($Path,$Value,$Encoding) $global:fixtureLogs.Add([string]$Value) }}
        function Set-Content {{ }}
        function Remove-Item {{ }}
        function Test-Path {{ return $true }}
        function Get-Content {{ return '42' }}
        function Start-Sleep {{ }}
        function taskkill.exe {{ $global:fixtureKills.Add('kill') }}
        function Start-Process {{ $global:fixtureStarts++; throw 'unexpected start' }}
        function Get-NetTCPConnection {{ param($LocalPort,$State,$ErrorAction)
            if ($LocalPort -eq 5001) {{
                if ('{case}' -eq 'legacy_tracked') {{ return [pscustomobject]@{{ OwningProcess=43 }} }}
                return @()
            }}
            return [pscustomobject]@{{ OwningProcess=44 }}
        }}
        function Get-CimInstance {{ param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            $id = [int]($Filter -replace 'ProcessId=','')
            if ($id -eq 43) {{ return [pscustomobject]@{{ ProcessId=43; ParentProcessId=42 }} }}
            $p = [pscustomobject]@{{ ProcessId=$id; Name='python.exe'; CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py' }}
            if (('{case}' -eq 'foreign_tracked' -and $id -eq 42) -or ('{case}' -eq 'foreign_listener' -and $id -eq 44)) {{
                $p.Name='cmd.exe'; $p.CommandLine='unrelated command'
            }}
            return $p
        }}
        & '{source.as_posix()}'
        @{{ code=$LASTEXITCODE; kills=@($global:fixtureKills); starts=$global:fixtureStarts; refused=[bool](@($global:fixtureLogs | Where-Object {{ $_ -like '*startup refused*' }}).Count) }} | ConvertTo-Json -Compress
    """)
    assert result == {'code': 1, 'kills': [], 'starts': 0, 'refused': True}


def forwarded_lifecycle(scenario):
    """Run the real guard; only CIM/port reads and native kill are adapters."""
    return ps(f"""
        . '{GUARD.as_posix()}'
        $Project='C:\\bitman_marketfloww'
        $script:parentAlive=$true
        $script:legacyOwner=0
        $script:kills=[System.Collections.Generic.List[int]]::new()
        $script:parent=[pscustomobject]@{{ProcessId=41;Name='python.exe';CreationDate=[datetime]'2026-10-19T00:00:00Z';CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py'}}
        $script:child=[pscustomobject]@{{ProcessId=42;ParentProcessId=41;Name='python.exe';CreationDate=[datetime]'2026-10-19T00:00:01Z';CommandLine='C:\\Python313\\python.exe flask_app.py'}}
        $snapshot=$script:child.PSObject.Copy()
        function Get-NetTCPConnection {{param($LocalPort,$State,$ErrorAction)
            if($LocalPort -ne 5001){{throw 'wrong protection port'}}
            if($script:legacyOwner){{return [pscustomobject]@{{OwningProcess=$script:legacyOwner}}}}
        }}
        function Get-CimInstance {{param($ClassName,$Filter,$OperationTimeoutSec,$ErrorAction)
            if($Filter -eq 'ProcessId=41' -and $script:parentAlive){{return $script:parent}}
            if($Filter -eq 'ProcessId=42'){{return $script:child}}
            return $null
        }}
        function Get-Process {{param($Id,$ErrorAction)
            if($Id -ne 42 -or $ErrorAction -ne 'Stop'){{throw 'wrong process inspection'}}
            $p=[pscustomobject]@{{Id=42;HasExited=$false}}
            $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{param($Milliseconds)
                if($Milliseconds -le 0 -or $Milliseconds -gt 1000){{throw 'unbounded exit wait'}}
                return $false
            }}
            return $p
        }}
        function taskkill.exe {{
            if($args.Count -ne 4 -or $args[0] -ne '/F' -or $args[1] -ne '/T' -or $args[2] -ne '/PID'){{throw 'wrong kill invocation'}}
            $script:kills.Add([int]$args[3])
        }}
        $errorReason=$null
        try{{ {scenario} }}catch{{$errorReason=$_.Exception.Message}}
        @{{kills=@($script:kills);reason=$errorReason}} | ConvertTo-Json -Compress
    """)


def test_prevalidated_forwarded_child_keeps_ownership_when_parent_exits_first():
    result = forwarded_lifecycle("""
        Assert-MarketFlowPrimaryCandidates -Candidates @($script:parent,$snapshot) -Project $Project
        $script:parentAlive=$false
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [42], 'reason': None}


@pytest.mark.parametrize('mutation', [
    "$script:child.CreationDate=[datetime]'2026-10-19T01:00:00Z'",
    "$script:child.CommandLine=''",
    "$script:child.Name='pythonw.exe'",
])
def test_prevalidated_proof_never_accepts_reused_or_dying_process_identity(mutation):
    result = forwarded_lifecycle(f"""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false
        {mutation}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'process_identity_changed'}


@pytest.mark.parametrize('mutation', [
    "$snapshot.MarketFlowOwnershipProof.Signature='forged'",
    "$snapshot.MarketFlowOwnershipProof.Binding='forged'",
    "$snapshot.MarketFlowOwnershipProof=[pscustomobject]@{Binding='forged';Signature='forged'}",
    "$Project='C:\\other_project'",
    "$snapshot.CommandLine='C:\\Python313\\python.exe unrelated.py';$script:child.CommandLine=$snapshot.CommandLine",
    "$snapshot.CreationDate=$snapshot.CreationDate.AddMinutes(1);$script:child.CreationDate=$snapshot.CreationDate",
    "$snapshot.Name='pythonw.exe';$script:child.Name=$snapshot.Name",
    "$snapshot.ProcessId=43;$script:child.ProcessId=43;function Get-CimInstance {return $script:child}",
])
def test_mutated_or_forged_preflight_proof_cannot_authorize_a_kill(mutation):
    result = forwarded_lifecycle(f"""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false
        {mutation}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'unverified_process'}


def test_current_legacy_listener_is_protected_even_after_successful_preflight():
    result = forwarded_lifecycle("""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false
        $script:legacyOwner=42
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'legacy_5001_protected'}


def test_unvalidated_child_still_needs_current_verified_parent():
    result = forwarded_lifecycle("""
        $script:parentAlive=$false
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'unverified_process'}


def test_failed_candidate_batch_does_not_issue_partial_ownership_proofs():
    result = forwarded_lifecycle("""
        $foreign=[pscustomobject]@{ProcessId=43;Name='cmd.exe';CommandLine='unrelated'}
        try{Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot,$foreign) -Project $Project}catch{}
        $script:parentAlive=$false
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'unverified_process'}


def test_preflight_proof_can_be_attached_to_native_cim_snapshot():
    result = ps(f"""
        . '{GUARD.as_posix()}'
        $Project='C:\\bitman_marketfloww'
        $snapshot=New-CimInstance -ClassName Win32_Process -ClientOnly -Property @{{
            ProcessId=[uint32]42;Name='python.exe';CreationDate=[datetime]'2026-10-19T00:00:00Z';
            CommandLine='C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe flask_app.py'
        }}
        function Get-NetTCPConnection {{return @()}}
        function Get-CimInstance {{return $snapshot}}
        $script:kills=0
        function taskkill.exe {{$script:kills++}}
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
        @{{native=($snapshot -is [Microsoft.Management.Infrastructure.CimInstance]);kills=$script:kills;proof=[bool]$snapshot.MarketFlowOwnershipProof}} | ConvertTo-Json -Compress
    """)
    assert result == {'native': True, 'kills': 1, 'proof': True}


@pytest.mark.parametrize('missing', ['CommandLine', 'CreationDate', 'Name', 'all'])
@pytest.mark.parametrize('exit_state', ['missing', 'exited', 'wait_exited'])
def test_matching_tombstone_is_skipped_only_after_independent_exit_confirmation(missing, exit_state):
    result = forwarded_lifecycle(f"""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false
        if('{missing}' -eq 'all'){{$script:child.CommandLine=$null;$script:child.CreationDate=$null;$script:child.Name=$null}}
        else{{$script:child.'{missing}'=$null}}
        function Get-Process {{param($Id,$ErrorAction)
            if($Id -ne 42 -or $ErrorAction -ne 'Stop'){{throw 'wrong process inspection'}}
            if('{exit_state}' -eq 'missing'){{
                throw [System.Management.Automation.ErrorRecord]::new(
                    [Microsoft.PowerShell.Commands.ProcessCommandException]::new('fixture missing'),
                    'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand',
                    [System.Management.Automation.ErrorCategory]::ObjectNotFound,[int]42)
            }}
            $p=[pscustomobject]@{{Id=42;HasExited=('{exit_state}' -eq 'exited')}}
            $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{param($Milliseconds)
                if($Milliseconds -le 0 -or $Milliseconds -gt 1000){{throw 'unbounded exit wait'}}
                return $true
            }}
            return $p
        }}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': None}


@pytest.mark.parametrize('inspection', ['alive', 'null_without_error', 'access_denied', 'wait_error', 'wrong_missing_id'])
def test_tombstone_alive_or_unverifiable_process_never_advances_recovery(inspection):
    result = forwarded_lifecycle(f"""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false;$script:child.CommandLine=$null
        function Get-Process {{param($Id,$ErrorAction)
            if('{inspection}' -eq 'null_without_error'){{return $null}}
            if('{inspection}' -eq 'access_denied'){{throw 'inspection unavailable'}}
            if('{inspection}' -eq 'wrong_missing_id'){{
                throw [System.Management.Automation.ErrorRecord]::new(
                    [Microsoft.PowerShell.Commands.ProcessCommandException]::new('fixture missing'),
                    'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand',
                    [System.Management.Automation.ErrorCategory]::ObjectNotFound,[int]43)
            }}
            $p=[pscustomobject]@{{Id=42;HasExited=$false}}
            $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{param($Milliseconds)
                if($Milliseconds -le 0 -or $Milliseconds -gt 1000){{throw 'unbounded exit wait'}}
                if('{inspection}' -eq 'wait_error'){{throw 'exit inspection unavailable'}}
                return $false
            }}
            return $p
        }}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'process_identity_changed'}


@pytest.mark.parametrize('different', ['CommandLine', 'CreationDate', 'Name'])
def test_nonempty_identity_difference_is_refused_even_when_another_field_is_missing(different):
    result = forwarded_lifecycle(f"""
        Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project
        $script:parentAlive=$false
        $script:child.CommandLine=$null;$script:child.Name=$null
        if('{different}' -eq 'CommandLine'){{$script:child.CommandLine='different.py'}}
        if('{different}' -eq 'CreationDate'){{$script:child.CreationDate=$script:child.CreationDate.AddMinutes(1)}}
        if('{different}' -eq 'Name'){{$script:child.Name='foreign.exe'}}
        function Get-Process {{throw 'must not inspect mismatched identity'}}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': 'process_identity_changed'}


@pytest.mark.parametrize('ownership', ['forged', 'unvalidated', 'incomplete_snapshot'])
def test_tombstone_exit_does_not_bypass_original_snapshot_ownership(ownership):
    result = forwarded_lifecycle(f"""
        if('{ownership}' -ne 'unvalidated'){{Assert-MarketFlowPrimaryCandidates -Candidates @($snapshot) -Project $Project}}
        if('{ownership}' -eq 'forged'){{$snapshot.MarketFlowOwnershipProof.Signature='forged'}}
        if('{ownership}' -eq 'incomplete_snapshot'){{$snapshot.CreationDate=$null}}
        $script:parentAlive=$false;$script:child.CommandLine=$null
        function Get-Process {{return [pscustomobject]@{{Id=42;HasExited=$true}}}}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result['kills'] == []
    assert result['reason'] is not None


def test_unsealed_snapshot_may_skip_exited_tombstone_only_with_current_strict_ownership():
    result = forwarded_lifecycle("""
        $script:child.CommandLine=$null
        function Get-Process {return [pscustomobject]@{Id=42;HasExited=$true}}
        Stop-MarketFlowPrimaryTree -Snapshot $snapshot -Project $Project
    """)
    assert result == {'kills': [], 'reason': None}
