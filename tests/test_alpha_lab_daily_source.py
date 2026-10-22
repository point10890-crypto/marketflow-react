"""KIS daily acquisition boundary; all HTTP responses are offline fixtures."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib

import pytest

NOW = datetime(2026, 10, 22, 0, tzinfo=timezone.utc)


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.daily_source')
    except ModuleNotFoundError:
        pytest.fail('daily source implementation missing')


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Requests:
    def __init__(self, *bodies):
        self.responses = [b if isinstance(b, (Response, Exception)) else Response(b) for b in bodies]
        self.calls = []

    def __call__(self, path, tr_id, params):
        self.calls.append((path, tr_id, deepcopy(params)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def bar(day, **changes):
    return dict(stck_bsop_date=day.replace('-', ''), stck_oprc='100', stck_hgpr='110',
        stck_lwpr='90', stck_clpr='105', acml_vol='10000000', acml_tr_pbmn='1050000000',
        flng_cls_code='00', prtt_rate='0.00', mod_yn='N', revl_issu_reas='', **changes)


def page(*days):
    return dict(rt_cd='0', msg_cd='MCA00000', msg1='normal',
        output1=dict(stck_shrn_iscd='005930'), output2=[bar(day) for day in days])


def provider(*bodies):
    calls = Requests(*bodies)
    return module().KISDailyProvider(request=calls, clock=lambda: NOW), calls


def test_backward_pages_bind_exact_source_request_and_use_actual_capture():
    first, second = page('2026-10-21', '2026-10-20'), page('2026-10-19', '2026-10-16')
    first['headers'] = {'authorization': 'never-store-secret'}
    first['output1']['appkey'] = 'never-store-secret'
    first['output2'][0]['appsecret'] = 'never-store-secret'
    value, calls = provider(first, second)
    result = value.fetch_history('005930', '2026-10-21', count=4)
    assert [row['date'] for row in result['bars']] == ['2026-10-16', '2026-10-19', '2026-10-20', '2026-10-21']
    assert result['captured_at'] == '2026-10-22T00:00:00Z'
    assert result['capture'] == {'first': '2026-10-22T00:00:00Z', 'last': '2026-10-22T00:00:00Z'}
    assert result['source']['tr_id'] == 'FHKST03010100'
    assert result['source']['market'] == 'J' and result['source']['period'] == 'D'
    assert result['source']['adjusted_request'] == '0'
    assert result['history_status'] == 'complete'
    assert len(calls.calls) == 2
    assert [call[2]['FID_INPUT_DATE_2'] for call in calls.calls] == ['20261021', '20261019']
    for path, tr_id, params in calls.calls:
        assert path == '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
        assert tr_id == 'FHKST03010100'
        assert params['FID_COND_MRKT_DIV_CODE'] == 'J' and params['FID_PERIOD_DIV_CODE'] == 'D'
        assert params['FID_ORG_ADJ_PRC'] == '0' and params['FID_INPUT_ISCD'] == '005930'
    assert 'never-store-secret' not in str(result)
    assert result['pages'][0]['response']['output2'][0]['stck_clpr'] == '105'


@pytest.mark.parametrize('change,reason', [
    (lambda b: b['output1'].update(stck_shrn_iscd='000660'), 'daily_identity'),
    (lambda b: b['output2'][0].update(symbol='000660'), 'daily_identity'),
    (lambda b: b['output2'][0].update(stck_clpr='nan'), 'daily_ohlcv'),
    (lambda b: b['output2'][0].update(stck_hgpr='99'), 'daily_ohlcv'),
    (lambda b: b['output2'][0].update(acml_vol='-1'), 'daily_ohlcv'),
    (lambda b: b['output2'][0].update(acml_tr_pbmn='inf'), 'daily_ohlcv'),
    (lambda b: b['output2'][0].update(stck_bsop_date='20260230'), 'daily_session'),
    (lambda b: b['output2'][0].update(stck_bsop_date='20261022'), 'daily_future_row'),
    (lambda b: b.update(output2=[deepcopy(b['output2'][0])] * 101), 'daily_page_size'),
])
def test_malformed_identity_prices_dates_and_large_pages_fail_closed(change, reason):
    body = page('2026-10-21'); change(body)
    value, _ = provider(body)
    with pytest.raises(ValueError, match=reason):
        value.fetch_history('005930', '2026-10-21', count=1)


def test_conflicting_duplicate_is_not_arbitrarily_deduplicated():
    body = page('2026-10-21', '2026-10-21')
    body['output2'][1]['stck_clpr'] = '104'
    value, _ = provider(body)
    with pytest.raises(ValueError, match='daily_duplicate_conflict'):
        value.fetch_history('005930', '2026-10-21', count=2)


def test_repeated_page_without_backward_progress_is_rejected():
    value, calls = provider(page('2026-10-21'), page('2026-10-21'))
    with pytest.raises(ValueError, match='daily_cursor'):
        value.fetch_history('005930', '2026-10-21', count=3)
    assert len(calls.calls) == 2


def test_page_budget_stops_even_if_provider_keeps_returning_one_new_row():
    days = [(date(2026, 10, 21) - timedelta(days=index)).isoformat() for index in range(13)]
    value, calls = provider(*(page(day) for day in days))
    with pytest.raises(ValueError, match='daily_page_limit'):
        value.fetch_history('005930', '2026-10-21')
    assert len(calls.calls) == 12


def test_new_listing_remains_real_data_with_explicit_insufficient_history():
    body = page('2026-10-21')
    body['output2'][0]['acml_vol'] = '0'
    body['output2'][0]['acml_tr_pbmn'] = '0'
    value, _ = provider(body, page())
    result = value.fetch_history('005930', '2026-10-21')
    assert result['history_status'] == 'insufficient_history' and len(result['bars']) == 1
    assert result['bars'][0]['tradable'] is False
    assert result['bars'][0]['quality_flags'] == [{'code': 'zero_volume_nontradable', 'severity': 'nontradable'}]


def test_completion_buffer_is_kst_and_cannot_be_bypassed_by_older_price_date():
    calls = Requests(page('2026-10-21'))
    before = datetime(2026, 10, 21, 11, 29, 59, tzinfo=timezone.utc)
    value = module().KISDailyProvider(request=calls, clock=lambda: before)
    with pytest.raises(ValueError, match='daily_session_incomplete'):
        value.fetch_history('005930', '2026-10-21', count=1)
    assert calls.calls == []
    value = module().KISDailyProvider(request=calls, clock=lambda: before+timedelta(seconds=1))
    assert value.fetch_history('005930', '2026-10-21', count=1)['bars'][0]['date'] == '2026-10-21'


@pytest.mark.parametrize('response,error', [
    (Response(page('2026-10-21'), 503), 'kis_http_failure'),
    (Response({'rt_cd': '1', 'msg1': 'secret-appkey'}), 'kis_api_failure'),
    (Response(ValueError('secret-appkey')), 'kis_payload_invalid'),
    (RuntimeError('secret-appkey'), 'kis_transport_failure'),
])
def test_transport_and_api_failures_expose_only_bounded_reason_codes(response, error, capsys):
    value, _ = provider(response)
    with pytest.raises(ValueError) as caught:
        value.fetch_history('005930', '2026-10-21', count=1)
    assert str(caught.value) == error and caught.value.code == error
    captured = capsys.readouterr()
    assert 'secret-appkey' not in captured.out+captured.err+str(caught.value)


def test_756_sessions_are_eight_bounded_pages_with_only_requested_tail_returned():
    days = [(date(2026, 10, 21)-timedelta(days=index)).isoformat() for index in range(800)]
    value, calls = provider(*(page(*days[start:start+100]) for start in range(0, 800, 100)))
    result = value.fetch_history('005930', '2026-10-21')
    assert len(result['bars']) == 756 and len(result['pages']) == len(calls.calls) == 8
    assert result['bars'][0]['date'] == days[755]
    assert all(len(p['response']['output2']) <= 100 for p in result['pages'])


def test_provider_clock_cannot_move_back_from_request_start():
    clock = iter([NOW, datetime(2026, 10, 21, 12, tzinfo=timezone.utc)])
    value = module().KISDailyProvider(request=Requests(page('2026-10-21')), clock=lambda: next(clock))
    with pytest.raises(ValueError, match='invalid_clock'):
        value.fetch_history('005930', '2026-10-21', count=1)
