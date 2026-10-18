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
