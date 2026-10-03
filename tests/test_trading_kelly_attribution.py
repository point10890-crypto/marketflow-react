import copy
import math

import pytest

from app.services.mirofish.trading_agents.kelly_attribution import (
    binary_kelly, build_kelly_attribution, render_kelly_section,
)


def report_fixture(*, volatility=.02, count=1, exposure=.6):
    metrics = dict(samples=100, win_rate=.8, win_lower=.71, payoff=2.,
                   avg_win=.06, avg_loss=.03, expected_net_return=.042)
    base = .2
    before_scale = base * (.5 if volatility > .03 else 1.)
    final = min(before_scale, exposure / count)
    rows = [dict(symbol=f'{i:06}', name=f'종목 {i}', market='KOSPI',
                 validation=copy.deepcopy(metrics), estimated_kelly=1.,
                 prior_volatility=volatility, base_target_weight=base,
                 target_weight=final, high_volatility_reduction=volatility > .03,
                 new_position=True) for i in range(1, count + 1)]
    return dict(run_id='attribution-test', synthetic=True, paper_only=True, live_orders=False,
        data=dict(status='ready', ranked=[], eligible_symbols=[]),
        quant=dict(qualification_complete=True, candidates=rows, qualification=rows,
                   frozen_at='2024-01-01', as_of='2024-02-01'),
        risk=dict(status='approved', candidate_evidence=rows, kelly_fraction=.5,
                  max_weight=.2, max_exposure=exposure, min_cash=.4, volatility_threshold=.03,
                  portfolio_equity=1_000_000., targets={r['symbol']: final for r in rows}),
        approval=dict(decision='approved'),
        execution=dict(status='executed', nav_after=999_000., fills=[], portfolio=dict(positions={})))


def test_reference_binary_formula_and_long_only_negative_edge():
    assert binary_kelly(.6, 1.) == pytest.approx(.2)
    assert binary_kelly(.4, 1.) == pytest.approx(-.2)
    view = build_kelly_attribution(report_fixture())
    assert view['reference_example']['full_kelly'] == pytest.approx(.2)
    assert view['reference_example']['half_kelly'] == pytest.approx(.1)


@pytest.mark.parametrize('p,b', [(math.nan, 1), (.6, 0), (1.1, 1), (True, 1)])
def test_formula_rejects_invalid_inputs(p, b):
    with pytest.raises(ValueError):
        binary_kelly(p, b)


def test_empirical_allocation_is_not_replaced_by_binary_diagnostic():
    report = report_fixture()
    before = copy.deepcopy(report)
    view = build_kelly_attribution(report)
    row = view['rows'][0]
    assert row['binary_stake_diagnostic'] == pytest.approx(.7)
    assert row['empirical_kelly'] == 1.
    assert row['fractional_kelly'] == .5
    assert row['capped_weight'] == .2
    assert row['final_weight'] == .2
    assert row['planned_amount'] == 200_000.
    assert row['post_cost_target_value'] == 199_800.
    assert view['source_split'] == 'validation'
    assert report == before


def test_high_volatility_halves_after_position_cap():
    row = build_kelly_attribution(report_fixture(volatility=.04))['rows'][0]
    assert row['capped_weight'] == .2
    assert row['volatility_multiplier'] == .5
    assert row['pre_exposure_weight'] == .1
    assert row['final_weight'] == .1
    assert row['planned_amount'] == 100_000.


def test_portfolio_limit_scales_all_targets_before_amounts():
    view = build_kelly_attribution(report_fixture(count=3, exposure=.3))
    assert view['portfolio_scale'] == pytest.approx(.5)
    assert sum(r['final_weight'] for r in view['rows']) == pytest.approx(.3)
    assert all(r['planned_amount'] == pytest.approx(100_000.) for r in view['rows'])


def test_full_cash_policy_retains_consistent_zero_weight_evidence():
    report = report_fixture()
    report['risk']['min_cash'] = 1.
    report['risk']['targets']['000001'] = 0.
    report['risk']['candidate_evidence'][0]['target_weight'] = 0.
    view = build_kelly_attribution(report)
    assert view['status'] == 'ready'
    assert view['portfolio_scale'] == 0.
    assert view['rows'][0]['final_weight'] == 0.
    assert view['approved_exposure'] == 0.
    assert view['decisions'][0]['reason'] == 'zero_risk_weight'
    report['approval']['decision'] = 'held'
    report['execution']['status'] = 'held'
    held = build_kelly_attribution(report)
    assert held['status'] == 'held' and held['rows'][0]['planned_amount'] is None


def test_blocked_real_data_has_unknown_inputs_and_no_allocation():
    report = report_fixture()
    report.update(synthetic=False, data=dict(status='blocked'), quant=dict(qualification_complete=False))
    report['approval']['decision'] = 'held'
    view = build_kelly_attribution(report)
    assert view['status'] == 'pending'
    assert view['rows'] == [] and view['approved_exposure'] is None
    assert '계산 대기' in render_kelly_section(view)
    assert '실제 투자 비중이 아닙니다' in render_kelly_section(view)


@pytest.mark.parametrize('field', ['target_weight', 'base_target_weight', 'estimated_kelly', 'payoff'])
def test_inconsistent_evidence_does_not_display_approved_amounts(field):
    report = report_fixture()
    row = report['risk']['candidate_evidence'][0]
    if field == 'payoff':
        row['validation'][field] = None
    else:
        row[field] = .123
    view = build_kelly_attribution(report)
    assert view['status'] == 'inconsistent'
    assert view['rows'] == [] and view['approved_exposure'] is None


def test_cio_veto_preserves_calculation_but_withholds_approved_amount():
    report = report_fixture()
    report['approval']['decision'] = 'held'
    report['execution']['status'] = 'held'
    view = build_kelly_attribution(report)
    assert view['status'] == 'held'
    assert view['rows'][0]['final_weight'] == .2
    assert view['rows'][0]['planned_amount'] is None
    assert view['rows'][0]['post_cost_target_value'] is None
    assert view['approved_exposure'] is None


def test_duplicate_day_is_not_new_execution_or_invented_post_cost_nav():
    report = report_fixture()
    report['execution'] = dict(status='duplicate_day', fills=[], portfolio=dict(positions={}))
    view = build_kelly_attribution(report)
    assert view['status'] == 'duplicate_day'
    assert view['new_fill_count'] == 0
    assert view['rows'][0]['post_cost_target_value'] is None
    assert '추가 체결 0건' in render_kelly_section(view)
    assert view['approved_exposure'] is None
    report['risk']['max_weight'] = .1
    report['risk']['targets']['000001'] = .1
    report['risk']['candidate_evidence'][0].update(base_target_weight=.1, target_weight=.1)
    changed = build_kelly_attribution(report)
    assert changed['rows'][0]['final_weight'] == .1
    assert '이번 요청의 검토 목표' in render_kelly_section(changed)
    assert '기존 체결 비중을 확인한 값이 아닙니다' in render_kelly_section(changed)


def test_test_outcomes_never_change_attribution_and_html_escapes_identity():
    report = report_fixture()
    view = build_kelly_attribution(report)
    report['quant']['test'] = {'win_rate': .999, 'expected_net_return': 200.}
    modified = build_kelly_attribution(report)
    assert modified['rows'] == view['rows']
    assert modified['report_sha256'] != view['report_sha256']
    report['risk']['candidate_evidence'][0]['name'] = '<script>alert(1)</script>'
    markup = render_kelly_section(build_kelly_attribution(report))
    assert '<script>' not in markup and '&lt;script&gt;' in markup
    assert 'argmax' in markup and '검증 기간' in markup
