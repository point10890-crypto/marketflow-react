"""The explicit recovery command never backfills old research or acquires data."""
from copy import deepcopy

from scripts import run_alpha_lab_evolution as cli
from tests.test_alpha_lab_evolution_store import context


def setup_cli(tmp_path, monkeypatch, *, declared='2026-10-14T10:00:00Z', decision='2026-10-13T11:31:00Z'):
    inputs, report, discovery = context('2026-10-13', decision)
    calls = []
    monkeypatch.setattr(cli.evolution_store, 'initialize', lambda *a, **k: {'declared_at': declared})
    monkeypatch.setattr(cli.store, 'read_status', lambda *a: {'report': report})
    monkeypatch.setattr(cli.service, 'resolve_inputs', lambda *a: ('p', 'm', 'u'))
    monkeypatch.setattr(cli.service, 'load_inputs', lambda *a: inputs)
    monkeypatch.setattr(cli.service, 'discover_opportunities', lambda *a, **k: calls.append('discover') or discovery)
    monkeypatch.setattr(cli.evolution_store, 'refresh', lambda root, i, r, d, **k: calls.append(deepcopy(d)) or {'status': 'ready'})
    return calls, inputs, report, discovery


def test_old_saved_decision_has_no_historical_ranking_or_enrollment(tmp_path, monkeypatch):
    calls, *_ = setup_cli(tmp_path, monkeypatch)
    assert cli.main(['--root', str(tmp_path)]) == 0
    assert calls == [{}]


def test_future_decision_gets_full_pool_only_once(tmp_path, monkeypatch):
    calls, _, _, discovery = setup_cli(tmp_path, monkeypatch, declared='2026-10-12T10:00:00Z')
    assert cli.main(['--root', str(tmp_path)]) == 0
    assert calls == ['discover', discovery]
    path = tmp_path/'evolution'/'cohorts'/'2026-10-13.json'
    path.parent.mkdir(parents=True)
    path.write_text('{}', encoding='utf-8')
    calls.clear()
    assert cli.main(['--root', str(tmp_path)]) == 0
    assert calls == [{}]


def test_missing_source_emits_only_safe_hold_code(tmp_path, monkeypatch, capsys):
    setup_cli(tmp_path, monkeypatch)
    def fail(*args):
        raise ValueError('private key and internal path')
    monkeypatch.setattr(cli.service, 'resolve_inputs', fail)
    assert cli.main(['--root', str(tmp_path)]) == 2
    output = capsys.readouterr().out
    assert 'saved_evolution_inputs_unavailable' in output and 'private' not in output
