"""Deterministic daily volume estimates; fixtures never call market services."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import math

import pytest


SOURCE = 'KIS:FHKST03010100:J:D:1'
CALENDAR = 'KIS:KOSPI:FHKUP03500100'
FETCHED = '2026-11-13T12:00:00Z'
SESSIONS = [(date(2026, 10, 19) + timedelta(days=i)).isoformat()
            for i in range(26) if (date(2026, 10, 19) + timedelta(days=i)).weekday() < 5]


def module():
    try:
        return importlib.import_module('app.services.mirofish.kongming_technical.profile')
    except ModuleNotFoundError:
        pytest.fail('technical profile implementation missing')


def bars(**changes):
    return [dict(symbol='005930', date=day, open=100, high=124, low=100,
                 close=112, volume=240, traded_value=26880, source_flags={}, **changes)
            for day in SESSIONS]


def build(rows=None, sessions=None, **changes):
    args = dict(fetched_at=FETCHED, source=SOURCE, calendar_source=CALENDAR)
    args.update(changes)
    return module().build_profile('005930', '삼성전자', bars() if rows is None else rows,
                                  SESSIONS if sessions is None else sessions, **args)


def test_uniform_overlap_preserves_both_totals_and_completed_close():
    result = build()
    assert result['status'] == 'ready'
    assert result['sessions_required'] == result['sessions_used'] == 20
    assert result['window_start'] == '2026-10-19'
    assert result['window_end'] == result['as_of'] == '2026-11-13'
    assert result['reference_price'] == 112
    assert result['total_volume'] == 4800
    assert result['total_traded_value'] == 537600
    assert len(result['bins']) == 24
    assert result['bins'][0] == dict(index=0, low=100, high=101, volume=200,
                                    volume_pct=pytest.approx(100/24), traded_value=22400)
    assert math.fsum(b['volume'] for b in result['bins']) == pytest.approx(4800)
    assert math.fsum(b['traded_value'] for b in result['bins']) == pytest.approx(537600)
    assert math.fsum(b['volume_pct'] for b in result['bins']) == pytest.approx(100)
    assert result['current_zone']['index'] == 12  # Boundary belongs to right bin.
    assert result['support']['high'] < 112
    assert result['resistance']['low'] > 112
    assert result['source'] == SOURCE and result['calendar_source'] == CALENDAR
    assert result['method'] == 'daily_uniform_range_overlap_v1'
    assert result['price_basis'] == 'KIS_KRX_raw_J_D_1'
    assert any('보유' in text for text in result['limitations'])


def test_partial_overlap_allocates_by_width_not_close_price():
    rows = bars()
    for row in rows:
        row.update(open=102, low=102, high=105, close=103, volume=300, traded_value=30900)
    rows[-1].update(open=100, low=100, high=124, close=112, volume=240, traded_value=26880)
    result = build(rows)
    assert result['bins'][0]['volume'] == 10
    assert result['bins'][2]['volume'] == 1910
    assert result['bins'][3]['volume'] == 1910
    assert result['bins'][4]['volume'] == 1910
    assert result['bins'][5]['volume'] == 10
    assert result['total_volume'] == 5940
    assert result['poc']['index'] == 2  # Lower price wins a deterministic volume tie.


def test_flat_window_is_one_bin_without_fabricated_levels():
    rows = bars()
    for row in rows:
        row.update(open=100, low=100, high=100, close=100, volume=10, traded_value=1000)
    result = build(rows)
    assert result['bins'] == [dict(index=0, low=100, high=100, volume=200,
                                   volume_pct=100, traded_value=20000)]
    assert result['poc'] == result['current_zone'] == result['bins'][0]
    assert result['support'] is None and result['resistance'] is None


def test_sparse_flat_bars_and_empty_price_bins_do_not_invent_support():
    rows = bars()
    for row in rows:
        row.update(open=124, high=124, low=124, close=124, volume=10, traded_value=1240)
    rows[0].update(open=100, high=100, low=100, close=100, volume=0, traded_value=0)
    result = build(rows)
    assert result['status'] == 'ready'
    assert result['total_volume'] == result['bins'][-1]['volume'] == 190
    assert result['support'] is None and result['resistance'] is None
    assert result['current_zone']['index'] == 23


@pytest.mark.parametrize('count', [0, 1, 19])
def test_short_history_is_explicit_and_has_no_derived_levels(count):
    result = build(bars()[:count])
    assert result['status'] == 'insufficient_history'
    assert result['sessions_used'] == count
    assert result['bins'] == []
    for field in ('poc', 'support', 'resistance', 'current_zone', 'reference_price',
                  'total_volume', 'total_traded_value'):
        assert result[field] is None


def test_zero_volume_window_has_no_invented_current_zone():
    rows = bars()
    for row in rows:
        row.update(volume=0, traded_value=0)
    result = build(rows)
    assert result['status'] == 'insufficient_history'
    assert result['reason'] == 'zero_volume_window'
    assert result['sessions_used'] == 20
    assert result['bins'] == [] and result['poc'] is None and result['current_zone'] is None


@pytest.mark.parametrize('flag,value', [('flng_cls_code', '02'), ('prtt_rate', '50.0'),
                                        ('mod_yn', 'Y'), ('revl_issu_reas', '1')])
def test_provider_price_event_withholds_blended_levels(flag, value):
    rows = bars()
    rows[4]['source_flags'] = {flag: value}
    result = build(rows)
    assert result['status'] == 'price_event_review'
    assert result['reason'] == 'provider_price_event_unverified'
    assert result['bins'] == []
    assert all(result[key] is None for key in ('poc', 'support', 'resistance', 'current_zone'))


def test_zero_event_rate_precision_is_neutral_without_certifying_adjustments():
    rows = bars()
    rows[3]['source_flags'] = dict(flng_cls_code='00', prtt_rate='0.000000', mod_yn='N', revl_issu_reas='0')
    result = build(rows)
    assert result['status'] == 'ready'
    assert any('기업행사' in text for text in result['limitations'])


@pytest.mark.parametrize('field,value', [('low', math.nan), ('high', math.inf), ('volume', -1),
                                        ('traded_value', math.inf), ('open', 125), ('close', 99),
                                        ('volume', True), ('close', 0), ('volume', 0.5)])
def test_invalid_ohlcv_is_rejected_with_bounded_code(field, value):
    rows = bars()
    rows[3][field] = value
    with pytest.raises(ValueError, match='daily_ohlcv') as error:
        build(rows)
    assert error.value.code == 'daily_ohlcv'


@pytest.mark.parametrize('change,reason', [
    (lambda rows: rows.append(deepcopy(rows[0])), 'daily_duplicate'),
    (lambda rows: rows[0].update(symbol='000660'), 'daily_identity'),
    (lambda rows: rows[0].update(date='2026-11-16'), 'daily_future_row'),
    (lambda rows: rows[0].update(date='2026-10-20'), 'daily_duplicate'),
    (lambda rows: rows[0].update(date='2026-10-18'), 'daily_session_mismatch'),
])
def test_identity_duplicates_and_wrong_session_rows_are_rejected(change, reason):
    rows = bars()
    change(rows)
    with pytest.raises(ValueError, match=reason):
        build(rows)


def test_fetched_time_cannot_certify_today_before_cutoff():
    with pytest.raises(ValueError, match='daily_session_incomplete'):
        build(fetched_at='2026-11-13T11:29:59Z')
    assert build(fetched_at='2026-11-13T11:30:00Z')['status'] == 'ready'


def test_calendar_requires_exactly_twenty_distinct_actual_dates():
    for sessions in (SESSIONS[:-1], SESSIONS + ['2026-11-16'], SESSIONS[:-1] + [SESSIONS[0]]):
        with pytest.raises(ValueError, match='calendar_invalid'):
            build(sessions=sessions)


def test_fingerprint_is_replayable_across_input_order_and_fetch_times():
    first = build()
    second = build(list(reversed(bars())), fetched_at='2026-11-14T12:00:00Z')
    assert first['fingerprint'] == second['fingerprint']
    changed = bars()
    changed[0]['volume'] += 1
    assert build(changed)['fingerprint'] != first['fingerprint']


def test_uneven_bin_boundaries_and_large_totals_remain_finite_and_conserved():
    rows = bars()
    for i, row in enumerate(rows):
        row.update(low=100+i/10, open=102+i/10, high=120+i/10, close=110+i/10,
                   volume=123456789+i, traded_value=13580246790+i)
    result = build(rows)
    for field, total in [('volume', result['total_volume']), ('traded_value', result['total_traded_value'])]:
        assert math.fsum(row[field] for row in result['bins']) == pytest.approx(total, rel=1e-14)
        assert all(math.isfinite(row[field]) and row[field] >= 0 for row in result['bins'])
