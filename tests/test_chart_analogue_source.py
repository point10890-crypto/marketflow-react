"""Closed adjusted source snapshots must retain actual collection availability."""
import csv
import importlib
import time
from datetime import datetime, timezone

import pytest


def source_module():
    try:
        return importlib.import_module('app.services.mirofish.chart_analogue_source')
    except ModuleNotFoundError:
        pytest.fail('Closed daily source collector is not implemented')


def universe(path):
    path.write_text('ticker,date,name,current_price,update_time\n003690,2026-01-01,코리안리,1,\n005930,2026-01-01,삼성전자,1,\n', encoding='utf-8')


def xml(symbol, values):
    return ('<protocol><chartdata symbol="' + symbol + '">' + ''.join('<item data="' + value + '" />' for value in values) + '</chartdata></protocol>').encode()


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def test_collector_rejects_current_intraday_invalid_and_duplicate_observations(tmp_path):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    raw_before = raw.read_bytes()
    data = xml('003690', ['20260929|1|1|1|14300|10', '20260930|1|1|1|14390|10',
                           '20260930|1|1|1|14390|10', '20261001|1|1|1|14500|10',
                           '20260926|1|1|1|100|10'])
    report = module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 10, 1, 5, 52, tzinfo=timezone.utc), fetcher=lambda symbol: data)
    saved = rows(output)
    assert [item['date'] for item in saved] == ['2026-09-29', '2026-09-30']
    assert saved[-1]['current_price'] == '14390.0'
    assert all(item['update_time'] == '2026-10-01T05:52:00Z' for item in saved)
    assert all(item['price_basis'] == 'provider_adjusted' and item['source_id'] == 'naver_closed_daily' for item in saved)
    assert report['status'] == 'complete'
    assert report['rejected']['intraday'] == 1
    assert report['rejected']['duplicate_sessions'] == 1
    assert report['rejected']['bad_price'] == 0
    assert report['rejected']['bad_date'] == 0
    assert report['rejected']['non_session_date'] == 1
    assert raw.read_bytes() == raw_before


@pytest.mark.parametrize('bad_bar', ['20260929|1|1|1|nan|10', '20260929|1|1|1|0|10', 'bad|1|1|1|1|10', '20260930|1|1|1|99999|10'])
def test_bad_or_conflicting_provider_bar_preserves_whole_trusted_snapshot(tmp_path, bad_bar):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|100|10']))
    before = output.read_bytes()
    report = module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 10, 1, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|101|10', bad_bar]))
    assert report['status'] == 'failed'
    assert report['preserved_symbols'] == 1
    assert output.read_bytes() == before


def test_provider_euc_kr_xml_is_decoded_before_elementtree(tmp_path):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    payload = '<?xml version="1.0" encoding="EUC-KR" ?><protocol><chartdata symbol="003690" name="코리안리"><item data="20261001|1|1|1|14390|10" /></chartdata></protocol>'.encode('euc-kr')
    report = module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 10, 1, 8, tzinfo=timezone.utc), fetcher=lambda symbol: payload)
    assert report['status'] == 'complete'
    assert rows(output)[0]['current_price'] == '14390.0'


def test_completed_today_is_available_only_after_actual_capture(tmp_path, monkeypatch):
    module = source_module()
    from app.services.mirofish import chart_analogue
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    data = xml('003690', ['20260930|1|1|1|14000|10', '20261001|1|1|1|14390|10'])
    module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 10, 1, 7, 0, tzinfo=timezone.utc), fetcher=lambda symbol: data)
    monkeypatch.setattr(chart_analogue, 'INDEX_ROOT', tmp_path / 'index')
    chart_analogue.build_index(output, tmp_path / 'index', price_basis='provider_adjusted', source_id='naver_closed_daily')
    before = chart_analogue.predict('003690', as_of='2026-10-01T06:59:59Z')
    after = chart_analogue.predict('003690', as_of='2026-10-01T07:00:00Z')
    assert before['history'] == []
    assert after['history'][-1]['close'] == 14390
    assert after['source']['price_basis'] == 'provider_adjusted'
    assert not any('are unadjusted' in warning for warning in after['warnings'])


def test_subsecond_capture_cannot_become_available_earlier_in_the_same_second(tmp_path, monkeypatch):
    module = source_module()
    from app.services.mirofish import chart_analogue
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    module.refresh_prices(raw, output, symbols=['003690'], now=datetime(2026, 10, 1, 7, 0, 0, 900000, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20261001|1|1|1|14390|10']))
    monkeypatch.setattr(chart_analogue, 'INDEX_ROOT', tmp_path / 'index')
    chart_analogue.build_index(output, tmp_path / 'index', price_basis='provider_adjusted', source_id='naver_closed_daily')
    assert chart_analogue.predict('003690', as_of='2026-10-01T07:00:00.100000Z')['history'] == []
    assert chart_analogue.predict('003690', as_of='2026-10-01T07:00:01Z')['history'][-1]['close'] == 14390


def test_partial_failure_preserves_previous_symbol_captures(tmp_path, monkeypatch):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    initial = datetime(2026, 9, 30, 8, tzinfo=timezone.utc)
    module.refresh_prices(raw, output, now=initial, fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|100|10']))
    def partial(symbol):
        if symbol == '005930':
            raise TimeoutError('provider unavailable')
        return xml(symbol, ['20260930|1|1|1|101|10', '20261001|1|1|1|102|10'])
    report = module.refresh_prices(raw, output, now=datetime(2026, 10, 1, 8, tzinfo=timezone.utc), fetcher=partial)
    saved = rows(output)
    assert report['status'] == 'partial'
    assert report['failed_symbols'] == 1 and report['preserved_symbols'] == 1
    assert [item['update_time'] for item in saved if item['ticker'] == '005930'] == ['2026-09-30T08:00:00Z']
    assert [item['current_price'] for item in saved if item['ticker'] == '005930'] == ['100.0']
    assert [item['update_time'] for item in saved if item['ticker'] == '003690'] == ['2026-10-01T08:00:00Z'] * 2
    assert {item['collection_status'] for item in saved if item['ticker'] == '005930'} == {'cache_preserved'}
    assert {item['collection_status'] for item in saved if item['ticker'] == '003690'} == {'fresh'}
    from app.services.mirofish import chart_analogue
    monkeypatch.setattr(chart_analogue, 'INDEX_ROOT', tmp_path / 'index')
    chart_analogue.build_index(output, tmp_path / 'index', price_basis='provider_adjusted', source_id='naver_closed_daily')
    prediction = chart_analogue.predict('005930', as_of='2026-10-01T09:00:00Z')
    assert prediction['source']['query_collection_status'] == 'cache_preserved'
    assert prediction['source']['query_captured_at'] == '2026-09-30T08:00:00Z'
    assert prediction['source']['collection_summary'] == {'fresh_symbols': 1, 'cache_preserved_symbols': 1, 'untracked_symbols': 0}


def test_full_failure_keeps_atomic_previous_snapshot(tmp_path):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    module.refresh_prices(raw, output, now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|100|10']))
    before = output.read_bytes()
    report = module.refresh_prices(raw, output, fetcher=lambda symbol: b'<malformed')
    assert report['status'] == 'failed'
    assert output.read_bytes() == before
    assert not list(tmp_path.glob('.closed-prices-*'))


def test_failed_atomic_publication_keeps_last_good_snapshot(tmp_path, monkeypatch):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    module.refresh_prices(raw, output, now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|100|10']))
    before = output.read_bytes()
    def unavailable_destination(*args):
        raise PermissionError('Publication failed')
    monkeypatch.setattr(module.os, 'replace', unavailable_destination)
    with pytest.raises(PermissionError):
        module.refresh_prices(raw, output, now=datetime(2026, 10, 1, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20261001|1|1|1|200|10']))
    assert output.read_bytes() == before
    assert not list(tmp_path.glob('.closed-prices-*'))


def test_raw_previous_snapshot_is_never_mixed_into_adjusted_feed(tmp_path):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    output.write_bytes(raw.read_bytes())
    def partial(symbol):
        if symbol == '005930':
            raise TimeoutError()
        return xml(symbol, ['20260930|1|1|1|101|10'])
    report = module.refresh_prices(raw, output, now=datetime(2026, 10, 1, 8, tzinfo=timezone.utc), fetcher=partial)
    assert report['preserved_symbols'] == 0
    assert {item['ticker'] for item in rows(output)} == {'003690'}


@pytest.mark.parametrize('payload', [b'<!DOCTYPE root [<!ENTITY bad "1">]><root>&bad;</root>', b'x' * (2 * 1024 * 1024 + 1), xml('005930', ['20260930|1|1|1|100|10'])], ids=['entities', 'oversize', 'wrong_symbol'])
def test_untrusted_provider_payload_is_bounded_and_symbol_checked(tmp_path, payload):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    report = module.refresh_prices(raw, output, symbols=['003690'], fetcher=lambda symbol: payload)
    assert report['status'] == 'failed'
    assert not output.exists()


def test_collector_validates_query_bounds_before_network(tmp_path):
    module = source_module()
    raw = tmp_path / 'raw.csv'
    universe(raw)
    for arguments in ({'workers': 9}, {'symbols': ['../bad']}, {'symbols': ['999999']}, {'now': datetime(2026, 1, 1)}):
        with pytest.raises(ValueError):
            module.refresh_prices(raw, tmp_path / 'out.csv', fetcher=lambda symbol: pytest.fail('network must not run'), **arguments)


def test_global_collection_budget_cancels_pending_work_and_preserves_snapshot(tmp_path):
    module = source_module()
    raw, output = tmp_path / 'raw.csv', tmp_path / 'closed.csv'
    universe(raw)
    module.refresh_prices(raw, output, now=datetime(2026, 9, 30, 8, tzinfo=timezone.utc), fetcher=lambda symbol: xml(symbol, ['20260930|1|1|1|100|10']))
    before = output.read_bytes()
    def slow(symbol):
        time.sleep(0.05)
        return xml(symbol, ['20260930|1|1|1|200|10'])
    report = module.refresh_prices(raw, output, workers=1, max_seconds=0.01, fetcher=slow)
    assert report['status'] == 'failed' and report['budget_expired'] is True
    assert report['failed_symbols'] == 2
    assert output.read_bytes() == before


def test_fetch_checks_deadline_between_single_network_reads(monkeypatch):
    module = source_module()
    values = iter([0.0, 0.0, 17.0])
    monkeypatch.setattr(module.monotonic_time, 'monotonic', lambda: next(values))
    class Raw:
        def read1(self, amount, decode_content=False):
            return b'<protocol>'
    class Response:
        raw = Raw()
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def raise_for_status(self):
            pass
    monkeypatch.setattr(module.requests, 'get', lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match='budget'):
        module.fetch_history('003690')
