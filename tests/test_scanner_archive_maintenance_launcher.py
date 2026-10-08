"""The scheduled launcher has fixed local scope and never installs or sends."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'maintain_scanner_archives.ps1'


def _source():
    assert SCRIPT.is_file(), 'maintenance launcher must exist'
    return SCRIPT.read_text(encoding='utf-8-sig')


def test_launcher_fixes_scope_arguments_and_seven_day_cutoff():
    source = _source()
    assert re.search(r"\$projectRoot\s*=\s*'C:\\bitman_marketfloww'", source)
    assert '(Get-Date).Date.AddDays(-7)' in source
    assert "'.venv\\Scripts\\python.exe'" in source
    assert "'scripts\\compact_scanner_archives.py'" in source
    for argument in ("'--apply'", "'--root'", "'--before'", "'--target-free-gib', '20'", "'--max-runs', '10000'"):
        assert argument in source
    assert 'Register-ScheduledTask' not in source
    assert 'New-ScheduledTask' not in source


def test_launcher_summarizes_output_and_checks_manifest_exit_and_target():
    source = _source()
    assert 'scanner_archive_maintenance.log' in source
    assert 'ConvertFrom-Json' in source
    assert 'scanner_archive_compaction' in source
    assert 'GetFullPath' in source and 'OrdinalIgnoreCase' in source
    assert '$LASTEXITCODE' in source
    assert 'exit $exitCode' in source
    assert 'target_not_reached' in source
    assert not re.search(r'Add-Content[^\n]*\$line\b', source)
    for forbidden in ('Invoke-RestMethod', 'Invoke-WebRequest', 'send_telegram', '.env', 'Get-ChildItem Env:', 'Remove-Item', 'Move-Item'):
        assert forbidden not in source


def test_windows_powershell_parser_accepts_launcher_without_executing_it():
    _source()
    powershell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if not powershell:
        pytest.skip('PowerShell parser is unavailable on this host')
    literal = str(SCRIPT).replace("'", "''")
    command = (
        '$tokens=$null; $parseErrors=$null; '
        f"$null=[System.Management.Automation.Language.Parser]::ParseFile('{literal}',[ref]$tokens,[ref]$parseErrors); "
        'if($parseErrors.Count -gt 0){exit 1}; exit 0'
    )
    result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command', command], capture_output=True, timeout=30)
    assert result.returncode == 0, 'maintenance launcher must parse in native PowerShell'
