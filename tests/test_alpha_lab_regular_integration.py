"""Newest source contract governs monitoring and delivery, never stale legacy."""
from app.services.mirofish.alpha_lab import candidate_store, candidate_monitor, candidate_alerts
from app.services.mirofish.alpha_lab.desk_selection import directory
from tests.test_alpha_lab_candidate_store import data, desk
from tests.test_alpha_lab_candidate_monitor import Provider, NOW


def seed(root, folder, symbol):
    value, inputs = desk(), data()
    value['source']['regular_session_verified'] = folder == 'candidate-regular-v1'
    value['candidates'][0]['symbol'] = symbol
    inputs['prices_by_symbol'] = {symbol: [dict(row, symbol=symbol) for row in inputs['prices_by_symbol']['005930']]}
    inputs['names'] = {symbol: symbol}
    return candidate_store.publish(root/folder, value, inputs, now=value['generated_at'])


def test_monitor_uses_current_regular_decision_and_isolated_quote_ledger(tmp_path):
    seed(tmp_path, 'candidate-desk', '005930')
    first = seed(tmp_path, 'candidate-regular-v1', '000660')
    provider = Provider()
    result = candidate_monitor.tick(tmp_path, provider, now=NOW)
    assert result['decision_id'] == first['decision_id']
    assert provider.calls[-1] == ('quote', '000660')
    assert (tmp_path/'candidate-regular-v1'/'monitor'/'latest.json').exists()
    assert not (tmp_path/'candidate-desk'/'monitor').exists()
    assert candidate_monitor.read_view(tmp_path, first, now=NOW) == result


def test_failed_new_collection_never_revives_legacy_alerts_or_quotes(tmp_path, monkeypatch):
    seed(tmp_path, 'candidate-desk', '005930')
    candidate_store.set_attempt(tmp_path/'candidate-regular-v1', 'failed', now=NOW.isoformat(), error='source_unavailable')
    assert directory(tmp_path).name == 'candidate-regular-v1'
    provider = Provider()
    assert candidate_monitor.tick(tmp_path, provider, now=NOW)['state'] == 'unavailable'
    assert provider.calls == []
    monkeypatch.setattr(candidate_alerts.telegram_alerts, 'preview_latest', lambda *a, **k: (_ for _ in ()).throw(AssertionError('legacy fallback')))
    assert candidate_alerts.preview_latest(tmp_path, now=NOW.isoformat())['status'] == 'no_candidates'


def test_failed_first_v4_attempt_also_prevents_legacy_delivery(tmp_path, monkeypatch):
    candidate_store.set_attempt(tmp_path/'candidate-desk', 'failed', now=NOW.isoformat(), error='source_unavailable')
    monkeypatch.setattr(candidate_alerts.telegram_alerts, 'preview_latest', lambda *a, **k: (_ for _ in ()).throw(AssertionError('legacy preview')))
    assert candidate_alerts.preview_latest(tmp_path, now=NOW.isoformat())['status'] == 'no_candidates'
    def capture(root, **kwargs):
        assert root == tmp_path/'candidate-desk'
        assert kwargs['prepare'] is candidate_alerts._prepare
        return kwargs['prepare'](root, NOW)[0]
    monkeypatch.setattr(candidate_alerts.telegram_alerts, 'deliver_latest', capture)
    assert candidate_alerts.deliver_latest(tmp_path, now=NOW.isoformat(), enabled=True)['status'] == 'no_candidates'


def test_source_switch_during_quote_fetch_discards_old_plan(tmp_path):
    seed(tmp_path, 'candidate-desk', '005930')
    def switch(_):
        seed(tmp_path, 'candidate-regular-v1', '000660')
    result = candidate_monitor.tick(tmp_path, Provider(change=switch), now=NOW)
    assert result['state'] == 'held'
    assert result['quotes'] == []
    assert not (tmp_path/'candidate-desk'/'monitor'/'latest.json').exists()
