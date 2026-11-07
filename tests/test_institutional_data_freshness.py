import asyncio
from dataclasses import asdict
from datetime import date, datetime
import json

import pandas as pd
import pytest

import all_institutional_trend_data as producer
from engine import collectors


class Today(date):
    @classmethod
    def today(cls):
        return cls(2026, 11, 8)


@pytest.fixture(autouse=True)
def frozen_producer_clock(monkeypatch):
    class Now(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 8, 12)
    monkeypatch.setattr(producer, 'datetime', Now)


@pytest.fixture
def csv_source(tmp_path, monkeypatch):
    (tmp_path / 'engine').mkdir()
    monkeypatch.setattr(collectors, '__file__', str(tmp_path / 'engine/collectors.py'))
    monkeypatch.setattr(collectors, 'date', Today)
    path = tmp_path / 'data/all_institutional_trend_data.csv'
    path.parent.mkdir()
    return path


def supply_row(**changes):
    row = {'ticker': '005930', 'scrape_date': '2026-11-08', 'data_date': '2026-11-06',
           'data_source': 'naver_finance_trend_api', 'total_days': 60,
           'foreign_net_buy_5d': -123, 'institutional_net_buy_5d': 456}
    return dict(row, **changes)


def get(collector):
    return asyncio.run(collector.get_supply_data('005930'))


def test_consumer_preserves_actual_session_and_source(csv_source):
    pd.DataFrame([supply_row()]).to_csv(csv_source, index=False)
    result = get(collectors.KRXCollector())
    assert result.date == date(2026, 11, 6)
    assert result.scrape_date == date(2026, 11, 8)
    assert result.data_source == 'naver_finance_trend_api'
    assert result.foreign_buy_5d == -123 and result.inst_buy_5d == 456
    assert asdict(result)['data_source'] == 'naver_finance_trend_api'


@pytest.mark.parametrize('changes', [
    {'data_date': '2026-09-10'}, {'data_date': '2026-11-09'}, {'data_date': 'invalid'},
    {'data_date': '2026-11-08'}, {'data_source': 'fallback_estimation'},
    {'total_days': 0}, {'foreign_net_buy_5d': 'NaN'}, {'institutional_net_buy_5d': 'bad'},
    {'scrape_date': '2026-11-09'}, {'foreign_net_buy_5d': 1.5},
])
def test_invalid_supply_is_not_scored(csv_source, changes):
    pd.DataFrame([supply_row(**changes)]).to_csv(csv_source, index=False)
    assert get(collectors.KRXCollector()) is None


def test_legacy_scrape_date_is_preserved_and_not_assumed_today(csv_source):
    row = supply_row(scrape_date='2026-11-06', data_source='naver_finance_enhanced')
    row.pop('data_date')
    pd.DataFrame([row]).to_csv(csv_source, index=False)
    assert get(collectors.KRXCollector()).date == date(2026, 11, 6)


def test_replaced_csv_is_reloaded_without_restarting_collector(csv_source):
    pd.DataFrame([supply_row(data_date='2026-09-10')]).to_csv(csv_source, index=False)
    collector = collectors.KRXCollector()
    assert get(collector) is None
    pd.DataFrame([supply_row()]).to_csv(csv_source, index=False)
    assert get(collector).foreign_buy_5d == -123


@pytest.mark.parametrize('today,source,expected', [
    ('2026-11-09', '2026-11-06', True),
    ('2026-11-10', '2026-11-06', False),
    ('2026-12-28', '2026-12-24', True),
    ('2026-05-04', '2026-04-30', True),
])
def test_consumer_accepts_previous_kr_session_across_holidays(csv_source, monkeypatch, today, source, expected):
    class CalendarDate(date):
        @classmethod
        def today(cls): return date.fromisoformat(today)
    monkeypatch.setattr(collectors, 'date', CalendarDate)
    pd.DataFrame([supply_row(scrape_date=today, data_date=source)]).to_csv(csv_source, index=False)
    assert (get(collectors.KRXCollector()) is not None) is expected


def api_rows():
    return [{'itemCode': '005930', 'bizdate': f'202611{day:02d}', 'closePrice': '100,000',
             'accumulatedTradingVolume': '1,000', 'organPureBuyQuant': '-123',
             'foreignerPureBuyQuant': '+456'} for day in (6, 5, 4, 3, 2)]


def test_current_naver_schema_keeps_real_signed_numbers_and_dates(tmp_path):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    rows = analyzer._extract_trend_json(api_rows(), '005930')
    assert rows[0] == {'date': '2026.11.06', 'close_price': 100000, 'volume': 1000,
                       'institutional_net_buy': -123, 'foreign_net_buy': 456}
    result = analyzer._analyze_comprehensive_trend('005930', rows)
    assert result.data_date == '2026-11-06'
    assert result.data_source == 'naver_finance_trend_api'
    assert result.institutional_net_buy_5d == -615


def test_scrape_uses_verified_json_endpoint_without_new_requests(tmp_path, monkeypatch):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    requested = []
    class Response:
        def json(self): return api_rows()
    def request(url):
        requested.append(url)
        return Response()
    monkeypatch.setattr(analyzer, '_make_request_with_retry', request)
    row = analyzer.scrape_naver_institutional_trend_data('005930')
    assert row.data_date == '2026-11-06' and row.scrape_date == '2026-11-08'
    assert requested == ['https://m.stock.naver.com/api/stock/005930/trend?pageSize=60']


def test_partial_source_coverage_is_not_relabelled_as_all_success(tmp_path, monkeypatch):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    monkeypatch.setattr(analyzer, 'load_all_stock_info', lambda: pd.DataFrame({'ticker': ['005930', '000660']}))
    good = analyzer._analyze_comprehensive_trend('005930', analyzer._extract_trend_json(api_rows(), '005930'))
    monkeypatch.setattr(analyzer, 'scrape_naver_institutional_trend_data', lambda ticker: good if ticker == '005930' else None)
    result = analyzer.download_all_institutional_data(max_workers=1)
    metadata = analyzer._create_metadata(result)
    assert metadata['attempted_scrapes'] == 2
    assert metadata['successful_scrapes'] == 1 and metadata['failed_scrapes'] == 1
    assert json.loads(metadata['requested_codes']) == ['005930', '000660']
    assert json.loads(metadata['failed_codes']) == ['000660']


@pytest.mark.parametrize('kind,expected,reason', [
    ('short', 'skipped', 'insufficient_history'),
    ('old', 'failed', 'source_history_not_current'),
    ('empty', 'failed', 'invalid_or_empty_response'),
    ('network', 'failed', 'request_failed'),
])
def test_only_verified_short_current_history_can_be_skipped(tmp_path, monkeypatch, kind, expected, reason):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    rows = api_rows()
    if kind == 'short': rows = rows[:2]
    if kind == 'old':
        for idx, row in enumerate(rows): row['bizdate'] = f'202609{10-idx:02d}'
    if kind == 'empty': rows = []
    class Response:
        def json(self): return rows
    monkeypatch.setattr(analyzer, '_make_request_with_retry', lambda url: None if kind == 'network' else Response())
    assert analyzer.scrape_naver_institutional_trend_data('005930') is None
    assert analyzer._request_outcomes['005930']['status'] == expected
    assert analyzer._request_outcomes['005930']['reason'] == reason


@pytest.mark.parametrize('mode,expected_success,expected_failed,expected_skipped', [
    ('all_stale', 0, 2, 0), ('all_short', 0, 0, 2), ('fresh_and_stale', 1, 1, 0),
])
def test_stale_or_no_usable_coverage_never_completes_main(
        tmp_path, monkeypatch, mode, expected_success, expected_failed, expected_skipped):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    monkeypatch.setattr(analyzer, 'load_all_stock_info', lambda: pd.DataFrame({'ticker': ['005930', '000660']}))
    class Response:
        def __init__(self, ticker): self.ticker = ticker
        def json(self):
            rows = api_rows()
            for row in rows: row['itemCode'] = self.ticker
            if mode == 'all_short': return rows[:2]
            if mode == 'all_stale' or self.ticker == '000660':
                for idx, row in enumerate(rows): row['bizdate'] = f'202609{10-idx:02d}'
            return rows
    monkeypatch.setattr(analyzer, '_make_request_with_retry', lambda url: Response(url.split('/')[-2]))
    monkeypatch.setattr(producer, 'EnhancedKoreanInstitutionalTrendAnalyzer', lambda **kwargs: analyzer)
    with pytest.raises(RuntimeError):
        producer.main()
    summary = analyzer.collection_summary
    assert summary['successful'] == expected_success
    assert summary['failed'] == expected_failed and summary['skipped'] == expected_skipped
    assert summary['status'] != 'completed'
    if not expected_success:
        assert not analyzer.all_institutional_csv_path.exists()


def test_partial_cli_preserves_previous_missing_row_and_fails(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    (tmp_path/'korean_stocks_list.csv').write_text('ticker,name,market\n005930,One,KOSPI\n000660,Two,KOSPI\n')
    old = asdict(producer.InstitutionalData('000660', '2026-09-10', 'naver_finance_enhanced', 20,
                                          data_date='2026-09-10', foreign_net_buy_5d=123456,
                                          momentum_score=99.9))
    pd.DataFrame([old]).to_csv(tmp_path/'all_institutional_trend_data.csv', index=False)
    code = f'''
import sys
sys.path.insert(0, {str(Path(producer.__file__).parent)!r})
import all_institutional_trend_data as p
from datetime import datetime
class Now(datetime):
    @classmethod
    def now(cls, tz=None): return cls(2026,11,8,12)
p.datetime=Now
class Response:
    def json(self): return {api_rows()!r}
p.EnhancedKoreanInstitutionalTrendAnalyzer._make_request_with_retry=lambda self,url: Response() if '/005930/' in url else None
p.main()
'''
    completed = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                               env=dict(os.environ, DATA_DIR=str(tmp_path), PYTHONIOENCODING='utf-8'),
                               capture_output=True, timeout=20)
    assert completed.returncode != 0
    snapshot = pd.read_csv(tmp_path/'all_institutional_trend_data.csv', dtype={'ticker': str}).set_index('ticker')
    assert set(snapshot.index) == {'005930', '000660'}
    assert snapshot.loc['005930', 'data_date'] == '2026-11-06'
    assert snapshot.loc['000660', 'data_date'] == '2026-09-10'
    assert snapshot.loc['000660', 'scrape_date'] == '2026-09-10'
    assert snapshot.loc['000660', 'foreign_net_buy_5d'] == 123456
    assert snapshot.loc['000660', 'momentum_score'] == 99.9
    status = json.loads((tmp_path/'institutional_collection_status.json').read_text())
    assert status['status'] == 'partial' and status['failed_codes'] == ['000660']
    assert status['successful'] == 1 and status['failed'] == 1 and status['skipped'] == 0


def test_retry_requests_only_failed_codes_and_preserves_other_rows(tmp_path, monkeypatch):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    monkeypatch.setattr(analyzer, 'load_all_stock_info', lambda: pd.DataFrame({'ticker': ['005930', '000660']}))
    old = asdict(producer.InstitutionalData('005930', '2026-11-08', 'naver_finance_trend_api', 60, data_date='2026-11-06'))
    pd.DataFrame([old]).to_csv(tmp_path/'all_institutional_trend_data.csv', index=False)
    requested = []
    def scrape(ticker):
        requested.append(ticker)
        return producer.InstitutionalData(ticker, '2026-11-08', 'naver_finance_trend_api', 60, data_date='2026-11-06')
    monkeypatch.setattr(analyzer, 'scrape_naver_institutional_trend_data', scrape)
    result = analyzer.download_all_institutional_data(requested_codes=['000660'], max_workers=1)
    assert requested == ['000660']
    assert analyzer.save_institutional_data(result)
    assert analyzer.collection_summary['failed_codes'] == []
    snapshot = pd.read_csv(tmp_path/'all_institutional_trend_data.csv', dtype={'ticker': str})
    assert set(snapshot['ticker']) == {'005930', '000660'}


def test_retained_rows_preserve_every_csv_value_without_float_round_trip(tmp_path):
    import csv
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    previous = asdict(producer.InstitutionalData(
        '000660', '2026-09-10', 'naver_finance_enhanced', 20, data_date=''))
    previous.update(institutional_ratio_60d='0.30000000000000004',
                    foreign_ratio_10d='2.2250738585072014e-308',
                    foreign_net_buy_60d='9007199254740993', risk_level='NA')
    target = tmp_path/'all_institutional_trend_data.csv'
    with target.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(previous))
        writer.writeheader(); writer.writerow(previous)
    with target.open(encoding='utf-8-sig', newline='') as handle:
        original = next(csv.DictReader(handle))
    fresh = asdict(producer.InstitutionalData(
        '005930', '2026-11-08', 'naver_finance_trend_api', 60, data_date='2026-11-06'))
    assert analyzer.save_institutional_data(pd.DataFrame([fresh]))
    with target.open(encoding='utf-8-sig', newline='') as handle:
        stored = {row['ticker']: row for row in csv.DictReader(handle)}
    assert stored['000660'] == original
    metadata = pd.read_csv(tmp_path/'all_institutional_metadata.csv').iloc[0]
    assert metadata['average_data_days'] == 40


@pytest.mark.parametrize('changes', [
    {'itemCode': '000660'}, {'bizdate': 'invalid'}, {'organPureBuyQuant': '-'},
    {'foreignerPureBuyQuant': None}, {'accumulatedTradingVolume': 'bad'}, {'closePrice': '0'},
])
def test_parser_does_not_replace_missing_numbers_with_zero(tmp_path, changes):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    rows = api_rows(); rows[0].update(changes)
    assert analyzer._extract_trend_json(rows, '005930') == []


def test_invalid_history_records_actual_latest_date_and_missing_field(tmp_path, monkeypatch):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    payload = api_rows()
    payload[-1]['accumulatedTradingVolume'] = '-'
    class Response:
        def json(self): return payload
    monkeypatch.setattr(analyzer, '_make_request_with_retry', lambda url: Response())
    assert analyzer.scrape_naver_institutional_trend_data('005930') is None
    outcome = analyzer._request_outcomes['005930']
    assert outcome['status'] == 'failed'
    assert outcome['reason'] == 'invalid_or_empty_response'
    assert outcome['data_date'] == '2026-11-06'
    assert outcome['source_rows'] == 5
    assert outcome['response_error'] == 'invalid_numeric_value'
    assert outcome['invalid_field'] == 'accumulatedTradingVolume'
    assert outcome['invalid_source_date'] == '2026-11-02'
    assert payload[-1]['accumulatedTradingVolume'] == '-'


def test_stock_codes_remain_six_characters(tmp_path):
    (tmp_path/'korean_stocks_list.csv').write_text('ticker,name,market\n005930,Test,KOSPI\n000660,Test,KOSPI\n')
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    assert analyzer.load_all_stock_info()['ticker'].tolist() == ['005930', '000660']


@pytest.mark.parametrize('source_date', ['20260910', '20261109'])
def test_producer_rejects_stale_or_future_source_dates(tmp_path, source_date):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    rows = api_rows(); rows[0]['bizdate'] = source_date
    if source_date == '20260910':
        for idx, row in enumerate(rows): row['bizdate'] = f'202609{10-idx:02d}'
    daily = analyzer._extract_trend_json(rows, '005930')
    assert analyzer._analyze_comprehensive_trend('005930', daily) is None
    assert analyzer._create_fallback_data('005930') is None


def test_failed_cli_exits_nonzero_without_touching_real_data(tmp_path):
    import os
    import subprocess
    import sys
    env = dict(os.environ, DATA_DIR=str(tmp_path), PYTHONIOENCODING='utf-8')
    completed = subprocess.run([sys.executable, producer.__file__], cwd=tmp_path,
                               capture_output=True, env=env, timeout=20)
    assert completed.returncode != 0
    assert not (tmp_path/'all_institutional_trend_data.csv').exists()


@pytest.mark.parametrize('save_ok', [None, False])
def test_failed_main_raises_for_cli_and_in_process_scheduler(monkeypatch, save_ok):
    class Analyzer:
        def __init__(self, **kwargs): pass
        def download_all_institutional_data(self, **kwargs):
            return pd.DataFrame() if save_ok is None else pd.DataFrame([supply_row()])
        def save_institutional_data(self, frame): return save_ok
    monkeypatch.setattr(producer, 'EnhancedKoreanInstitutionalTrendAnalyzer', Analyzer)
    with pytest.raises(RuntimeError):
        producer.main()


def test_failed_save_preserves_previous_snapshot(tmp_path, monkeypatch):
    analyzer = producer.EnhancedKoreanInstitutionalTrendAnalyzer(data_dir=str(tmp_path))
    target = tmp_path/'all_institutional_trend_data.csv'
    previous = 'ticker,scrape_date\n005930,2026-09-10\n'
    target.write_text(previous, encoding='utf8')
    original = pd.DataFrame.to_csv
    def fail(frame, path, *args, **kwargs):
        if str(path).endswith('.tmp'):
            raise OSError('disk full')
        return original(frame, path, *args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, 'to_csv', fail)
    row = asdict(producer.InstitutionalData('005930', '2026-11-08', 'naver_finance_trend_api', 60))
    assert not analyzer.save_institutional_data(pd.DataFrame([row]))
    assert target.read_text() == previous
