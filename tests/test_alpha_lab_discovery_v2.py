"""A recovery detector must earn its labels with the same historical gates."""
from copy import deepcopy
from datetime import date, timedelta

import pytest


def module():
    from app.services.mirofish.alpha_lab import discovery_v2
    return discovery_v2


def bars(count=1320, *, symbol='005930', drift=.001, volume=20_000_000.):
    start = date(2021, 1, 1)
    rows = []
    for index in range(count):
        close = 100. * (1 + drift) ** index
        rows.append(dict(symbol=symbol, date=(start+timedelta(days=index)).isoformat(),
                         open=close*.999, high=close*1.01, low=close*.99,
                         close=close, volume=volume))
    return rows


def cohort(rows=None):
    rows = rows or bars()
    return {'005930': rows, '000660': bars(len(rows), symbol='000660', drift=.0002),
            '035420': bars(len(rows), symbol='035420', drift=0.)}


def execution(rows, index, policy=None):
    if index+1 >= len(rows):
        return None
    entry = rows[index+1]
    trade = dict(symbol=entry['symbol'], signal_date=rows[index]['date'], entry_date=entry['date'],
                 entry_price=entry['open'], status='open', exit_date=None, exit_price=None, net_return=None)
    if index+2 >= len(rows):
        return trade
    exit_price = entry['open']*(1.06 if index//2 % 2 == 0 else .99)
    trade.update(status='closed', exit_date=rows[index+2]['date'], exit_price=exit_price,
                 net_return=exit_price*(1-policy.exit_cost)/(entry['open']*(1+policy.entry_cost))-1)
    return trade


def controlled(monkeypatch):
    from app.services.mirofish.alpha_lab import discovery
    monkeypatch.setattr(discovery, 'simulate_trade', execution)
    return module()


def test_v2_uses_causal_gates_and_preserves_v1_contract(monkeypatch):
    mod = controlled(monkeypatch)
    from app.services.mirofish.alpha_lab import discovery
    prices = cohort(); before = deepcopy(prices)
    legacy = discovery.discover_opportunities(prices)
    result = mod.discover_opportunities_v2(prices, names={'005930': '삼성전자'})
    assert result['policy_version'] == 'quality-setup-opportunity-v2'
    assert result['selection_basis'] == 'causal_recovery_recent_stress_then_confirmation'
    candidate = next(row for row in result['candidates'] if row['symbol'] == '005930')
    recent = candidate['evidence']['recent']
    assert recent['start'] == prices['005930'][-126]['date']
    assert recent['samples'] >= 5
    audited = next(row for row in result['audit'] if row['symbol'] == '005930' and row['selected'])
    assert recent == audited['recent']['summary']
    assert all(trade['entry_date'] >= recent['start'] for trade in audited['recent']['trades'])
    assert candidate['evidence']['independent_validation'] is False
    assert candidate['risk']['weight'] == 0. and 0 < candidate['risk']['research_weight'] <= .05
    assert discovery.discover_opportunities(prices) == legacy
    assert prices == before


def test_continuously_falling_old_mean_reversion_setup_never_activates():
    mod = module(); rows = bars(drift=-.006)
    result = mod.discover_opportunities_v2(cohort(rows))
    target = [row for row in result['audit'] if row['symbol'] == '005930']
    assert target and all(not row['setup_active'] for row in target)
    assert 'close_not_above_sma60' in next(row for row in target if row['strategy_id'] == 'mean_reversion')['reasons']


def recovery_rows(*, confirmed=True):
    rows = bars()
    values = [139., 135., 133., 131., 129., 132. if confirmed else 128.]
    for row, close in zip(rows[-6:], values):
        row.update(open=close*.999, high=close*1.01, low=close*.99, close=close)
    # A long, rising baseline keeps recovery above both long averages.
    for index, row in enumerate(rows[-61:-6]):
        close = 100.+index*.6
        row.update(open=close*.999, high=close*1.005, low=close*.995, close=close)
    rows[-1]['open'] = 130. if confirmed else 129.
    rows[-1]['high'] = max(rows[-1]['high'], rows[-1]['open'])
    rows[-1]['low'] = min(rows[-1]['low'], rows[-1]['open'])
    return rows


def test_mean_reversion_requires_confirmed_recovery_over_previous_high_and_open():
    mod = module()
    for confirmed in (False, True):
        prices = cohort(recovery_rows(confirmed=confirmed))
        # Comparable slower and flat series make target relative strength positive.
        prices['000660'] = bars(symbol='000660', drift=0.)
        result = mod.discover_opportunities_v2(prices)
        audit = next(row for row in result['audit'] if row['symbol'] == '005930' and row['strategy_id'] == 'mean_reversion')
        assert audit['setup_active'] is confirmed
        if not confirmed:
            assert 'recovery_confirmation_missing' in audit['reasons']


@pytest.mark.parametrize('mutation,reason', [
    ('relative_strength', 'relative_strength_not_positive'),
    ('low_value', 'insufficient_average_traded_value'),
    ('missing_session', 'sparse_factor_window'),
])
def test_quality_gate_excludes_weak_illiquid_and_sparse_setups(mutation, reason):
    mod = module(); prices = cohort()
    if mutation == 'relative_strength':
        prices['000660'] = bars(symbol='000660', drift=.002)
        prices['035420'] = bars(symbol='035420', drift=.003)
    elif mutation == 'low_value':
        for row in prices['005930']:
            row['volume'] = 1.
    else:
        del prices['005930'][-15]
    result = mod.discover_opportunities_v2(prices)
    assert not any(row['symbol'] == '005930' for row in result['candidates'])
    assert any(reason in row['reasons'] for row in result['audit'] if row['symbol'] == '005930')


def test_positive_annual_confirmation_cannot_hide_losing_recent_tail(monkeypatch):
    mod = controlled(monkeypatch); prices = cohort(); recent_start = prices['005930'][-126]['date']
    from app.services.mirofish.alpha_lab import discovery
    def deteriorating(rows, index, policy=None):
        trade = execution(rows, index, policy)
        if trade and trade['status'] == 'closed':
            multiplier = .99 if trade['entry_date'] >= recent_start else (1.10 if index//2 % 2 == 0 else .99)
            trade['exit_price'] = trade['entry_price']*multiplier
            trade['net_return'] = trade['exit_price']*(1-policy.exit_cost)/(trade['entry_price']*(1+policy.entry_cost))-1
        return trade
    monkeypatch.setattr(discovery, 'simulate_trade', deteriorating)
    result = mod.discover_opportunities_v2(prices)
    target = next(row for row in result['audit'] if row['symbol'] == '005930' and row['selected'])
    assert target['confirmation']['summary']['mean_net_return'] > 0
    assert target['confirmation']['summary']['stress_compounded_trade_return'] > 0
    assert target['recent']['summary']['mean_net_return'] < 0
    assert 'recent_nonpositive_mean_net_return' in target['reasons']
    assert not any(row['symbol'] == '005930' for row in result['candidates'])


def test_historical_fills_use_the_identical_prefix_gate_instead_of_v1_labels(monkeypatch):
    mod = controlled(monkeypatch); prices = cohort(); rows = prices['005930']
    # This interval is far too illiquid at its own signal time; today's liquid
    # setup must not inherit trades from the old permissive policy.
    for row in rows[300:500]:
        row['volume'] = 1.
    from app.services.mirofish.alpha_lab import discovery
    old = discovery.discover_opportunities(prices)
    result = mod.discover_opportunities_v2(prices)
    audit = next(row for row in result['audit'] if row['symbol'] == '005930' and row['selected'])
    old_audit = next(row for row in old['audit'] if row['symbol'] == '005930' and row['selected'])
    prohibited = {row['date'] for row in rows[320:500]}
    assert any(t['signal_date'] in prohibited for t in old_audit['calibration']['trades'])
    assert not any(t['signal_date'] in prohibited for t in audit['calibration']['trades'])
    for phase in ('calibration', 'confirmation'):
        for trade in audit[phase]['trades']:
            assert trade['stress_net_return'] == pytest.approx(trade['exit_price']*(1-.006)/(trade['entry_price']*(1+.002))-1)


def test_future_peer_or_target_bar_mutation_cannot_change_any_v2_evidence(monkeypatch):
    mod = controlled(monkeypatch); prices = cohort(); cutoff = prices['005930'][-1]['date']
    expected = mod.discover_opportunities_v2(prices, as_of=cutoff)
    for symbol, rows in prices.items():
        rows.append(dict(symbol=symbol, date=(date.fromisoformat(cutoff)+timedelta(days=1)).isoformat(),
                         open=-1., close=float('nan'), volume=-1.))
    assert mod.discover_opportunities_v2(prices, as_of=cutoff) == expected


def test_recent_evidence_is_not_a_fresh_flat_restart_with_overlapping_labels(monkeypatch):
    mod = controlled(monkeypatch); result = mod.discover_opportunities_v2(cohort())
    audit = next(row for row in result['audit'] if row['symbol'] == '005930' and row['selected'])
    recent = audit['recent']; start = recent['summary']['start']
    assert recent['trades'] == [row for row in audit['confirmation']['trades'] if row['entry_date'] >= start]


def test_real_execution_is_prefix_gated_and_uses_actual_next_open_fills():
    mod = module(); prices = cohort(); rows = prices['005930']
    result = mod.discover_opportunities_v2(prices)
    audit = next(row for row in result['audit'] if row['symbol'] == '005930' and row['strategy_id'] == 'momentum')
    trades = audit['calibration']['trades']
    assert trades  # Real execution creates labels even if a later economic gate holds the stock.
    indices = {row['date']: index for index, row in enumerate(rows)}
    calendar = [row['date'] for row in rows]
    gate = mod._CausalSetupGate(prices, calendar, {day: index for index, day in enumerate(calendar)})
    from app.services.mirofish.alpha_lab.features import features_at
    for trade in trades:
        at = indices[trade['signal_date']]
        assert gate(rows, at, 'momentum', features_at(rows, at))
        assert trade['entry_price'] == rows[at+1]['open']
        assert trade['entry_date'] == rows[at+1]['date']
        assert trade['holding_sessions'] <= 10
        assert trade['net_return'] == pytest.approx(trade['exit_price']*(1-.003)/(trade['entry_price']*(1+.001))-1)
    assert all(left['exit_date'] < right['entry_date'] for left, right in zip(trades, trades[1:]))


def test_four_recent_completed_winners_are_insufficient_even_when_all_returns_positive():
    mod = module()
    trades = [dict(net_return=.02, stress_net_return=.01, exit_date=f'2025-01-{index+2:02d}') for index in range(4)]
    summary = mod.v1._summarize(trades, '2025-01-01', '2025-01-06')
    assert mod._recent_reasons(summary) == ['recent_insufficient_completed_outcomes']


@pytest.mark.parametrize('value', [True, 0, 101, 1.5])
def test_candidate_limit_keeps_the_bounded_original_contract(value):
    with pytest.raises(ValueError, match='candidate_limit'):
        module().discover_opportunities_v2({}, candidate_limit=value)
