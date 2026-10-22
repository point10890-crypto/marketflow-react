"""Manual entry conditions and historical/forward labels share one boundary."""
from copy import deepcopy
from datetime import date, timedelta

import pytest


def api():
    from app.services.mirofish.alpha_lab import candidate_execution
    return candidate_execution


def bars(count=24):
    return [dict(symbol='000001', date=(date(2024, 1, 1)+timedelta(days=at)).isoformat(),
                 open=100., high=101., low=99., close=100., volume=1000.)
            for at in range(count)]


@pytest.mark.parametrize('opening', [102.01, 96., 95., 108., 109.])
def test_open_above_ceiling_or_at_or_beyond_signal_barriers_is_unfilled(opening):
    rows = bars()
    rows[14].update(open=opening, high=max(opening, 101.), low=min(opening, 99.))
    assert api().simulate_candidate_trade(rows, 13) is None


@pytest.mark.parametrize('opening', [96.01, 100., 102.])
def test_valid_open_inside_fixed_signal_band_uses_shared_actual_fill_bracket(opening):
    from app.services.mirofish.alpha_lab.execution import simulate_trade
    rows = bars(); rows[14].update(open=opening, high=max(opening, 101.), low=min(opening, 99.))
    reference = api().build_candidate_reference_plan(rows, 13)
    historical = api().simulate_candidate_trade(rows, 13)
    forward = api().simulate_candidate_trade(rows, 13, reference_plan=reference)
    assert historical == forward == simulate_trade(rows, 13)
    assert historical['entry_price'] == opening
    assert historical['stop_price'] == opening-4.
    assert historical['target_price'] == opening+8.


def test_reference_plan_pins_original_entry_ceiling_in_forward_observation():
    rows = bars(); reference = api().build_candidate_reference_plan(rows, 13)
    rows[14].update(open=101., high=102.)
    assert api().simulate_candidate_trade(rows, 13, reference_plan=reference) is not None
    narrower = dict(reference, entry_upper=100.5)
    assert api().simulate_candidate_trade(rows, 13, reference_plan=narrower) is None


def test_low_atr_plan_with_target_inside_entry_band_is_never_actionable_or_filled():
    rows = bars()
    for row in rows:
        row.update(high=100.2, low=99.8)
    plan = api().build_candidate_reference_plan(rows, 13)
    assert plan['status'] == 'held'
    assert 'target_not_above_entry_upper' in plan['reasons']
    assert api().simulate_candidate_trade(rows, 13) is None


def test_only_explicit_warning_info_flags_are_ignored_and_raw_data_is_untouched():
    clean = bars(); expected = api().simulate_candidate_trade(clean, 13)
    rows = deepcopy(clean)
    for at, row in enumerate(rows):
        row['quality_flags'] = [{'code': 'provider_event', 'severity': 'warning' if at % 2 else 'info'}]
    before = deepcopy(rows)
    assert api().simulate_candidate_trade(rows, 13) == expected
    assert api().build_candidate_reference_plan(rows, 13)['status'] == 'ready'
    assert rows == before
    rows[14]['quality_flags'].append({'code': 'suspended', 'severity': 'nontradable'})
    assert api().simulate_candidate_trade(rows, 13) is None
    rows[14]['quality_flags'] = ['unknown_provider_flag']
    assert api().simulate_candidate_trade(rows, 13) is None


def test_fatal_signal_flag_and_explicit_nontradable_entry_never_fill():
    rows = bars(); rows[13]['quality_flags'] = [{'code': 'bad', 'severity': 'fatal'}]
    assert api().build_candidate_reference_plan(rows, 13)['status'] == 'held'
    assert api().simulate_candidate_trade(rows, 13) is None
    rows = bars(); rows[14]['tradable'] = False
    assert api().simulate_candidate_trade(rows, 13) is None
