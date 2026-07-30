"""Measurement harness for Goodrich detection quality.

The published TOP 3 is replaced every cycle, so the live service can only ever
report the outcome of a pick that happened to survive. These tests pin the
ledger that keeps every published pick evaluable afterwards, and the
look-ahead-safe forward return / benchmark-excess maths built on top of it.
"""

import json

from app.services.mirofish import goodrich_ledger


def _snapshot(cycle_id, picks, detected_at='2026-07-28T10:15:00+09:00'):
    return {
        'cycle_id': cycle_id,
        'detected_at': detected_at,
        'picks': picks,
    }


def _pick(symbol, name, entry_price, rank=1, **extra):
    return {
        'symbol': symbol,
        'name': name,
        'rank': rank,
        'entry_price': entry_price,
        'current_price': entry_price,
        **extra,
    }


def _rows(pairs):
    return [{'date': date, 'current_price': close} for date, close in pairs]


def test_record_snapshot_keeps_every_published_pick(tmp_path):
    ledger = tmp_path / 'ledger.jsonl'

    written = goodrich_ledger.record_snapshot(
        _snapshot('cycle-1', [
            _pick('005930', '삼성전자', 70000, rank=1),
            _pick('068270', '셀트리온', 180000, rank=2),
        ]),
        ledger_path=str(ledger),
    )

    assert written == 2
    entries = [json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()]
    assert [entry['symbol'] for entry in entries] == ['005930', '068270']
    assert entries[0]['cycle_id'] == 'cycle-1'
    assert entries[0]['entry_price'] == 70000
    assert entries[0]['entry_date'] == '2026-07-28'


def test_record_snapshot_is_idempotent_per_cycle_and_symbol(tmp_path):
    """A replaced pick must stay in the ledger exactly once, not be re-appended."""
    ledger = tmp_path / 'ledger.jsonl'
    snapshot = _snapshot('cycle-1', [_pick('005930', '삼성전자', 70000)])

    goodrich_ledger.record_snapshot(snapshot, ledger_path=str(ledger))
    written_again = goodrich_ledger.record_snapshot(snapshot, ledger_path=str(ledger))

    assert written_again == 0
    assert len(ledger.read_text(encoding='utf-8').splitlines()) == 1


def test_forward_return_ignores_prices_up_to_and_including_entry_date():
    """Look-ahead safety: only strictly-future rows may be used as exits."""
    entry = {'symbol': '005930', 'entry_date': '2026-07-28', 'entry_price': 100.0}
    rows = _rows([
        ('2026-07-27', 90.0),
        ('2026-07-28', 100.0),   # entry day itself is not an exit
        ('2026-07-29', 110.0),   # T+1
        ('2026-07-30', 120.0),   # T+2
    ])

    result = goodrich_ledger.evaluate_pick(entry, rows, None, horizons=(1, 2))

    assert result['horizons']['1']['exit_date'] == '2026-07-29'
    assert result['horizons']['1']['return_pct'] == 10.0
    assert result['horizons']['2']['return_pct'] == 20.0


def test_benchmark_is_aligned_by_date_not_by_row_position():
    """The index may miss a session the stock traded; positional alignment lies."""
    entry = {'symbol': '005930', 'entry_date': '2026-07-28', 'entry_price': 100.0}
    rows = _rows([
        ('2026-07-28', 100.0),
        ('2026-07-29', 108.0),
        ('2026-07-30', 112.0),
    ])
    benchmark = _rows([
        ('2026-07-28', 2000.0),
        # 07-29 missing from the index series on purpose
        ('2026-07-30', 2060.0),
    ])

    result = goodrich_ledger.evaluate_pick(entry, rows, benchmark, horizons=(1, 2))

    t1 = result['horizons']['1']
    assert t1['return_pct'] == 8.0
    assert t1['benchmark_return_pct'] is None, 'no same-date index close -> no excess claim'
    assert t1['excess_return_pct'] is None

    t2 = result['horizons']['2']
    assert t2['return_pct'] == 12.0
    assert t2['benchmark_return_pct'] == 3.0
    assert t2['excess_return_pct'] == 9.0


def test_costs_are_subtracted_from_return_and_excess():
    entry = {'symbol': '005930', 'entry_date': '2026-07-28', 'entry_price': 100.0}
    rows = _rows([('2026-07-28', 100.0), ('2026-07-29', 105.0)])
    benchmark = _rows([('2026-07-28', 1000.0), ('2026-07-29', 1020.0)])

    result = goodrich_ledger.evaluate_pick(
        entry, rows, benchmark, horizons=(1,), round_trip_cost_pct=0.23,
    )

    t1 = result['horizons']['1']
    assert t1['return_pct'] == 5.0
    assert t1['net_return_pct'] == 4.77
    assert t1['benchmark_return_pct'] == 2.0
    assert t1['excess_return_pct'] == 3.0
    assert t1['net_excess_return_pct'] == 2.77
    assert result['round_trip_cost_pct'] == 0.23


def test_pick_without_enough_future_sessions_stays_pending():
    entry = {'symbol': '005930', 'entry_date': '2026-07-28', 'entry_price': 100.0}
    rows = _rows([('2026-07-28', 100.0), ('2026-07-29', 103.0)])

    result = goodrich_ledger.evaluate_pick(entry, rows, None, horizons=(1, 5))

    assert result['status'] == 'partial'
    assert '1' in result['horizons']
    assert '5' not in result['horizons']
    assert result['pending_horizons'] == [5]


def test_pick_with_no_future_sessions_is_pending_not_zero():
    """A brand-new pick must never be counted as a 0% outcome."""
    entry = {'symbol': '005930', 'entry_date': '2026-07-28', 'entry_price': 100.0}

    result = goodrich_ledger.evaluate_pick(entry, _rows([('2026-07-28', 100.0)]), None, horizons=(1,))

    assert result['status'] == 'pending'
    assert result['horizons'] == {}


def test_backfill_ingests_every_cycle_from_a_history_payload(tmp_path):
    ledger = tmp_path / 'ledger.jsonl'
    history = {
        'items': [
            _snapshot('cycle-2', [_pick('035420', 'NAVER', 210000)],
                      detected_at='2026-07-28T10:16:47'),
            _snapshot('cycle-1', [
                _pick('068270', '셀트리온', 177400, rank=1),
                _pick('035720', '카카오', 35650, rank=2),
            ], detected_at='2026-07-28T09:26:26'),
        ],
    }

    written = goodrich_ledger.backfill_from_history(history, ledger_path=str(ledger))

    assert written == 3
    entries = goodrich_ledger.read_ledger(ledger_path=str(ledger))
    assert {entry['cycle_id'] for entry in entries} == {'cycle-1', 'cycle-2'}
    assert goodrich_ledger.backfill_from_history(history, ledger_path=str(ledger)) == 0


def test_summary_reports_win_rate_and_mean_excess_per_horizon():
    evaluations = [
        {'horizons': {'1': {'return_pct': 10.0, 'net_return_pct': 9.77,
                            'excess_return_pct': 8.0, 'net_excess_return_pct': 7.77}}},
        {'horizons': {'1': {'return_pct': -4.0, 'net_return_pct': -4.23,
                            'excess_return_pct': -6.0, 'net_excess_return_pct': -6.23}}},
        {'horizons': {'1': {'return_pct': 2.0, 'net_return_pct': 1.77,
                            'excess_return_pct': None, 'net_excess_return_pct': None}}},
        {'horizons': {}},  # pending pick must not dilute the statistics
    ]

    summary = goodrich_ledger.summarize(evaluations, horizons=(1,))

    horizon = summary['horizons']['1']
    assert horizon['evaluated_count'] == 3
    assert horizon['win_rate_pct'] == 66.67
    assert horizon['mean_return_pct'] == 2.67
    assert horizon['mean_net_return_pct'] == 2.44
    assert horizon['benchmarked_count'] == 2
    assert horizon['mean_excess_return_pct'] == 1.0
    assert horizon['mean_net_excess_return_pct'] == 0.77
    assert summary['pending_count'] == 1
