import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1]/'scripts/run_alpha_lab_telegram.py'


def module():
    spec = importlib.util.spec_from_file_location('alpha_lab_telegram_cli', SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.mark.parametrize('mode,expected', [([], 'preview'), (['--send'], True), (['--automatic'], None)])
def test_cli_routes_exact_operation_without_exposing_transport_details(tmp_path, monkeypatch, capsys, mode, expected):
    cli = module()
    monkeypatch.setattr(cli, '_load_env', lambda: None)
    calls = []
    def preview(root):
        calls.append((root, 'preview'))
        return dict(status='preview', decision_id='a'*64, digest='b'*64,
                    message='hidden', message_id=99, receipt={'private': 'hidden'})
    def deliver(root, *, enabled):
        calls.append((root, enabled))
        return dict(status='delivered', decision_id='a'*64, digest='b'*64,
                    message='hidden', message_id=99, recipient='hidden')
    assert cli.main([*mode, '--root', str(tmp_path)], notifications=SimpleNamespace(
        preview_latest=preview, deliver_latest=deliver)) == 0
    assert calls == [(tmp_path, expected)]
    body = json.loads(capsys.readouterr().out)
    assert body['decision_id'] == 'a'*64
    assert set(body) == {'status', 'decision_id', 'digest'}
    assert 'hidden' not in str(body)


@pytest.mark.parametrize('status', ['uncertain', 'action_required', 'invalid_saved_decision', 'not_configured'])
def test_cli_reports_unresolved_delivery_as_failure_without_raw_exception(monkeypatch, capsys, status):
    cli = module()
    monkeypatch.setattr(cli, '_load_env', lambda: None)
    assert cli.main(['--automatic'], notifications=SimpleNamespace(
        deliver_latest=lambda *a, **k: dict(status=status))) == 2
    assert json.loads(capsys.readouterr().out) == {'status': status}


def test_cli_transport_exception_is_bounded(monkeypatch, capsys):
    cli = module()
    monkeypatch.setattr(cli, '_load_env', lambda: None)
    def unavailable(*args, **kwargs):
        raise RuntimeError('private token and recipient must not print')
    assert cli.main(['--automatic'], notifications=SimpleNamespace(deliver_latest=unavailable)) == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {'status': 'notification_unavailable'}
    assert 'private' not in output
