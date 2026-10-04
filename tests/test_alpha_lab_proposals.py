"""Manual opinions use current evidence without changing automated approval."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 10, 4, 3, tzinfo=timezone.utc)
PROPOSAL_KEYS = {'action', 'label', 'reason', 'next_step', 'proposed_weight', 'input_session',
                 'derived_at', 'valid_until', 'plan_basis', 'order_allowed'}
SUMMARY_KEYS = {'action', 'headline', 'reason', 'buy_count', 'wait_count', 'avoid_count', 'policy_version'}


def present(status, now=NOW):
    from app.services.mirofish.alpha_lab.proposals import present_status
    return present_status(status, now=now)


def evidence():
    candidate = dict(symbol='005930', name='삼성전자', strategy_id='momentum', score=1., last_close=100.,
        quote_session='2026-10-02', setup_active=True,
        plan=dict(entry_price=100., stop_price=96., target_price=108., loss_fraction=.04),
        risk=dict(weight=0., research_weight=.1, p=.6, status='held', reasons=['source_verification_required']),
        reasons=['source_verification_required'])
    strategy = dict(strategy_id='momentum', qualified=True,
        validation=dict(trades=40, mean_net_return=.01), test=dict(trades=40, net_total_return=.05),
        stress=dict(trades=40, net_total_return=.02))
    report = dict(schema_version=1, mode='research', decision_at='2026-10-04T02:00:00Z',
        latest_session='2026-10-02', universe=dict(scope_date='2026-10-02'),
        provenance=dict(captured_at='2026-10-04T01:00:00Z', analysis_ready=False,
                        historical_vintage_verified=False, point_in_time_universe_verified=False),
        champion=dict(strategy_id='momentum', selection_basis='validation_only', status='held', reasons=['historical_vintage_unverified']),
        approval=dict(status='held', approved_exposure=0., live_orders=False),
        candidates=[candidate], strategies=[strategy], warnings=['corporate_action_adjustment_unverified'])
    return dict(schema_version=1, state='held', report=report, error=None)


def opinion(status):
    return present(status)['report']['candidates'][0]['proposal']


def test_positive_manual_proposal_is_additive_and_keeps_automated_gates_unchanged():
    status = evidence(); before = deepcopy(status)
    out = present(status)
    candidate = out['report']['candidates'][0]
    assert candidate['proposal']['action'] == 'buy'
    assert candidate['proposal']['label'] == '매수 제안'
    assert candidate['proposal']['proposed_weight'] == .1
    assert candidate['proposal']['order_allowed'] is False
    assert candidate['proposal']['plan_basis'] == 'last_closed_price_next_open_reference'
    assert candidate['risk'] == before['report']['candidates'][0]['risk']
    assert candidate['risk']['weight'] == 0.
    assert out['report']['approval'] == before['report']['approval']
    assert out['report']['provenance'] == before['report']['provenance']
    assert status == before
    assert set(candidate['proposal']) == PROPOSAL_KEYS
    assert set(out['report']['proposal_summary']) == SUMMARY_KEYS


@pytest.mark.parametrize('phase', ['test', 'stress'])
def test_negative_matching_strategy_is_avoid_without_champion_or_legacy_quote(phase):
    status = evidence()
    status['report']['champion']['strategy_id'] = None
    status['report']['candidates'][0].pop('quote_session')
    status['report']['strategies'][0][phase]['net_total_return'] = -.01
    proposal = opinion(status)
    assert proposal['action'] == 'avoid'
    assert proposal['proposed_weight'] == 0
    assert '신규 매수' in proposal['reason']
    assert '매도 지시는 아닙니다' in proposal['next_step']
    assert present(status)['report']['proposal_summary']['headline'] == '오늘 제안: 신규 매수하지 않음'


def test_avoid_reason_formats_only_matching_strategy_realized_net_return_metrics():
    status = evidence(); strategy = status['report']['strategies'][0]
    strategy['test']['net_total_return'] = -.055
    strategy['stress']['net_total_return'] = -.067
    status['report']['strategies'].append(dict(strategy_id='other', test=dict(net_total_return=-.99)))
    proposal = opinion(status)
    assert proposal['reason'] == '전략 테스트 -5.5%, 비용 2배 -6.7%: 이 종목의 신규 매수를 제외합니다.'
    assert proposal['next_step'] == '다음 스캔에서 신규 매수 근거를 다시 확인하세요. 매도 지시는 아닙니다.'
    assert proposal['action'] == 'avoid' and proposal['proposed_weight'] == 0.


@pytest.mark.parametrize('missing_metric', [None, True, float('nan'), float('inf')])
def test_avoid_reason_never_invents_missing_or_nonfinite_return_metrics(missing_metric):
    status = evidence(); strategy = status['report']['strategies'][0]
    strategy['test']['net_total_return'] = -.055
    strategy['stress']['net_total_return'] = missing_metric
    assert opinion(status)['reason'] == '전략 테스트 -5.5%: 이 종목의 신규 매수를 제외합니다.'
    strategy['test'].pop('net_total_return')
    strategy['stress']['net_total_return'] = -.067
    assert opinion(status)['reason'] == '비용 2배 -6.7%: 이 종목의 신규 매수를 제외합니다.'


@pytest.mark.parametrize('phase', ['test', 'stress'])
def test_zero_economics_is_wait_not_buy(phase):
    status = evidence(); status['report']['strategies'][0][phase]['net_total_return'] = 0.
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('state', ['running', 'failed', 'missing', 'error', 'done', 'unknown'])
def test_non_operational_state_overrides_retained_buy_or_negative_opinion(state):
    status = evidence(); status['state'] = state
    status['report']['candidates'][0]['proposal'] = dict(action='buy')
    status['report']['strategies'][0]['test']['net_total_return'] = -.1
    proposal = opinion(status)
    assert proposal['action'] == 'wait'
    assert proposal['proposed_weight'] == 0.
    assert proposal['order_allowed'] is False


@pytest.mark.parametrize('field', ['champion', 'decision_at', 'latest_session', 'provenance'])
def test_missing_report_evidence_is_wait(field):
    status = evidence(); status['report'].pop(field)
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('field', ['quote_session', 'plan', 'risk', 'strategy_id', 'setup_active', 'last_close'])
def test_missing_candidate_evidence_is_wait(field):
    status = evidence(); status['report']['candidates'][0].pop(field)
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('value', [True, False, float('nan'), float('inf'), float('-inf'), -.1, 0., .200001, .5, '0.1'])
def test_research_weight_rejects_non_numbers_nonfinite_and_nonpositive(value):
    status = evidence(); status['report']['candidates'][0]['risk']['research_weight'] = value
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('value', [None, True, False, -.2, 0., 1., 1.2, float('nan'), float('inf'), '0.6'])
def test_win_probability_requires_finite_strict_two_sided_interval(value):
    status = evidence(); status['report']['candidates'][0]['risk']['p'] = value
    assert opinion(status)['action'] == 'wait'


def test_missing_probability_and_capture_after_decision_are_wait():
    status = evidence(); status['report']['candidates'][0]['risk'].pop('p')
    assert opinion(status)['action'] == 'wait'
    status = evidence(); status['report']['provenance']['captured_at'] = '2026-10-04T02:30:00Z'
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), '0.1'])
@pytest.mark.parametrize('phase', ['test', 'stress'])
def test_economics_rejects_bool_nonfinite_and_strings(phase, value):
    status = evidence(); status['report']['strategies'][0][phase]['net_total_return'] = value
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('phase', ['test', 'stress', 'validation'])
@pytest.mark.parametrize('trades', [29, True, 30.5])
def test_each_phase_requires_at_least_thirty_completed_integer_outcomes(phase, trades):
    status = evidence(); status['report']['strategies'][0][phase]['trades'] = trades
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('change', ['champion_mismatch', 'candidate_mismatch', 'not_qualified', 'inactive',
                                  'zero_validation', 'missing_scope', 'wrong_entry', 'inverted_stop',
                                  'inverted_target', 'wrong_stop_fraction', 'boolean_plan', 'wrong_selection'])
def test_invalid_selection_validation_entry_or_plan_is_wait(change):
    status = evidence(); report = status['report']; candidate = report['candidates'][0]
    if change == 'champion_mismatch': report['champion']['strategy_id'] = 'other'
    elif change == 'candidate_mismatch': candidate['strategy_id'] = 'other'
    elif change == 'not_qualified': report['strategies'][0]['qualified'] = 1
    elif change == 'inactive': candidate['setup_active'] = 1
    elif change == 'zero_validation': report['strategies'][0]['validation']['mean_net_return'] = 0.
    elif change == 'missing_scope': report['universe'].pop('scope_date')
    elif change == 'wrong_entry': candidate['plan']['entry_price'] = 101.
    elif change == 'inverted_stop': candidate['plan']['stop_price'] = 105.
    elif change == 'inverted_target': candidate['plan']['target_price'] = 95.
    elif change == 'wrong_stop_fraction': candidate['plan']['loss_fraction'] = .01
    elif change == 'boolean_plan': candidate['plan']['target_price'] = True
    elif change == 'wrong_selection': report['champion']['selection_basis'] = 'test_only'
    assert opinion(status)['action'] == 'wait'


@pytest.mark.parametrize('path, value', [
    ('decision_at', '2026-10-04T03:00:01Z'), ('decision_at', '2026-10-04T02:00:00'),
    ('capture', '2026-10-04T03:00:01Z'), ('capture', '2026-10-04T01:00:00'),
    ('capture', '2026-09-26T01:00:00Z'), ('latest', '2026-10-05'), ('latest', '2026-09-26'),
    ('quote', '2026-10-01'), ('quote', '2026-10-05'), ('quote', '2026-09-26'),
    ('scope', '2026-10-05'), ('scope', '2026-09-26'),
])
def test_timestamp_freshness_and_symbol_quote_alignment(path, value):
    status = evidence(); report = status['report']
    if path == 'decision_at': report['decision_at'] = value
    elif path == 'capture': report['provenance']['captured_at'] = value
    elif path == 'latest': report['latest_session'] = value
    elif path == 'quote': report['candidates'][0]['quote_session'] = value
    elif path == 'scope': report['universe']['scope_date'] = value
    assert opinion(status)['action'] == 'wait'


def test_expiry_is_exactly_twenty_four_hours_and_repeated_projection_reevaluates_it():
    status = evidence(); report = status['report']
    assert present(status)['report']['candidates'][0]['proposal']['valid_until'] == '2026-10-05T02:00:00Z'
    before_expiry = datetime(2026, 10, 5, 1, 59, 59, tzinfo=timezone.utc)
    expiry = before_expiry + timedelta(seconds=1)
    assert present(status, before_expiry)['report']['candidates'][0]['proposal']['action'] == 'buy'
    expired = present(status, expiry)['report']['candidates'][0]['proposal']
    assert expired['action'] == 'wait'
    assert report['decision_at'] == '2026-10-04T02:00:00Z'


@pytest.mark.parametrize('reason', ['stale_prices', 'stale_scope', 'future_source_capture',
                                  'input_refresh_failed_previous_snapshot_retained', 'source_refresh_failed'])
def test_current_source_failures_block_positive_manual_proposal(reason):
    status = evidence(); status['report']['champion']['reasons'].append(reason)
    assert opinion(status)['action'] == 'wait'


def test_matching_strategy_losses_do_not_leak_from_other_strategy_or_global_reasons():
    status = evidence()
    status['report']['strategies'].append(dict(strategy_id='other', test=dict(net_total_return=-.4)))
    status['report']['champion']['reasons'].append('heldout_test_net_loss')
    assert opinion(status)['action'] == 'buy'


def test_summary_counts_mixed_and_empty_lists():
    status = evidence(); report = status['report']; report['candidates'][0]['risk']['research_weight'] = .2
    wait = deepcopy(report['candidates'][0]); wait['symbol'] = '000660'; wait.pop('quote_session')
    avoid = deepcopy(wait); avoid['symbol'] = '042700'; avoid['strategy_id'] = 'other'
    report['strategies'].append(dict(strategy_id='other', test=dict(net_total_return=-.1)))
    report['candidates'] += [wait, avoid]
    out = present(status)['report']; summary = out['proposal_summary']
    assert out['candidates'][0]['proposal']['proposed_weight'] == .2
    assert (summary['buy_count'], summary['wait_count'], summary['avoid_count']) == (1, 1, 1)
    assert summary['headline'] == '오늘 제안: 1종목 매수 검토'
    report['candidates'] = report['candidates'][1:]
    assert present(status)['report']['proposal_summary']['headline'] == '오늘 제안: 진입 대기'
    report['candidates'] = []
    assert present(status)['report']['proposal_summary']['action'] == 'wait'


def test_projection_has_no_filesystem_or_journal_mutations(monkeypatch):
    from app.services.mirofish.alpha_lab import store
    def forbidden(*_args, **_kwargs): raise AssertionError('projection must not write or replay')
    monkeypatch.setattr(store, '_write', forbidden)
    monkeypatch.setattr(store, 'observe_and_freeze', forbidden)
    status = evidence(); before = deepcopy(status)
    assert present(status) == present(status)
    assert status == before


def test_account_risk_is_recomputed_from_reference_plan_and_proposed_weight():
    status = evidence(); candidate = status['report']['candidates'][0]
    candidate['risk']['research_weight'] = .2
    candidate['risk']['planned_account_risk'] = .001
    candidate['plan'].update(stop_price=92., loss_fraction=.08)
    assert opinion(status)['action'] == 'wait'
    candidate['plan'].update(stop_price=95., loss_fraction=.05)
    assert opinion(status)['action'] == 'buy'


def test_seven_calendar_day_source_age_is_inclusive_and_eight_days_waits():
    status = evidence(); report = status['report']
    report['latest_session'] = report['universe']['scope_date'] = '2026-09-27'
    report['candidates'][0]['quote_session'] = '2026-09-27'
    report['provenance']['captured_at'] = '2026-09-27T01:00:00Z'
    assert opinion(status)['action'] == 'buy'
    assert present(status, NOW+timedelta(days=1))['report']['candidates'][0]['proposal']['action'] == 'wait'


def test_legacy_route_stub_and_missing_report_are_returned_unchanged_as_copies():
    status = dict(state='done', report=dict(status='ready', candidates=[dict(symbol='042700')]))
    projected = present(status)
    assert projected == status and projected is not status and projected['report'] is not status['report']
    assert present(dict(state='missing', report=None)) == dict(state='missing', report=None)


def test_normalizer_copies_observed_candidate_date_without_inference():
    from app.services.mirofish.alpha_lab import service
    metrics = dict(net_total_return=.02, max_drawdown=-.03)
    phase = dict(metrics=metrics, closed_net_returns=[.01, -.005])
    candidate = evidence()['report']['candidates'][0]
    candidate['risk'] = dict(weight=.1, held_reasons=[])
    candidate['as_of'] = '2026-10-01'
    core = dict(champion=None, strategies=[dict(strategy_id='momentum', name='Momentum', validation=phase,
        test=phase, stress=dict(test=phase), calibration=dict(qualified=False, held_reasons=[]))],
        candidates=[candidate], diagnostics=dict(held_reasons=[]), protocol=dict(periods=dict(
        train=dict(end='2024-01-01'), validation=dict(end='2025-01-01'), test=dict(start='2025-02-01')),
        configuration=dict(policy=dict(horizon=10))))
    inputs = dict(status='ready', reasons=[], latest_session='2026-10-02', warnings=[], input_fingerprint='a'*64,
                  universe={}, provenance=dict(analysis_ready=False))
    report = service.normalize_report(core, inputs, now='2026-10-04T02:00:00Z')
    assert report['candidates'][0]['quote_session'] == '2026-10-01'
    candidate.pop('as_of')
    assert service.normalize_report(core, inputs, now='2026-10-04T02:00:00Z')['candidates'][0]['quote_session'] is None
