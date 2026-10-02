"""Offline scan operator boundaries and the actual nightly stage sequence."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
import venv

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / 'scripts' / 'scan_chart_analogue_top3.py'
NIGHTLY = REPO_ROOT / 'scripts' / 'refresh_chart_analogue_index.ps1'
POWERSHELL = shutil.which('powershell') or shutil.which('pwsh')
STAGES = [
    'refresh_chart_analogue_prices.py',
    'build_chart_analogue_index.py',
    'evaluate_chart_analogue_shadow.py',
    'scan_chart_analogue_top3.py',
]


def _load_cli():
    assert SCRIPT.is_file(), 'The offline TOP3 scan CLI is missing'
    spec = importlib.util.spec_from_file_location('chart_analogue_top3_cli', SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _scan_service(monkeypatch, run_scan):
    from app.services import mirofish

    service = SimpleNamespace(run_scan=run_scan)
    monkeypatch.setattr(mirofish, 'chart_analogue_top3', service, raising=False)
    monkeypatch.setitem(sys.modules, 'app.services.mirofish.chart_analogue_top3', service)


@pytest.mark.parametrize('status', ['ready', 'insufficient_candidates', 'running', 'joined'])
def test_cli_success_passes_explicit_offline_scope_and_prints_safe_summary(
    monkeypatch, capsys, tmp_path, status,
):
    root = str(tmp_path / 'reports')
    index_root = str(tmp_path / 'prepared-index')
    as_of = '2026-10-02T09:00:00+09:00'

    def run_scan(**kwargs):
        if kwargs != {'root': root, 'index_root': index_root, 'as_of': as_of}:
            raise ValueError('the scan received the wrong offline scope')
        return {
            'status': status,
            'generated_at': as_of,
            'universe': {'indexed': 10, 'processed': 10, 'eligible': 1, 'rejected': 9,
                         'private_path': 'C:/private/index'},
            'candidates': [{'symbol': '005930', 'target': 'Test', 'score': 72.5,
                            'private_path': 'C:/private/report.json'}],
            'artifact_root': 'C:/private/reports',
            'private_exception': 'sensitive diagnostic',
        }

    _scan_service(monkeypatch, run_scan)
    result = _load_cli().main(['--root', root, '--index-root', index_root, '--as-of', as_of])
    captured = capsys.readouterr()
    assert result == 0
    assert json.loads(captured.out) == {
        'status': status, 'generated_at': as_of,
        'universe': {'indexed': 10, 'processed': 10, 'eligible': 1, 'rejected': 9},
        'candidates': [{'symbol': '005930', 'target': 'Test', 'score': 72.5}],
    }
    assert captured.err == ''
    assert 'private' not in captured.out
    assert root not in captured.out


def test_cli_defaults_leave_service_paths_and_cutoff_optional(monkeypatch, capsys):
    def run_scan(**kwargs):
        if kwargs != {'root': None, 'index_root': None, 'as_of': None}:
            raise ValueError('defaults must remain service-owned')
        return {'status': 'insufficient_candidates', 'generated_at': None,
                'universe': {}, 'candidates': []}

    _scan_service(monkeypatch, run_scan)
    assert _load_cli().main([]) == 0
    assert json.loads(capsys.readouterr().out)['candidates'] == []


@pytest.mark.parametrize('status', ['unavailable', 'failed', 'stale', 'collecting', None])
def test_cli_non_success_report_exits_one_without_private_report_fields(
    monkeypatch, capsys, status,
):
    _scan_service(monkeypatch, lambda **kwargs: {
        'status': status, 'private_exception': 'C:/private/broken-index',
    })
    assert _load_cli().main([]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        'status': 'unavailable', 'error': 'chart_top3_scan_failed',
    }
    assert captured.err == ''


@pytest.mark.parametrize('exception_type', [OSError, ValueError, RuntimeError, KeyError, TypeError])
def test_cli_scan_exception_is_a_safe_failure(monkeypatch, capsys, exception_type):
    def run_scan(**kwargs):
        raise exception_type('private API-key diagnostic C:/private/index')

    _scan_service(monkeypatch, run_scan)
    assert _load_cli().main([]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        'status': 'unavailable', 'error': 'chart_top3_scan_failed',
    }
    assert captured.err == ''


def test_cli_executable_fails_safely_for_an_absent_local_index(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), '--root', str(tmp_path / 'reports'),
         '--index-root', str(tmp_path / 'missing-index'), '--as-of', '2026-10-02T09:00:00+09:00'],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert json.loads(result.stdout) == {
        'status': 'unavailable', 'error': 'chart_top3_scan_failed',
    }
    assert result.stderr == ''
    assert not (tmp_path / 'missing-index').exists()


def _nightly_project(tmp_path, *, failed_stage=None, missing_scanner=False):
    root = tmp_path / 'project with spaces'
    root.mkdir()
    venv.EnvBuilder(with_pip=False).create(root / '.venv')
    scripts = root / 'scripts'
    scripts.mkdir()
    prices = root / 'data' / 'daily_prices.csv'
    prices.parent.mkdir()
    prices.write_text('symbol,name\n005930,Test\n', encoding='utf-8')
    index = root / 'data' / 'chart_analogue'
    index.mkdir()
    (index / 'prepared.json').write_text('existing-index', encoding='utf-8')
    for stage in STAGES:
        if missing_scanner and stage == STAGES[-1]:
            continue
        effect = ''
        if stage == STAGES[0] and stage != failed_stage:
            effect = "(root/'data'/'chart_analogue'/'closed_prices.csv').write_text('closed-prices', encoding='utf-8')\n"
        elif stage == STAGES[1] and stage != failed_stage:
            effect = "(root/'data'/'chart_analogue'/'prepared.json').write_text('new-prepared-index', encoding='utf-8')\n"
        (scripts / stage).write_text(
            "import json\nfrom pathlib import Path\nimport sys\n"
            "root=Path.cwd()\n"
            "with (root/'calls.jsonl').open('a', encoding='utf-8') as handle:\n"
            "    handle.write(json.dumps({'stage': Path(__file__).name, 'args': sys.argv[1:]})+'\\n')\n"
            f"{effect}"
            f"raise SystemExit({9 if stage == failed_stage else 0})\n",
            encoding='utf-8',
        )
    return root


def _run_nightly(tmp_path, root):
    # Catch only for compact diagnostics: the real refresh script owns stage execution.
    wrapper = tmp_path / 'invoke-nightly.ps1'
    wrapper.write_text(
        "param([string]$RefreshScript, [string]$Root)\n"
        "$ErrorActionPreference = 'Stop'\n"
        "try { & $RefreshScript -Root $Root; exit 0 }\n"
        "catch { Write-Output $_.Exception.Message; exit 1 }\n",
        encoding='utf-8',
    )
    return subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
         '-File', str(wrapper), '-RefreshScript', str(NIGHTLY), '-Root', str(root)],
        capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
    )


def _nightly_calls(root):
    path = root / 'calls.jsonl'
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


@pytest.mark.skipif(POWERSHELL is None or sys.platform != 'win32', reason='Windows PowerShell is required')
def test_nightly_scan_runs_after_collection_index_and_evaluation(tmp_path):
    root = _nightly_project(tmp_path)
    result = _run_nightly(tmp_path, root)
    assert result.returncode == 0, result.stdout + result.stderr
    calls = _nightly_calls(root)
    assert [call['stage'] for call in calls] == STAGES
    assert calls[2]['args'] == ['--ingest-latest']
    assert calls[3]['args'] == []
    assert (root / 'data' / 'chart_analogue' / 'prepared.json').read_text() == 'new-prepared-index'


@pytest.mark.skipif(POWERSHELL is None or sys.platform != 'win32', reason='Windows PowerShell is required')
def test_nightly_scan_failure_retains_the_new_prepared_index(tmp_path):
    root = _nightly_project(tmp_path, failed_stage=STAGES[-1])
    result = _run_nightly(tmp_path, root)
    assert result.returncode == 1
    assert [call['stage'] for call in _nightly_calls(root)] == STAGES
    assert (root / 'data' / 'chart_analogue' / 'prepared.json').read_text() == 'new-prepared-index'
    assert 'scan' in result.stdout.lower()
    assert 'retained' in result.stdout.lower()
    assert str(root) not in result.stdout


@pytest.mark.skipif(POWERSHELL is None or sys.platform != 'win32', reason='Windows PowerShell is required')
def test_nightly_missing_scanner_stops_before_replacing_the_existing_index(tmp_path):
    root = _nightly_project(tmp_path, missing_scanner=True)
    result = _run_nightly(tmp_path, root)
    assert result.returncode == 1
    assert _nightly_calls(root) == []
    assert (root / 'data' / 'chart_analogue' / 'prepared.json').read_text() == 'existing-index'
    assert str(root) not in result.stdout


@pytest.mark.skipif(POWERSHELL is None or sys.platform != 'win32', reason='Windows PowerShell is required')
@pytest.mark.parametrize('failed_stage,expected_calls,expected_index', [
    ('refresh_chart_analogue_prices.py', ['refresh_chart_analogue_prices.py'], 'existing-index'),
    ('build_chart_analogue_index.py', ['refresh_chart_analogue_prices.py', 'build_chart_analogue_index.py'], 'existing-index'),
    ('evaluate_chart_analogue_shadow.py', ['refresh_chart_analogue_prices.py', 'build_chart_analogue_index.py', 'evaluate_chart_analogue_shadow.py'], 'new-prepared-index'),
])
def test_nightly_prior_stage_failure_prevents_the_scan(tmp_path, failed_stage, expected_calls, expected_index):
    root = _nightly_project(tmp_path, failed_stage=failed_stage)
    result = _run_nightly(tmp_path, root)
    assert result.returncode == 1
    assert [call['stage'] for call in _nightly_calls(root)] == expected_calls
    assert (root / 'data' / 'chart_analogue' / 'prepared.json').read_text() == expected_index
