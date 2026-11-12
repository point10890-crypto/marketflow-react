import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.forecast_league import bars, baselines, candidates, capsules, ledger

WEEKDAYS = lambda day: day.weekday() < 5  # noqa: E731
ASOF_DATE = '2026-11-12'


def _sessions(count, end=ASOF_DATE):
    days, cursor = [], date.fromisoformat(end)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _series(conn, code, days, *, start=100.0, step=0.0, spike_every=0):
    price = start
    for index, day in enumerate(days):
        high = price * (1.10 if spike_every and index % spike_every == 0 else 1.01)
        bars.put_bar(conn, stock_code=code, session_date=day, basis=bars.BASIS_UNIVERSE, open=price, high=high,
                     low=price * 0.99, close=price, captured_at='t')
        price += step


@pytest.fixture
def at_evening(monkeypatch):
    moment = datetime(2026, 11, 12, 22, 30, tzinfo=timezone.utc)   # 11-13 07:30 KST
    monkeypatch.setattr(ledger, '_now', lambda: moment)


def test_universe_base_rate_counts_decided_paths_only(league_conn):
    days = _sessions(30)
    _series(league_conn, '000001', days, spike_every=1)     # 매일 +10% 고가 → 모든 경로 적중
    _series(league_conn, '000002', days)                    # 한 번도 닿지 않음 → 8일 만기 실패
    result = baselines.universe_base_rate(league_conn, ASOF_DATE)
    assert result['hits'] == 29                              # 000001: 신호일 29개 모두 다음 날 적중
    assert result['n'] == 29 + 22                            # 000002: 8거래일이 남은 신호일만 판정
    assert result['rate'] == pytest.approx(29 / 51)


def test_universe_base_rate_ignores_bars_after_the_asof_date(league_conn):
    days = _sessions(30)
    _series(league_conn, '000002', days)
    before = baselines.universe_base_rate(league_conn, ASOF_DATE)
    _series(league_conn, '000002', ['2026-11-13', '2026-11-16'], spike_every=1)
    assert baselines.universe_base_rate(league_conn, ASOF_DATE) == before


def test_momentum_ranks_use_twenty_session_returns(league_conn):
    days = _sessions(21)
    _series(league_conn, '000001', days, step=1.0)
    _series(league_conn, '000002', days, step=0.0)
    _series(league_conn, '000003', days, step=-1.0)
    _series(league_conn, '000004', days[1:], step=5.0)       # 20개뿐 → 순위 없음
    ranks = baselines.momentum_ranks(league_conn, ASOF_DATE)
    assert ranks == {'000003': 0.0, '000002': 0.5, '000001': 1.0}


def test_baselines_submit_one_forecast_each_per_candidate(league_conn, at_evening):
    days = _sessions(60)
    for code in ('000001', '000002', '000003'):
        _series(league_conn, code, days, step=0.1, spike_every=3)
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001', '000002'],
                                         trading_day=WEEKDAYS)
    assert summary == {'submitted': 4, 'abstained': 0, 'duplicate': 0}
    rows = league_conn.execute('SELECT forecaster_id, stock_code, probability, raw_score, capsule_hash, asof_ts '
                               'FROM forecasts ORDER BY forecaster_id, stock_code').fetchall()
    assert [(row['forecaster_id'], row['stock_code']) for row in rows] == [
        ('baseline_base_rate', '000001'), ('baseline_base_rate', '000002'),
        ('baseline_momentum', '000001'), ('baseline_momentum', '000002')]
    assert {row['asof_ts'] for row in rows} == {'2026-11-12T06:30:00Z'}
    assert rows[0]['probability'] == rows[1]['probability'] and 0.02 <= rows[0]['probability'] <= 0.98
    assert rows[0]['raw_score'] is None and rows[2]['raw_score'] is not None
    capsule = capsules.get_capsule(league_conn, rows[2]['capsule_hash'])
    assert capsule['forecaster'] == 'baseline_momentum' and capsule['derived_from'] == 'fallback'
    kinds = {row['forecaster_id']: (row['kind'], row['probability_source'])
             for row in league_conn.execute('SELECT * FROM forecasters')}
    assert kinds == {'baseline_base_rate': ('baseline', 'native'), 'baseline_momentum': ('baseline', 'derived')}


def test_rerun_does_not_add_forecasts(league_conn, at_evening):
    days = _sessions(60)
    _series(league_conn, '000001', days, spike_every=3)
    _series(league_conn, '000002', days, step=0.1, spike_every=3)
    baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    again = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert again == {'submitted': 0, 'abstained': 0, 'duplicate': 2}
    assert league_conn.execute('SELECT COUNT(*) FROM forecasts').fetchone()[0] == 2


def test_short_history_abstains(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(60), spike_every=3)
    _series(league_conn, '000009', _sessions(5))
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000009'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 1, 'abstained': 1, 'duplicate': 0}
    row = league_conn.execute('SELECT forecaster_id, reason FROM abstentions').fetchone()
    assert tuple(row) == ('baseline_momentum', 'momentum_history_short')


def test_too_few_base_rate_samples_abstains_for_both(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(21))
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 0, 'abstained': 2, 'duplicate': 0}
    assert {row['reason'] for row in league_conn.execute('SELECT reason FROM abstentions')} == {'base_rate_insufficient'}


def test_late_run_records_abstentions_instead_of_forecasts(league_conn, monkeypatch):
    _series(league_conn, '000001', _sessions(60), spike_every=3)
    _series(league_conn, '000002', _sessions(60), step=0.1, spike_every=3)
    monkeypatch.setattr(ledger, '_now', lambda: datetime(2026, 11, 13, 0, 0, tzinfo=timezone.utc))  # 09:00 KST
    summary = baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)
    assert summary == {'submitted': 0, 'abstained': 2, 'duplicate': 0}
    assert {row['reason'] for row in league_conn.execute('SELECT reason FROM abstentions')} == {'late_submission'}


def test_missing_universe_bars_for_the_asof_date_raises(league_conn, at_evening):
    _series(league_conn, '000001', _sessions(60, end='2026-11-11'))
    with pytest.raises(baselines.UniverseBarsMissing):
        baselines.submit_baselines(league_conn, asof_date=ASOF_DATE, stock_codes=['000001'], trading_day=WEEKDAYS)


def test_jongga_candidates_reads_the_daily_result_file(tmp_path):
    path = tmp_path / 'jongga_v2_results_20261112.json'
    path.write_text(json.dumps({'signals': [{'stock_code': '005930'}, {'stock_code': '000660'},
                                            {'stock_code': '005930'}, {'stock_code': 'ABC'}, {}]}), encoding='utf-8')
    assert candidates.jongga_candidates('2026-11-12', data_dir=str(tmp_path)) == ['000660', '005930']
    assert candidates.jongga_candidates('2026-11-13', data_dir=str(tmp_path)) == []
    path.write_text('not json', encoding='utf-8')
    assert candidates.jongga_candidates('2026-11-12', data_dir=str(tmp_path)) == []
