import csv
import hashlib
import importlib.util
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from urllib3.exceptions import ProtocolError


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/collect_large_cap_price_history.py'
HEADER = ['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율']
STAMP = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)


def collector():
    assert SCRIPT.exists(), 'The bounded research collector has not been implemented'
    spec = importlib.util.spec_from_file_location('long_price_collector_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def payload(rows, header=HEADER, encoding='utf-8'):
    return ('\n  ' + repr([header, *rows]) + '\n').encode(encoding)


def universe(tmp_path, symbols=('005930', '000660', '035420')):
    path = tmp_path / 'universe.json'
    path.write_text(json.dumps({'as_of': '2026-10-01', 'ranking': {'ranked': [
        {'symbol': symbol, 'rank': index + 1, 'name': f'Company {index}', 'market': 'KOSPI'}
        for index, symbol in enumerate(symbols)
    ]}}), encoding='utf-8')
    return path


def capture(rows):
    return {'payload': payload(rows), 'captured_at': STAMP.isoformat(), 'http_status': 200}


def test_suspension_rows_and_one_won_anomaly_are_preserved_without_changing_prices():
    module = collector()
    result = module.parse_payload(payload([
        ['20180427', 53380, 53639, 52440, 53000, 606216, 52.06],
        ['20180430', 0, 0, 0, 53000, 0, 52.06],
        ['20180504', 53000, 53900, 51800, 51900, 39565391, 52.79],
        ['20180508', 52600, 53199, 51900, 53200, 23104720, 52.81],
    ]), '2005-01-01', '2026-10-02')
    assert len(result['bars']) == 4
    assert result['bars'][1]['close'] == 53000 and result['bars'][1]['open'] == 0
    assert set(result['bars'][1]['quality_flags']) == {'zero_ohl', 'no_tradable_volume'}
    assert result['bars'][3]['close'] == 53200 and result['bars'][3]['high'] == 53199
    assert result['bars'][3]['quality_flags'] == ['ohlc_bounds_mismatch']
    assert result['quality_counts'] == {'zero_ohl': 1, 'no_tradable_volume': 1, 'ohlc_bounds_mismatch': 1}


@pytest.mark.parametrize('encoding', ['utf-8', 'euc-kr', 'cp949'])
def test_header_six_and_seven_column_rows_are_decoded_from_actual_provider_encodings(encoding):
    module = collector()
    result = module.parse_payload(payload([
        ['20050103', 10, 12, 9, 11, 100], ['20050104', 11, 13, 10, 12, 110, 50.1],
    ], encoding=encoding), '2005-01-01', '2026-10-02')
    assert [bar['close'] for bar in result['bars']] == [11, 12]
    assert result['header'] == HEADER and result['row_shape_counts'] == {'6': 1, '7': 1}


@pytest.mark.parametrize('rows', [
    [['20050103', True, 12, 9, 11, 100]],
    [['20050103', '10', 12, 9, 11, 100]],
    [['20050103', -1, 12, 9, 11, 100]],
    [['20050103', 10, 12, 9, 11]],
    [['20050230', 10, 12, 9, 11, 100]],
    [['20041231', 10, 12, 9, 11, 100]],
    [['20050103', 10, 12, 9, 11, 100], ['20050103', 10, 12, 9, 11, 100]],
    [['20050104', 10, 12, 9, 11, 100], ['20050103', 10, 12, 9, 11, 100]],
])
def test_malformed_snapshot_is_rejected_as_a_whole(rows):
    module = collector()
    with pytest.raises(module.InvalidPayload):
        module.parse_payload(payload(rows), '2005-01-01', '2026-10-02')


def test_wrong_header_code_expression_nonfinite_and_size_limit_are_not_accepted(tmp_path):
    module = collector()
    for raw in [payload([['20050103', 10, 12, 9, 11, 100]], header=['wrong'] * 7),
                b"__import__('os').system('unsafe')", b"[['x'], ['20050103', 1e999, 12, 9, 11, 100]]",
                b'x' * (5 * 1024 * 1024 + 1)]:
        with pytest.raises(module.InvalidPayload):
            module.parse_payload(raw, '2005-01-01', '2026-10-02')


def test_selected_codes_keep_original_order_and_never_refill_after_a_failure(tmp_path):
    module = collector()
    source = universe(tmp_path)
    selected = module.load_universe(source, 2)
    assert [row['symbol'] for row in selected] == ['005930', '000660']
    requested = []
    def fetch(symbol, params):
        requested.append(symbol)
        if symbol == '005930':
            raise requests.Timeout('temporary network failure')
        return capture([['20050103', 10, 12, 9, 11, 100]])
    report = module.collect(source, tmp_path / 'output', start='2005-01-01', end='2026-10-02',
                            max_symbols=2, workers=1, retries=0, fetch=True, fetcher=fetch)
    assert requested == ['005930', '000660']
    assert report['selected_symbols'] == ['005930', '000660']
    assert report['status_counts'] == {'failed': 1, 'collected': 1}
    assert report['symbols'][0]['status'] == 'failed'
    assert (tmp_path / 'output' / 'symbols' / '005930' / 'summary.json').exists()


def test_collection_emits_raw_ohlcv_and_explicit_unverified_metadata_then_resumes_without_network(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930',))
    out = tmp_path / 'output'
    def fetch(symbol, params):
        assert symbol == '005930' and params['startTime'] == '20050101' and params['endTime'] == '20261002'
        return capture([['20180427', 53380, 53639, 52440, 53000, 606216],
                        ['20180430', 0, 0, 0, 53000, 0]])
    first = module.collect(source, out, start='2005-01-01', end='2026-10-02', fetch=True, fetcher=fetch)
    with (out / 'prices.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2 and rows[1]['open'] == '0' and rows[1]['close'] == '53000'
    assert rows[1]['quality_flags'] == 'zero_ohl;no_tradable_volume'
    assert rows[1]['analysis_ready'] == 'false' and rows[1]['captured_at'] == STAMP.isoformat()
    assert rows[0]['price_basis'] == 'provider_reported_unverified'
    for flag in ('corporate_action_adjustment_verified', 'historical_vintage_verified', 'dividend_included', 'analysis_ready'):
        assert first[flag] is False and first['symbols'][0][flag] is False
    receipt = json.loads((out / 'symbols' / '005930' / 'summary.json').read_text(encoding='utf-8'))
    raw = out / receipt['raw_file']
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == receipt['raw_sha256']
    assert receipt['coverage']['first_date'] == '2018-04-27' and receipt['coverage']['rows'] == 2
    second = module.collect(source, out, start='2005-01-01', end='2026-10-02',
                            fetcher=lambda *_: pytest.fail('Valid identical raw should be reused'))
    assert second['symbols'][0]['cache_reused'] is True and second['total_rows'] == 2


def test_tampered_raw_hash_is_not_reused_and_failure_is_not_hidden_by_old_bars(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930',))
    out = tmp_path / 'output'
    first = module.collect(source, out, start='2005-01-01', end='2026-10-02',
                           fetch=True, fetcher=lambda *_: capture([['20050103', 10, 12, 9, 11, 100]]))
    (out / first['symbols'][0]['raw_file']).write_bytes(b'tampered')
    def broken(*_):
        raise requests.Timeout('offline')
    second = module.collect(source, out, start='2005-01-01', end='2026-10-02', retries=0, fetch=True, fetcher=broken)
    assert second['status_counts'] == {'failed': 1} and second['total_rows'] == 0
    assert second['symbols'][0]['cache_rejection'] == 'raw_hash_mismatch'
    assert len((out / 'prices.csv').read_text(encoding='utf-8-sig').splitlines()) == 1


def test_malformed_response_keeps_raw_and_reports_failure_without_shortening_it(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930',))
    out = tmp_path / 'output'
    raw = payload([['20050103', 10, 12, 9, 11, 100], ['20050103', 10, 12, 9, 11, 100]])
    report = module.collect(source, out, start='2005-01-01', end='2026-10-02',
                            fetch=True, fetcher=lambda *_: {'payload': raw, 'captured_at': STAMP.isoformat(), 'http_status': 200})
    row = report['symbols'][0]
    assert row['status'] == 'rejected' and report['total_rows'] == 0
    assert (out / row['raw_file']).read_bytes() == raw and row['error_type'] == 'InvalidPayload'


def test_transient_fetch_has_at_most_two_retries_and_permanent_http_error_has_none(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930',))
    attempts = []
    def transient(*_):
        attempts.append(1)
        raise requests.Timeout('timeout')
    report = module.collect(source, tmp_path / 'retry', start='2005-01-01', end='2026-10-02',
                            retries=2, workers=1, fetch=True, fetcher=transient, sleeper=lambda _: None)
    assert len(attempts) == 3 and report['symbols'][0]['attempts'] == 3
    attempts.clear()
    def forbidden(*_):
        attempts.append(1)
        response = requests.Response()
        response.status_code = 403
        raise requests.HTTPError('denied', response=response)
    report = module.collect(source, tmp_path / 'denied', start='2005-01-01', end='2026-10-02',
                            retries=2, fetch=True, fetcher=forbidden, sleeper=lambda _: None)
    assert len(attempts) == 1 and report['symbols'][0]['attempts'] == 1


@pytest.mark.parametrize('options', [{'workers': 4}, {'workers': 0}, {'retries': 3}, {'max_symbols': 101}, {'fetch': 'yes'}])
def test_collector_bounds_fail_before_any_fetch(tmp_path, options):
    module = collector()
    with pytest.raises(ValueError):
        module.collect(universe(tmp_path), tmp_path / 'out', start='2005-01-01', end='2026-10-02',
                       fetcher=lambda *_: pytest.fail('Invalid bounds must not access network'), **options)


def test_manifest_mismatch_fails_before_fetch_instead_of_mixing_periods(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930',))
    out = tmp_path / 'output'
    module.collect(source, out, start='2005-01-01', end='2026-10-02',
                   fetch=True, fetcher=lambda *_: capture([['20050103', 10, 12, 9, 11, 100]]))
    with pytest.raises(ValueError, match='manifest'):
        module.collect(source, out, start='2015-01-01', end='2026-10-02',
                       fetcher=lambda *_: pytest.fail('Mismatch must not fetch'))


def test_invalid_or_duplicate_selected_symbol_is_not_replaced_by_later_codes(tmp_path):
    module = collector()
    for symbols in [('bad', '000660', '035420'), ('005930', '005930', '035420')]:
        with pytest.raises(ValueError):
            module.load_universe(universe(tmp_path, symbols), 2)


def test_atomic_write_failure_keeps_previous_complete_artifact(tmp_path, monkeypatch):
    module = collector()
    destination = tmp_path / 'summary.json'
    destination.write_bytes(b'previous')
    monkeypatch.setattr(module.os, 'replace', lambda *_: (_ for _ in ()).throw(OSError('locked')))
    with pytest.raises(OSError):
        module.atomic_write(destination, b'new')
    assert destination.read_bytes() == b'previous'
    assert list(tmp_path.iterdir()) == [destination]


def test_fixed_public_endpoint_fetch_is_size_time_and_redirect_bounded():
    module = collector()
    options = []
    class Response:
        status_code = 200
        headers = {}
        def __init__(self, chunks):
            self.chunks = iter(chunks)
            self.raw = self
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return None
        def raise_for_status(self):
            return None
        def read1(self, size, decode_content=True):
            assert size <= 65536
            return next(self.chunks, b'')
    def request(url, **kwargs):
        options.append((url, kwargs))
        return Response([payload([['20050103', 10, 12, 9, 11, 100]])])
    params = {'symbol': '005930', 'requestType': '1', 'startTime': '20050101',
              'endTime': '20261002', 'timeframe': 'day'}
    result = module.fetch_payload('005930', params, requester=request)
    assert result['http_status'] == 200 and result['payload'].startswith(b'\n')
    url, kwargs = options[0]
    assert url == 'https://api.finance.naver.com/siseJson.naver'
    assert kwargs['allow_redirects'] is False and kwargs['timeout'] == (4, 8)
    with pytest.raises(module.InvalidPayload, match='size'):
        module.fetch_payload('005930', params, requester=lambda *_args, **_kw: Response([b'x' * (5 * 1024 * 1024 + 1)]))
    times = iter([0, 0, 21])
    with pytest.raises(requests.Timeout):
        module.fetch_payload('005930', params, requester=request, monotonic=lambda: next(times))


def test_parallel_collection_never_has_more_than_three_requests_in_flight(tmp_path):
    module = collector()
    source = universe(tmp_path, tuple(f'{index:06}' for index in range(1, 10)))
    lock = threading.Lock()
    active = peak = 0
    def fetch(*_):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.015)
        with lock:
            active -= 1
        return capture([['20050103', 10, 12, 9, 11, 100]])
    report = module.collect(source, tmp_path / 'output', start='2005-01-01', end='2026-10-02', workers=3, fetch=True, fetcher=fetch)
    assert report['status_counts'] == {'collected': 9} and 1 < peak <= 3


@pytest.mark.parametrize('ratio', [None, 'nan', 'unavailable'])
def test_optional_foreign_ratio_does_not_discard_valid_ohlcv(ratio):
    module = collector()
    result = module.parse_payload(payload([['20050103', 10, 12, 9, 11, 100, ratio]]), '2005-01-01', '2026-10-02')
    assert result['bars'][0]['close'] == 11 and result['bars'][0]['volume'] == 100


def test_bare_json_null_is_safe_only_in_an_optional_field():
    module = collector()
    raw = payload([['20050103', 10, 12, 9, 11, 100, None]]).replace(b'None', b'null')
    assert module.parse_payload(raw, '2005-01-01', '2026-10-02')['bars'][0]['close'] == 11
    invalid = payload([['20050103', None, 12, 9, 11, 100]]).replace(b'None', b'null')
    with pytest.raises(module.InvalidPayload):
        module.parse_payload(invalid, '2005-01-01', '2026-10-02')


def test_finite_type_guard_handles_integer_overflow_as_invalid_snapshot():
    module = collector()
    with pytest.raises(module.InvalidPayload):
        module.parse_payload(payload([['20050103', 10**500, 12, 9, 11, 100]]), '2005-01-01', '2026-10-02')


def test_current_name_and_aggregate_coverage_are_labeled_without_historical_membership_claim(tmp_path):
    module = collector()
    source = universe(tmp_path, ('005930', '000660', '035420'))
    counts = {'005930': 1, '000660': 2, '035420': 4}
    def fetch(symbol, _):
        return capture([[f'2005010{index+3}', 10, 12, 9, 11, 100] for index in range(counts[symbol])])
    report = module.collect(source, tmp_path / 'out', start='2005-01-01', end='2026-10-02', fetch=True, fetcher=fetch)
    assert [row['name_as_of'] for row in report['symbols']] == ['2026-10-01'] * 3
    assert report['coverage_summary'] == {'collected_symbols': 3, 'min_rows': 1, 'median_rows': 2,
                                          'max_rows': 4, 'symbols_over_800_rows': 0, 'symbols_at_least_3000_rows': 0}
    assert report['current_cohort_bias'] is True and report['point_in_time_universe_verified'] is False


def test_stream_transport_failure_is_bounded_and_recorded_for_the_selected_symbol(tmp_path):
    module = collector()
    def broken_stream(*_):
        raise ProtocolError('Connection closed during read')
    report = module.collect(universe(tmp_path, ('005930',)), tmp_path / 'out',
                            start='2005-01-01', end='2026-10-02', retries=2,
                            fetch=True, fetcher=broken_stream, sleeper=lambda _: None)
    assert report['status_counts'] == {'failed': 1}
    assert report['symbols'][0]['attempts'] == 3 and report['symbols'][0]['error_type'] == 'ProtocolError'


def test_cache_only_default_never_fetches_a_missing_symbol_and_records_fetch_required(tmp_path):
    module = collector()
    report = module.collect(universe(tmp_path, ('005930',)), tmp_path / 'out',
                            start='2005-01-01', end='2026-10-02',
                            fetcher=lambda *_: pytest.fail('Default mode must not access network'))
    assert report['status_counts'] == {'failed': 1}
    assert report['symbols'][0]['error_code'] == 'fetch_required'
    assert report['symbols'][0]['attempts'] == 0 and report['total_rows'] == 0


@pytest.mark.parametrize('opt_in', [False, True])
def test_cli_passes_explicit_network_opt_in_to_the_collection_boundary(tmp_path, monkeypatch, opt_in):
    module = collector()
    received = []
    def collect(*args, **kwargs):
        received.append(kwargs.get('fetch'))
        return {'status_counts': {'collected': 1}, 'total_rows': 1, 'analysis_ready': False,
                'prices_sha256': 'proof', 'selected_symbols': ['005930']}
    monkeypatch.setattr(module, 'collect', collect)
    monkeypatch.setattr(sys, 'argv', ['collector', '--universe-report', str(tmp_path / 'report.json'),
                                           *(['--fetch'] if opt_in else [])])
    assert module.main() == 0 and received == [opt_in]
