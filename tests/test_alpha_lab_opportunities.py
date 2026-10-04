from copy import deepcopy
import pytest

NOW = '2026-10-04T06:00:00Z'


def status():
    def phase(n, start, end):
        return dict(samples=n, wins=n//2+1, losses=n-n//2-1, zeros=0,
                    win_rate=(n//2+1)/n, mean_net_return=.012,
                    stress_mean_net_return=.008, compounded_trade_return=.10,
                    stress_compounded_trade_return=.06, start=start, end=end,
                    last_exit_session=end)
    row = dict(symbol='196170', name='알테오젠', strategy_id='mean_reversion', score=.008,
               last_close=100., quote_session='2026-10-02', setup_active=True, reasons=[],
               plan=dict(entry_price=100., stop_price=96., target_price=108., loss_fraction=.04),
               risk=dict(weight=0., status='held', research_weight=.05, p=16/30,
                         kelly_raw=2., quarter_kelly_fraction=.5, reasons=[]),
               evidence=dict(selection_basis='calibration_stress_mean_then_confirmation', retrospective=True, independent_validation=False, calibration=phase(30, '2021-08-06', '2025-09-17'),
                             confirmation=phase(10, '2025-09-18', '2026-10-02'),
                             stronger_evidence=False))
    report = dict(schema_version=1, mode='research', decision_at='2026-10-04T05:00:00Z',
                  latest_session='2026-10-02', universe=dict(scope_date='2026-10-02'),
                  provenance=dict(captured_at='2026-10-04T04:00:00Z', analysis_ready=False),
                  champion=dict(strategy_id='mean_reversion', selection_basis='validation_only',
                                status='held', reasons=['heldout_test_net_loss']),
                  strategies=[dict(strategy_id='mean_reversion', qualified=False,
                                   test=dict(net_total_return=-.05), stress=dict(net_total_return=-.07))],
                  candidates=[], buy_candidates=[row], warnings=['corporate_action_adjustment_unverified'],
                  approval=dict(status='held', approved_exposure=0., live_orders=False),
                  opportunity_scan=dict(policy_version='quality-setup-opportunity-v1',
                      selection_basis='calibration_stress_mean_then_confirmation', status='ready',
                      latest_session='2026-10-02', horizon_sessions=10, lookback_sessions=1260,
                      calibration_sessions=1008, confirmation_sessions=252, inspected_count=52,
                      eligible_count=1, active_setup_count=44, reasons=[]))
    return dict(schema_version=1, state='held', report=report, error=None)


def present(value=None, now=NOW):
    from app.services.mirofish.alpha_lab.proposals import present_status
    return present_status(status() if value is None else value, now=now)


def proposal(value):
    return present(value)['report']['buy_candidates'][0]['proposal']


def test_independent_positive_setup_has_buy_opinion_despite_losing_old_global_strategy():
    source = status(); original = deepcopy(source)
    result = present(source)
    row = result['report']['buy_candidates'][0]
    assert row['proposal']['action'] == 'buy'
    assert row['proposal']['proposed_weight'] == .05
    assert row['risk']['weight'] == 0 and row['proposal']['order_allowed'] is False
    assert result['report']['approval'] == original['report']['approval']
    assert source == original
    assert result['report']['opportunity_summary']['buy_count'] == 1
    assert result['report']['opportunity_summary']['policy_version'] == 'quality-setup-opportunity-v1'


@pytest.mark.parametrize('phase,field,value', [
    ('calibration', 'samples', 29), ('confirmation', 'samples', 9),
    ('calibration', 'mean_net_return', -.01), ('confirmation', 'stress_mean_net_return', -.01),
    ('calibration', 'compounded_trade_return', 0.), ('confirmation', 'stress_compounded_trade_return', 0.),
    ('calibration', 'wins', True), ('confirmation', 'losses', 0),
    ('calibration', 'last_exit_session', '2025-09-18'),
    ('confirmation', 'last_exit_session', '2026-10-05'),
    ('confirmation', 'mean_net_return', float('nan')),
])
def test_insufficient_negative_or_future_conditional_evidence_never_has_buy(phase, field, value):
    source = status(); source['report']['buy_candidates'][0]['evidence'][phase][field] = value
    assert proposal(source)['action'] == 'wait'


@pytest.mark.parametrize('state', ['running', 'failed', 'missing'])
def test_retained_opportunity_is_not_actionable_while_unfinished_or_failed(state):
    source = status(); source['state'] = state
    assert proposal(source)['action'] == 'wait'


def test_overlapping_periods_wrong_policy_or_failed_source_do_not_bypass_evidence():
    source = status()
    source['report']['buy_candidates'][0]['evidence']['confirmation']['start'] = '2025-09-17'
    assert proposal(source)['action'] == 'wait'
    source = status(); source['report']['opportunity_scan']['policy_version'] = 'unknown'
    assert proposal(source)['action'] == 'wait'
    source = status(); source['report']['warnings'].append('input_refresh_failed_previous_snapshot_retained')
    assert proposal(source)['action'] == 'wait'


def test_unverified_retrospective_source_is_disclosed_and_not_called_certified():
    result = present()
    assert result['report']['buy_candidates'][0]['proposal']['action'] == 'buy'
    assert '탐색' in result['report']['buy_candidates'][0]['proposal']['reason']
    assert result['report']['provenance']['analysis_ready'] is False


@pytest.mark.parametrize('risk', [dict(research_weight=.051), dict(research_weight=0.),
                                dict(kelly_raw=0.), dict(weight=.05)])
def test_nonpositive_kelly_excess_or_approved_weight_cannot_be_a_manual_buy(risk):
    source = status(); source['report']['buy_candidates'][0]['risk'].update(risk)
    assert proposal(source)['action'] == 'wait'


def test_expired_or_wrong_quote_session_downgrades_without_changing_plan():
    source = status()
    assert present(source, now='2026-10-05T05:00:00Z')['report']['buy_candidates'][0]['proposal']['action'] == 'wait'
    source['report']['buy_candidates'][0]['quote_session'] = '2026-10-01'
    assert proposal(source)['action'] == 'wait'


def test_no_positive_candidates_has_empty_discovery_not_legacy_fallback():
    source = status(); source['report']['buy_candidates'] = []
    source['report']['opportunity_scan']['eligible_count'] = 0
    summary = present(source)['report']['opportunity_summary']
    assert summary['buy_count'] == 0 and summary['action'] == 'wait'


def test_scan_publishes_private_discovery_and_separate_immutable_forward_journal(tmp_path, monkeypatch):
    from tests.test_alpha_lab_service import core, inputs
    from app.services.mirofish.alpha_lab import service, store
    data = inputs(); data['provenance']['captured_at'] = '2026-10-04T01:00:00Z'
    normalize = service.normalize_report
    monkeypatch.setattr(service, 'normalize_report', lambda core, data: normalize(core, data, now=NOW))
    scan = status()['report']['opportunity_scan']; scan['candidates'] = status()['report']['buy_candidates']
    scan['audit'] = {'private_trade_records': []}
    monkeypatch.setattr(service, 'resolve_inputs', lambda _: ('p', 'm', 'u'))
    monkeypatch.setattr(service, 'load_inputs', lambda *_: data)
    monkeypatch.setattr(service, 'run_research', lambda *_, **__: core())
    monkeypatch.setattr(service, 'discover_opportunities', lambda *_, **__: deepcopy(scan), raising=False)
    first = service.scan_once(tmp_path)
    assert first['report']['buy_candidates'][0]['symbol'] == '196170'
    assert 'audit' not in first['report']['opportunity_scan']
    assert len(list((tmp_path/'opportunities'/'runs').glob('*.json'))) == 1
    frozen = store.read_journal(tmp_path)['decisions'][0]['sha256']
    discovery_frozen = store.read_journal(tmp_path/'opportunities')['decisions'][0]['sha256']
    second = service.scan_once(tmp_path)
    assert store.read_journal(tmp_path)['decisions'][0]['sha256'] == frozen
    assert store.read_journal(tmp_path/'opportunities')['decisions'][0]['sha256'] == discovery_frozen
    assert second['report']['approval']['approved_exposure'] == 0
