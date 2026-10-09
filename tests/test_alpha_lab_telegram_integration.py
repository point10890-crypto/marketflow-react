"""Notification events follow saved detection commits; reads never send."""
import sys
from types import SimpleNamespace

import pytest

from app.services.mirofish.alpha_lab import service, store
from tests.test_alpha_lab_service import _context_scan


def install_delivery(monkeypatch, callback):
    monkeypatch.setitem(sys.modules, service.__package__+'.telegram_alerts',
                        SimpleNamespace(deliver_latest=callback))


def test_completed_detection_notifies_only_after_result_is_saved(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    observed = []
    def delivery(root):
        saved = store.read_status(root)
        assert saved['state'] == 'held'
        assert saved['report']['opportunity_board']['decision_id']
        observed.append(saved['report']['opportunity_board']['decision_id'])
        return {'status': 'delivered'}
    install_delivery(monkeypatch, delivery)
    result = service.scan_once(tmp_path)
    assert observed == [result['report']['opportunity_board']['decision_id']]


def test_delivery_failure_keeps_completed_research_and_frozen_decision(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    observed = []
    def delivery(root):
        observed.append(root)
        raise OSError('private Telegram response must not appear')
    install_delivery(monkeypatch, delivery)
    result = service.scan_once(tmp_path)
    assert observed == [tmp_path]
    assert result['state'] == 'held'
    assert store.read_status(tmp_path)['report'] == result['report']
    assert len(list((tmp_path/'runs').glob('*.json'))) == 1
    assert 'private Telegram' not in str(result)


def test_failed_research_and_saved_get_do_not_notify(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    result = service.scan_once(tmp_path)
    assert result['state'] == 'held'
    calls = []
    install_delivery(monkeypatch, lambda root: calls.append(root))
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    service.read_status()
    monkeypatch.setattr(service, 'resolve_inputs', lambda root: (_ for _ in ()).throw(ValueError('missing')))
    assert service.scan_once(tmp_path)['state'] == 'failed'
    assert calls == []
