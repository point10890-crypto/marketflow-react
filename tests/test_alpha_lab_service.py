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
