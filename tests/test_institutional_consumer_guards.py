"""New signal scans must not promote retained old rows with a fresh file mtime."""
import csv
from datetime import datetime
import os

import pytest

import signal_tracker
from app.services.mirofish import alpha_scanner


NOW = datetime.fromisoformat('2026-11-08T19:00:00+09:00')


def row(ticker='005930', **changes):
    return dict({'ticker':ticker, 'data_source':'naver_finance_trend_api', 'data_date':'2026-11-06',
                 'scrape_date':'2026-11-08', 'total_days':60, 'foreign_net_buy_5d':100000,
                 'institutional_net_buy_5d':1000, 'supply_demand_index':80}, **changes)


def test_signal_tracker_excludes_49_stale_filter_matches_before_vcp_detection(tmp_path,monkeypatch):
    stale = [row(f'9{i:05d}',data_date='',scrape_date='2026-09-10',data_source='naver_finance_enhanced')
             for i in range(49)]
    with (tmp_path/'all_institutional_trend_data.csv').open('w',encoding='utf-8-sig',newline='') as handle:
        writer = csv.DictWriter(handle,fieldnames=list(row()))
        writer.writeheader(); writer.writerows(stale+[row()])
    stamp = datetime.fromisoformat('2026-11-08T02:10:00+09:00').timestamp()
    os.utime(tmp_path/'all_institutional_trend_data.csv',(stamp,stamp))
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return NOW if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(signal_tracker,'datetime',Clock)
    tracker = signal_tracker.SignalTracker.__new__(signal_tracker.SignalTracker)
    tracker.data_dir = str(tmp_path)
    tracker.strategy_params = {'foreign_min':50000}
    attempted = []
    monkeypatch.setattr(tracker,'detect_vcp_forming',lambda code:(attempted.append(code) or True,{'current_price':100,'contraction_ratio':0.5}))
    monkeypatch.setattr(tracker,'_append_to_log',lambda _rows:None)
    result = tracker.scan_today_signals()
    assert attempted == ['005930']
    assert result['ticker'].tolist() == ['005930']


@pytest.mark.parametrize('cutoff,source,scraped,observed', [
    ('2026-11-06T15:29:00+09:00','2026-11-06','2026-11-06','2026-11-06T15:00:00+09:00'),
    ('2026-11-08T19:00:00+09:00','2026-11-06','2026-11-08','2026-11-08T19:01:00+09:00'),
    ('2026-11-08T19:00:00+09:00','2026-11-06','2026-11-08','2026-11-07T19:00:00+09:00'),
])
def test_signal_tracker_excludes_rows_not_yet_available_at_scan(tmp_path,monkeypatch,cutoff,source,scraped,observed):
    payload = row(data_date=source,scrape_date=scraped)
    path = tmp_path/'all_institutional_trend_data.csv'
    with path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer = csv.DictWriter(handle,fieldnames=list(payload)); writer.writeheader(); writer.writerow(payload)
    stamp = datetime.fromisoformat(observed).timestamp(); os.utime(path,(stamp,stamp))
    moment = datetime.fromisoformat(cutoff)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None): return moment if tz else moment.replace(tzinfo=None)
    monkeypatch.setattr(signal_tracker,'datetime',Clock)
    tracker = signal_tracker.SignalTracker.__new__(signal_tracker.SignalTracker)
    tracker.data_dir = str(tmp_path); tracker.strategy_params = {'foreign_min':50000}
    def must_not_detect(_code): raise AssertionError('unavailable source reached VCP detection')
    monkeypatch.setattr(tracker,'detect_vcp_forming',must_not_detect)
    assert tracker.scan_today_signals().empty


def normalize(payload,cutoff=NOW,mtime='2026-11-08T02:10:00+09:00'):
    return alpha_scanner._normalize_scoring_source(
        'all_institutional_trend_data.csv',payload,artifacts={},cutoff_ceiling=cutoff.isoformat(),
        file_observed_at=mtime)


def test_alpha_excludes_24_old_dual_buy_rows_even_with_new_copy_time():
    stale = [row(f'9{i:05d}',data_date='2026-09-10',scrape_date='2026-09-10') for i in range(24)]
    accepted = [r for payload in stale+[row()] if (r:=normalize(payload)[0]) is not None]
    assert [r['ticker'] for r in accepted] == ['005930']
    assert all(not alpha_scanner._institutional_flow_confirmation(normalize(payload)[0])['passed'] for payload in stale)


def test_weekend_acquisition_uses_actual_envelope_not_scrape_day_market_close():
    before = datetime.fromisoformat('2026-11-08T02:00:00+09:00')
    after = datetime.fromisoformat('2026-11-08T02:20:00+09:00')
    assert normalize(row(),before)[0] is None
    accepted,_ = normalize(row(),after)
    assert accepted is not None
    assert accepted['available_at'] == '2026-11-07T17:10:00+00:00'


@pytest.mark.parametrize('changes', [
    {'data_date':''},{'data_source':'fallback_estimation'},{'total_days':0},
    {'data_date':'2026-11-09'},{'data_date':'2026-11-07'},
    {'scrape_date':'2026-11-09'},{'scrape_date':'2026-11-05'},
    {'foreign_net_buy_5d':'NaN'},{'institutional_net_buy_5d':'1.5'},
])
def test_alpha_fails_closed_for_unverified_row_contract(changes):
    assert normalize(row(**changes))[0] is None


def test_alpha_replay_checks_the_requested_historical_session_not_wall_clock():
    payload = row(data_date='2026-09-03',scrape_date='2026-09-03')
    then = datetime.fromisoformat('2026-09-03T16:00:00+09:00')
    accepted,_ = normalize(payload,then,'2026-09-03T15:40:00+09:00')
    assert accepted is not None
    assert normalize(payload,NOW)[0] is None
    assert normalize(payload,then,'2026-11-08T02:10:00+09:00')[0] is None


@pytest.mark.parametrize('stamp,expected', [('2026-11-09T17:29:00+09:00',True),('2026-11-09T17:30:00+09:00',False)])
def test_new_consumers_follow_the_quality_monitor_session_deadline(stamp,expected):
    from app.services.institutional_freshness import institutional_row_is_available
    cutoff = datetime.fromisoformat(stamp)
    observed = datetime.fromisoformat('2026-11-08T02:10:00+09:00')
    assert institutional_row_is_available(row(),as_of=cutoff,file_observed_at=observed) is expected
    assert (normalize(row(),cutoff)[0] is not None) is expected
