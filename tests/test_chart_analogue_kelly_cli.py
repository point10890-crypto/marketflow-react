"""Offline CLI never leaks source/provider exceptions or raw evidence."""
import json

import pytest

from scripts import scan_chart_analogue_kelly as cli
from app.services.mirofish import chart_analogue_kelly_store as store


@pytest.mark.parametrize('status,code', [('ready', 0), ('blocked', 2)])
def test_cli_publishes_small_summary_and_exact_options(monkeypatch, capsys, status, code):
    seen = []
    def scan(**kwargs):
        seen.append(kwargs)
        return {'status': status, 'run_id': 'fixture-run', 'as_of': '2026-10-03T01:00:00Z',
                'universe': {}, 'approval': {'status': 'held'}, 'portfolio': {}, 'forward': {},
                'candidates': [{'symbol': '005930', 'target': '삼성전자', 'score': 1.,
                                'research_status': 'watch', 'kelly': {}, 'private_cases': [1, 2]}],
                '_audit': {'not_public': True}}
    monkeypatch.setattr(store, 'run_scan', scan)
    args = ['--root', 'saved', '--universe', 'scope.json', '--index-root', 'prepared', '--as-of', '2026-10-03T01:00:00Z']
    assert cli.main(args) == code
    payload = json.loads(capsys.readouterr().out)
    assert payload['candidates'][0]['target'] == '삼성전자'
    assert '_audit' not in payload
    assert 'private_cases' not in payload['candidates'][0]
    assert seen == [{'root': 'saved', 'universe_path': 'scope.json', 'index_root': 'prepared', 'as_of': '2026-10-03T01:00:00Z'}]


def test_cli_failure_is_generic(monkeypatch, capsys):
    def fail(**kwargs):
        raise ValueError('SECRET_TOKEN:/private/provider')
    monkeypatch.setattr(store, 'run_scan', fail)
    assert cli.main([]) == 1
    payload = capsys.readouterr().out
    assert 'SECRET' not in payload
    assert json.loads(payload) == {'status': 'unavailable', 'error': 'chart_analogue_kelly_scan_failed'}
