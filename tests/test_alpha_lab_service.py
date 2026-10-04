import json
from pathlib import Path

import pytest

from app.services.mirofish.alpha_lab import service, store


def core():
    metrics = dict(net_total_return=.02, max_drawdown=-.03)
    phase = dict(metrics=metrics, closed_net_returns=[.01, -.005], closed_trades=2, open_trades=0)
    return dict(champion=None, strategies=[dict(strategy_id='momentum', name='Momentum', validation=phase,
             test=phase, stress=dict(test=phase), calibration=dict(qualified=False, held_reasons=['minimum_samples']))],
        candidates=[dict(symbol='005930', name='삼성전자', strategy_id='momentum', score=1., last_close=100.,
            plan=dict(entry_price=100., stop_price=96., target_price=108., loss_fraction=.04),
            risk=dict(weight=.1, p=.6, raw_fraction=2., held_reasons=[]), setup_active=True, reasons=[])],
        diagnostics=dict(held_reasons=['no_validation_qualified_champion']),
        protocol=dict(periods=dict(train=dict(end='2024-01-01'), validation=dict(end='2025-01-01'),
                                  test=dict(start='2025-02-01')), configuration=dict(policy=dict(horizon=10))))


def inputs():
    return dict(status='ready', reasons=[], latest_session='2026-10-02', input_fingerprint='a'*64,
        prices_by_symbol={'005930': []}, names={'005930': '삼성전자'},
        universe=dict(ranked_count=100, quality_count=52, inspected_count=52, scope_date='2026-10-01'),
        provenance=dict(price_basis='provider_reported_unverified', price_adjustment_verified=False,
                        historical_vintage_verified=False, point_in_time_universe_verified=False,
                        current_cohort_bias=True, analysis_ready=False), warnings=['current_cohort_survivorship_bias'])


def test_adapter_keeps_research_watchlist_without_champion_as_zero_weight():
    report = service.normalize_report(core(), inputs(), now='2026-10-04T03:00:00Z')
    assert report['candidates'][0]['risk']['weight'] == 0.
    assert report['champion']['strategy_id'] is None
    assert report['champion']['selection_basis'] == 'validation_only'
    assert report['strategies'][0]['test']['net_total_return'] == .02
    assert report['strategies'][0]['validation']['trades'] == 2
    assert report['strategies'][0]['validation']['mean_net_return'] == .0025
    assert report['mode'] == 'research'
    assert report['approval']['approved_exposure'] == 0.
    assert report['provenance']['analysis_ready'] is False
    json.dumps(report, allow_nan=False)


def test_negative_holdout_rejects_selected_strategy_without_hindsight_reselection():
    result = core(); result['champion'] = dict(strategy_id='momentum')
    result['strategies'][0]['calibration']['qualified'] = True
    result['strategies'][0]['test'] = dict(metrics=dict(net_total_return=-.05, max_drawdown=-.1),
                                          closed_net_returns=[.01, -.02]*20)
    data = inputs(); data['provenance']['analysis_ready'] = True
    report = service.normalize_report(result, data)
    assert report['champion']['strategy_id'] == 'momentum'
    assert report['champion']['status'] == 'held'
    assert report['candidates'][0]['risk']['weight'] == 0.
    assert 'heldout_test_net_loss' in report['champion']['reasons']
    assert report['strategies'][0]['qualified'] is False


def test_failed_scan_preserves_saved_result_and_get_never_runs_engine(tmp_path, monkeypatch):
    report = service.normalize_report(core(), inputs(), now='2026-10-04T03:00:00Z')
    store.publish(tmp_path, report)
    def unavailable(*_args, **_kwargs):
        raise ValueError('sensitive C:/private/.env details')
    monkeypatch.setattr(service, 'resolve_inputs', unavailable)
    status = service.scan_once(tmp_path)
    assert status['state'] == 'failed'
    assert status['report'] == report
    assert 'private' not in json.dumps(status)
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    assert service.read_status()['report'] == report


def test_scan_uses_latest_observed_session_not_weekend_today(tmp_path, monkeypatch):
    observed = {}
    monkeypatch.setattr(service, 'resolve_inputs', lambda _root: (Path('p'), Path('m'), Path('u')))
    monkeypatch.setattr(service, 'load_inputs', lambda *_args: inputs())
    def run(_prices, **kwargs):
        observed['cutoff'] = kwargs['config'].as_of
        return core()
    monkeypatch.setattr(service, 'run_research', run)
    result = service.scan_once(tmp_path)
    assert result['state'] == 'held'
    assert observed['cutoff'] == '2026-10-02'
    assert result['report']['forward']['matured'] == 0


def test_status_envelope_agrees_with_negative_economic_hold(tmp_path, monkeypatch):
    data = inputs(); data['provenance']['analysis_ready'] = True
    evidence = core(); evidence['champion'] = dict(strategy_id='momentum')
    evidence['strategies'][0]['test'] = dict(metrics=dict(net_total_return=-.05, max_drawdown=-.1),
                                            closed_net_returns=[.01, -.02]*20)
    monkeypatch.setattr(service, 'resolve_inputs', lambda _root: (Path('p'), Path('m'), Path('u')))
    monkeypatch.setattr(service, 'load_inputs', lambda *_args: data)
    monkeypatch.setattr(service, 'run_research', lambda *_args, **_kwargs: evidence)
    status = service.scan_once(tmp_path)
    assert status['report']['champion']['status'] == 'held'
    assert status['state'] == 'held'


@pytest.mark.parametrize('path', ['../outside/prices.csv', '/absolute.csv', 'C:/private.csv'])
def test_input_pointer_cannot_escape_canonical_snapshot(tmp_path, path):
    target = tmp_path / 'inputs'; target.mkdir()
    (target / 'current.json').write_text(json.dumps(dict(schema_version=1, prices=path,
        price_manifest='m.json', universe_report='u.json')), encoding='utf-8')
    with pytest.raises(ValueError, match='input_pointer'):
        service.resolve_inputs(tmp_path)


def test_research_change_cannot_overwrite_prior_replay_evidence(tmp_path, monkeypatch):
    from copy import deepcopy
    monkeypatch.setattr(service, 'resolve_inputs', lambda _root: (Path('p'), Path('m'), Path('u')))
    monkeypatch.setattr(service, 'load_inputs', lambda *_args: inputs())
    evidence = core()
    monkeypatch.setattr(service, 'run_research', lambda *_args, **_kwargs: deepcopy(evidence))
    first = service.scan_once(tmp_path)
    evidence['strategies'][0]['test'] = dict(metrics=dict(net_total_return=-.05, max_drawdown=-.1),
                                            closed_net_returns=[.01, -.02]*20)
    second = service.scan_once(tmp_path)
    assert first['report']['experiment_hash'] != second['report']['experiment_hash']
    assert len(list((tmp_path/'runs').glob('*.json'))) == 2
    assert any(json.loads(path.read_text(encoding='utf-8'))['strategies'][0]['test']['metrics']['net_total_return'] == .02
               for path in (tmp_path/'runs').glob('*.json'))


def _context_scan(tmp_path, monkeypatch):
    from copy import deepcopy
    from datetime import date, timedelta
    from tests.test_alpha_lab_opportunities import status, NOW
    data = inputs()
    data['universe']['quality_count'] = data['universe']['inspected_count'] = 8
    data['universe']['scope_date'] = '2026-10-02'
    data['provenance']['captured_at'] = '2026-10-04T01:00:00Z'
    end = date.fromisoformat(data['latest_session'])
    symbols = ['196170', *[f'{index:06d}' for index in range(7)]]
    data['prices_by_symbol'] = {symbol: [dict(symbol=symbol,
        date=(end-timedelta(days=60-index)).isoformat(), open=100., high=101., low=99.,
        close=100., volume=1000.+rank) for index in range(61)] for rank, symbol in enumerate(symbols)}
    data['names'] = {symbol: symbol for symbol in symbols}
    scan = deepcopy(status()['report']['opportunity_scan'])
    scan['candidates'] = deepcopy(status()['report']['buy_candidates'])
    scan['inspected_count'] = 8
    scan['audit'] = {'private_trade_records': []}
    normalize = service.normalize_report
    monkeypatch.setattr(service, 'normalize_report', lambda core, data: normalize(core, data, now=NOW))
    monkeypatch.setattr(service, 'resolve_inputs', lambda _: ('p', 'm', 'u'))
    monkeypatch.setattr(service, 'load_inputs', lambda *_: data)
    monkeypatch.setattr(service, 'run_research', lambda *_, **__: core())
    monkeypatch.setattr(service, 'discover_opportunities', lambda *_, **__: deepcopy(scan))
    return data, scan


def test_selected_context_is_bound_audited_and_does_not_change_selection_or_kelly(tmp_path, monkeypatch):
    data, scan = _context_scan(tmp_path, monkeypatch)
    result = service.scan_once(tmp_path)
    assert result['state'] == 'held'
    report = result['report']; selected = report['buy_candidates'][0]
    assert selected['analyst_context']['status'] == 'ready'
    assert selected['analyst_context']['cohort_count'] == 8
    assert selected['analyst_context']['input_fingerprint'] == data['input_fingerprint']
    assert selected['analyst_context']['as_of'] == selected['quote_session']
    assert selected['entry_guard']['max_entry_price'] == 102.
    assert selected['entry_guard']['backtest_applied'] is False
    assert {key: selected[key] for key in scan['candidates'][0]} == scan['candidates'][0]
    assert report['approval']['approved_exposure'] == 0 and report['approval']['live_orders'] is False
    discovery_path, = (tmp_path/'opportunities'/'runs').glob('*.json')
    assert store._read(discovery_path) == scan
    assert report['opportunity_scan']['audit_hash'] == store._hash(scan)
    context_path, = (tmp_path/'opportunities'/'context-runs').glob('*.json')
    audit = store._read(context_path)
    assert len(audit['contexts']) == 8
    assert audit['input_fingerprint'] == report['input_fingerprint']
    assert audit['opportunity_audit_hash'] == store._hash(scan)
    assert audit['contexts']['196170'] == selected['analyst_context']
    assert store._hash(audit) == report['opportunity_scan']['analyst_context_audit_hash']
    frozen = store.read_journal(tmp_path/'opportunities')['decisions'][0]['candidates'][0]
    assert frozen['analyst_context'] == selected['analyst_context']
    assert frozen['entry_guard'] == selected['entry_guard']
    assert frozen['proposal']['action'] == 'buy'


def test_context_get_is_saved_pure_and_repeated_scan_preserves_both_first_decisions(tmp_path, monkeypatch):
    data, _ = _context_scan(tmp_path, monkeypatch)
    first = service.scan_once(tmp_path)
    hashes = [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]
    second = service.scan_once(tmp_path)
    assert first['report']['buy_candidates'] == second['report']['buy_candidates']
    assert hashes == [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]
    assert len(list((tmp_path/'opportunities'/'context-runs').glob('*.json'))) == 1
    before = {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    def forbidden(*_, **__):
        pytest.fail('GET must not compute or write research')
    monkeypatch.setattr(service, 'ROOT', tmp_path)
    monkeypatch.setattr(service, 'run_research', forbidden)
    monkeypatch.setattr(service, 'discover_opportunities', forbidden)
    monkeypatch.setattr(service, 'build_analyst_context', forbidden)
    from app.services.mirofish.alpha_lab.proposals import present_status
    present_status(service.read_status(), now='2026-10-04T07:00:00Z')
    assert before == {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}


def test_context_audit_tampering_fails_before_freezing_and_retains_last_report(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    first = service.scan_once(tmp_path)
    frozen = [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]
    path, = (tmp_path/'opportunities'/'context-runs').glob('*.json')
    broken = store._read(path); broken['contexts']['196170']['score'] = 99.
    store._write(path, broken)
    result = service.scan_once(tmp_path)
    assert result['state'] == 'failed'
    assert result['report'] == first['report']
    assert frozen == [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]


def test_new_input_context_is_append_only_without_backfilling_same_day_decisions(tmp_path, monkeypatch):
    data, _ = _context_scan(tmp_path, monkeypatch)
    service.scan_once(tmp_path)
    frozen = [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]
    data['input_fingerprint'] = 'b'*64
    result = service.scan_once(tmp_path)
    assert result['report']['buy_candidates'][0]['analyst_context']['input_fingerprint'] == 'b'*64
    assert len(list((tmp_path/'opportunities'/'context-runs').glob('*.json'))) == 2
    assert frozen == [store.read_journal(root)['decisions'][0]['sha256'] for root in (tmp_path, tmp_path/'opportunities')]


def test_failed_refresh_retains_context_but_has_no_active_buy(tmp_path, monkeypatch):
    _context_scan(tmp_path, monkeypatch)
    service.scan_once(tmp_path)
    (tmp_path/'inputs').mkdir()
    (tmp_path/'inputs'/'last_attempt.json').write_text('{"status":"failed"}', encoding='utf-8')
    result = service.scan_once(tmp_path)
    from app.services.mirofish.alpha_lab.proposals import present_status
    view = present_status(result, now='2026-10-04T07:00:00Z')['report']['buy_candidates'][0]
    assert view['analyst_context']['status'] == 'ready'
    assert view['proposal']['action'] == 'wait'


def test_upgrade_keeps_unannotated_legacy_opportunity_decision_body_and_hash(tmp_path, monkeypatch):
    from copy import deepcopy
    from tests.test_alpha_lab_opportunities import NOW
    from app.services.mirofish.alpha_lab.proposals import present_status
    data, scan = _context_scan(tmp_path, monkeypatch)
    old_report = service.normalize_report(core(), data)
    old_report['buy_candidates'] = deepcopy(scan['candidates'])
    old_report['opportunity_scan'] = {key: deepcopy(value) for key, value in scan.items()
                                      if key not in ('candidates', 'audit')}
    view = present_status(dict(state='held', report=old_report), now=NOW)['report']
    old_report['candidates'] = view['buy_candidates']
    store.observe_and_freeze(tmp_path/'opportunities', old_report, data['prices_by_symbol'], now=NOW)
    original = deepcopy(store.read_journal(tmp_path/'opportunities')['decisions'][0])
    assert 'analyst_context' not in original['candidates'][0]
    assert 'entry_guard' not in original['candidates'][0]
    result = service.scan_once(tmp_path)
    assert result['report']['buy_candidates'][0]['analyst_context']['status'] == 'ready'
    after = store.read_journal(tmp_path/'opportunities')['decisions'][0]
    assert after == original



def test_context_cohort_includes_quality_member_with_no_valid_prices(tmp_path, monkeypatch):
    data, scan = _context_scan(tmp_path, monkeypatch)
    data['names']['999999'] = 'Missing history'
    data['universe']['quality_count'] = 9
    result = service.scan_once(tmp_path)
    report = result['report']; selected = report['buy_candidates'][0]
    assert selected['analyst_context']['status'] == 'ready'
    assert selected['analyst_context']['cohort_count'] == report['universe']['quality_count'] == 9
    assert selected['analyst_context']['comparison_count'] == report['universe']['inspected_count'] == 8
    assert {key: selected[key] for key in scan['candidates'][0]} == scan['candidates'][0]
    path, = (tmp_path/'opportunities'/'context-runs').glob('*.json')
    missing = store._read(path)['contexts']['999999']
    assert missing['status'] == 'unavailable' and missing['score'] is None
    assert missing['reasons'] == ['missing_prices']
