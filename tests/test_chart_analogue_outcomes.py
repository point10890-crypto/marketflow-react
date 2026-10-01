"""Realised labels use knowable complete observations and one price vintage."""
import csv
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.mirofish import chart_analogue


def observed(*args, **kwargs):
    function = getattr(chart_analogue, 'observed_outcomes', None)
    assert callable(function), 'Read-only observed outcome adapter is not implemented'
    return function(*args, **kwargs)


def days(count=45):
    current = date(2026, 9, 21)
    result = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def install(tmp_path, *, count=45, overrides=None, price_basis='unadjusted'):
    sessions = days(count)
    path = tmp_path / 'prices.csv'
    fields = ['ticker', 'date', 'name', 'current_price', 'update_time']
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, day in enumerate(sessions):
            row = {'ticker': '003690', 'date': day.isoformat(), 'name': 'Korean Re',
                   'current_price': 100 + index, 'update_time': f'{day}T08:00:00Z'}
            if overrides:
                row.update(overrides(index, row) or {})
            writer.writerow(row)
    root = tmp_path / 'index'
    chart_analogue.build_index(path, root, price_basis=price_basis)
    return root, path, sessions


def arguments(root, sessions, **updates):
    result = {'symbol': '003690', 'decision_at': '2026-09-21T08:00:00Z',
              'reference_session': '2026-09-21', 'frozen_reference_close': 100,
              'as_of': f'{sessions[-1]}T08:00:00Z', 'index_root': root,
              'expected_source_id': 'local_daily_prices', 'expected_price_basis': 'unadjusted'}
    result.update(updates)
    return result


def test_forecast_anchor_and_post_decision_trade_have_separate_observation_counts(tmp_path):
    root, _, sessions = install(tmp_path)
    result = observed(**arguments(root, sessions))
    assert result['status'] == 'ready'
    assert result['reference'] == {'session': '2026-09-21', 'frozen_close': 100.0, 'evaluated_close': 100.0, 'rebased': False}
    forecasts = result['forecast_horizons']
    trades = result['trade_horizons']
    assert [row['sessions'] for row in forecasts] == [5, 20, 40]
    assert forecasts[0]['entry_date'] == '2026-09-21'
    assert forecasts[0]['exit_date'] == '2026-09-28'
    assert forecasts[0]['gross_return_pct'] == 5.0
    assert trades[0]['entry_date'] == '2026-09-22'
    assert trades[0]['entry_close'] == 101.0
    assert trades[0]['exit_date'] == '2026-09-29'
    assert trades[0]['exit_close'] == 106.0
    assert trades[0]['gross_return_pct'] == pytest.approx(4.950495)
    assert all(row['status'] == 'matured' and row['observed_sessions'] == row['sessions'] for row in forecasts + trades)
    assert all(row['reason'] is None for row in forecasts + trades)
    json.dumps(result, allow_nan=False)


def test_trade_entry_is_strictly_after_korean_decision_date(tmp_path):
    root, _, sessions = install(tmp_path)
    result = observed(**arguments(root, sessions, decision_at='2026-09-21T16:00:00Z', horizons=(5,)))
    trade = result['trade_horizons'][0]
    assert trade['entry_date'] == '2026-09-23'  # UTC September 21 is already KST September 22.
    assert trade['entry_close'] == 102
    assert trade['exit_date'] == '2026-09-30'
    assert trade['gross_return_pct'] == pytest.approx(4.901961)


def test_adjusted_labels_rebase_the_reference_and_never_mix_frozen_price(tmp_path):
    captured = '2026-11-20T08:00:00Z'
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'update_time': captured}, price_basis='provider_adjusted')
    result = observed(**arguments(root, sessions, frozen_reference_close=50, expected_price_basis='provider_adjusted', horizons=(5,)))
    assert result['reference']['rebased'] is True
    assert result['reference']['evaluated_close'] == 100
    assert result['forecast_horizons'][0]['gross_return_pct'] == 5
    assert result['trade_horizons'][0]['gross_return_pct'] == pytest.approx(4.950495)


def test_short_history_is_pending_without_inventing_exit_values(tmp_path):
    root, _, sessions = install(tmp_path, count=4)
    result = observed(**arguments(root, sessions, horizons=(5,)))
    forecast, trade = result['forecast_horizons'][0], result['trade_horizons'][0]
    assert forecast['status'] == trade['status'] == 'pending'
    assert forecast['reason'] == trade['reason'] == 'incomplete_sessions'
    assert forecast['observed_sessions'] == 3
    assert trade['observed_sessions'] == 2
    assert all(row['exit_close'] is None and row['exit_date'] is None and row['gross_return_pct'] is None for row in [forecast, trade])


def test_exact_microsecond_capture_after_cutoff_prevents_maturity(tmp_path):
    def late(index, row):
        return {'update_time': '2026-09-29T08:00:00.900000Z'} if index == 3 else {}
    root, _, sessions = install(tmp_path, count=8, overrides=late)
    result = observed(**arguments(root, sessions, as_of='2026-09-29T08:00:00.100000Z', horizons=(5,)))
    for row in result['forecast_horizons'] + result['trade_horizons']:
        assert row['status'] == 'pending'
        assert row['reason'] == 'capture_after_as_of'
        assert row['gross_return_pct'] is None
        assert datetime.fromisoformat(row['captured_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(result['as_of'].replace('Z', '+00:00'))
    exact = observed(**arguments(root, sessions, as_of='2026-09-29T08:00:00.900000Z', horizons=(5,)))
    assert exact['forecast_horizons'][0]['status'] == 'matured'
    assert exact['trade_horizons'][0]['status'] == 'matured'


def test_today_close_before_korean_session_end_is_pending_even_when_present_in_index(tmp_path):
    root, _, sessions = install(tmp_path, count=8)
    result = observed(**arguments(root, sessions, as_of='2026-09-28T06:29:59Z', horizons=(5,)))
    forecast = result['forecast_horizons'][0]
    assert forecast['status'] == 'pending'
    assert forecast['reason'] == 'close_not_completed'
    assert forecast['observed_sessions'] == 4
    assert forecast['gross_return_pct'] is None


def test_capture_fractionally_before_session_close_is_not_a_completed_label(tmp_path):
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'update_time': '2026-09-24T06:29:59.900000Z'} if index == 3 else {})
    result = observed(**arguments(root, sessions, horizons=(5,)))
    assert all(row['status'] == 'blocked' and row['reason'] == 'invalid_span'
               and row['gross_return_pct'] is None for row in result['forecast_horizons'] + result['trade_horizons'])


@pytest.mark.parametrize('bad', ['nan', '0', '-1'])
def test_invalid_middle_observation_blocks_the_unfiltered_span(tmp_path, bad):
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'current_price': bad} if index == 3 else {})
    result = observed(**arguments(root, sessions, horizons=(5,)))
    assert result['forecast_horizons'][0]['observed_sessions'] == 2
    assert result['trade_horizons'][0]['observed_sessions'] == 1
    assert all(row['status'] == 'blocked' and row['reason'] == 'invalid_span' and row['gross_return_pct'] is None for row in result['forecast_horizons'] + result['trade_horizons'])


def test_invalid_first_post_decision_close_cannot_be_skipped_to_a_later_entry(tmp_path):
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'current_price': 'nan'} if index == 1 else {})
    result = observed(**arguments(root, sessions, horizons=(5,)))
    trade = result['trade_horizons'][0]
    assert trade['status'] == 'blocked' and trade['reason'] == 'invalid_span'
    assert trade['entry_date'] is None and trade['entry_close'] is None


def test_missing_reference_is_explicitly_blocked(tmp_path):
    root, _, sessions = install(tmp_path)
    result = observed(**arguments(root, sessions, reference_session='2026-09-18', horizons=(5,)))
    assert result['reference']['evaluated_close'] is None
    assert all(row['status'] == 'blocked' and row['reason'] == 'reference_missing' for row in result['forecast_horizons'] + result['trade_horizons'])


def test_future_reference_capture_exposes_no_evaluated_price_or_rebase(tmp_path):
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'update_time': '2030-01-01T08:00:00Z'} if index == 0 else {})
    result = observed(**arguments(root, sessions, frozen_reference_close=50, horizons=(5,)))
    assert result['reference']['evaluated_close'] is None and result['reference']['rebased'] is False
    assert all(row['status'] == 'pending' and row['reason'] == 'capture_after_as_of'
               and row['entry_close'] is None and row['exit_close'] is None and row['gross_return_pct'] is None
               for row in result['forecast_horizons'] + result['trade_horizons'])


def test_large_gap_blocks_both_spans_without_compressing_dates(tmp_path):
    def gap(index, row):
        if index >= 3:
            shifted = date.fromisoformat(row['date']) + timedelta(days=28)
            return {'date': shifted.isoformat(), 'update_time': f'{shifted}T08:00:00Z'}
    root, _, sessions = install(tmp_path, overrides=gap)
    result = observed(**arguments(root, sessions, as_of=f'{sessions[-1] + timedelta(days=28)}T08:00:00Z', horizons=(5,)))
    assert all(row['status'] == 'blocked' and row['reason'] == 'invalid_span' for row in result['forecast_horizons'] + result['trade_horizons'])


@pytest.mark.parametrize('decision', ['2026-09-21T08:00:00Z', '2026-10-15T08:00:00Z'])
def test_long_gap_before_entry_cannot_be_replaced_with_a_later_resume(tmp_path, decision):
    def gap(index, row):
        if index >= 1:
            shifted = date.fromisoformat(row['date']) + timedelta(days=28)
            return {'date': shifted.isoformat(), 'update_time': f'{shifted}T08:00:00Z'}
    root, _, sessions = install(tmp_path, count=8, overrides=gap)
    result = observed(**arguments(root, sessions, decision_at=decision,
                                 as_of=f'{sessions[-1] + timedelta(days=28)}T08:00:00Z', horizons=(5,)))
    trade = result['trade_horizons'][0]
    assert trade['status'] == 'blocked' and trade['reason'] == 'invalid_entry_span'
    assert trade['entry_close'] is None and trade['gross_return_pct'] is None


def test_discontinuity_into_entry_is_not_a_valid_trade_label(tmp_path):
    root, _, sessions = install(tmp_path, count=8,
        overrides=lambda index, row: {'current_price': 200 + index} if index >= 1 else {})
    trade = observed(**arguments(root, sessions, horizons=(5,)))['trade_horizons'][0]
    assert trade['status'] == 'blocked' and trade['reason'] == 'invalid_entry_span'
    assert trade['entry_close'] is None and trade['gross_return_pct'] is None


def test_unknown_capture_is_a_barrier_not_a_removed_observation(tmp_path):
    root, _, sessions = install(tmp_path, overrides=lambda index, row: {'update_time': ''} if index == 3 else {})
    result = observed(**arguments(root, sessions, horizons=(5,)))
    assert all(row['status'] == 'blocked' and row['reason'] == 'invalid_span' for row in result['forecast_horizons'] + result['trade_horizons'])


def test_trade_waits_when_no_post_decision_observation_exists(tmp_path):
    root, _, sessions = install(tmp_path, count=1)
    result = observed(**arguments(root, sessions, horizons=(5,)))
    assert result['trade_horizons'][0]['status'] == 'pending'
    assert result['trade_horizons'][0]['reason'] == 'entry_not_observed'
    assert result['trade_horizons'][0]['entry_close'] is None


@pytest.mark.parametrize('expected,reason', [({'expected_source_id': 'wrong_provider'}, 'source_mismatch'), ({'expected_price_basis': 'provider_adjusted'}, 'price_basis_mismatch')])
def test_expected_provider_and_price_basis_are_enforced(tmp_path, expected, reason):
    root, _, sessions = install(tmp_path)
    result = observed(**arguments(root, sessions, horizons=(5,), **expected))
    assert result['status'] == 'ready'
    assert result['reference']['evaluated_close'] is None
    assert all(row['status'] == 'blocked' and row['reason'] == reason and row['gross_return_pct'] is None for row in result['forecast_horizons'] + result['trade_horizons'])


def test_missing_and_corrupt_index_are_read_only_visible_states(tmp_path):
    root = tmp_path / 'missing'
    result = observed(**arguments(root, days(), horizons=(5,)))
    assert result['status'] == 'missing_index'
    assert not root.exists()
    root.mkdir()
    (root / chart_analogue.INDEX_NAME).write_bytes(b'broken')
    assert observed(**arguments(root, days(), horizons=(5,)))['status'] == 'unavailable'


def test_query_needs_only_saved_index_and_never_changes_default_root(tmp_path, monkeypatch):
    root, csv_path, sessions = install(tmp_path)
    default_root = tmp_path / 'default_missing'
    monkeypatch.setattr(chart_analogue, 'INDEX_ROOT', default_root)
    before = (root / chart_analogue.INDEX_NAME).stat().st_mtime_ns
    csv_path.unlink()
    assert observed(**arguments(root, sessions, horizons=(5,)))['forecast_horizons'][0]['status'] == 'matured'
    assert chart_analogue.INDEX_ROOT == default_root
    assert (root / chart_analogue.INDEX_NAME).stat().st_mtime_ns == before
    assert not default_root.exists()


@pytest.mark.parametrize('invalid', [
    {'symbol': '../path'}, {'as_of': '2026-09-21T07:59:59Z'}, {'decision_at': '2026-09-21'},
    {'reference_session': '2026-09-xx'}, {'frozen_reference_close': 0}, {'frozen_reference_close': float('nan')},
    {'horizons': (41,)}, {'horizons': (True,)}, {'horizons': ()},
    {'expected_source_id': '../bad'}, {'expected_price_basis': 'unknown'},
    {'decision_at': None}, {'expected_price_basis': []}, {'frozen_reference_close': 10 ** 1000},
])
def test_strict_arguments_are_rejected_before_index_access(tmp_path, invalid):
    with pytest.raises(ValueError):
        observed(**arguments(tmp_path / 'missing', days(), **invalid))


def test_horizon_iterable_is_consumed_only_to_the_validation_bound(tmp_path):
    def unbounded():
        for index in range(42):
            assert index < 41, 'Unbounded horizons were consumed past the validation budget'
            yield 5
    with pytest.raises(ValueError):
        observed(**arguments(tmp_path / 'missing', days(), horizons=unbounded()))
