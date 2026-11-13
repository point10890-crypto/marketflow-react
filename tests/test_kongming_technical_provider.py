"""Offline provider boundary fixtures cover raw prices and actual index sessions."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import importlib

import pytest


NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
SESSIONS = [(date(2026, 10, 19) + timedelta(days=i)).isoformat()
            for i in range(26) if (date(2026, 10, 19) + timedelta(days=i)).weekday() < 5]


def module():
    try:
        return importlib.import_module('app.services.mirofish.kongming_technical.provider')
    except ModuleNotFoundError:
        pytest.fail('technical provider implementation missing')


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Requests:
    def __init__(self, *responses):
        self.responses = [row if isinstance(row, (Response, Exception)) else Response(row) for row in responses]
        self.calls = []

    def __call__(self, path, tr_id, params):
        self.calls.append((path, tr_id, deepcopy(params)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def page(symbol='005930', days=None):
    return dict(rt_cd='0', output1=dict(stck_shrn_iscd=symbol, hts_kor_isnm='삼성전자'),
                output2=[dict(stck_bsop_date=day.replace('-', ''), stck_oprc='100', stck_hgpr='124',
                              stck_lwpr='100', stck_clpr='112', acml_vol='240', acml_tr_pbmn='26880',
                              flng_cls_code='00', prtt_rate='0.000000', mod_yn='N', revl_issu_reas='0')
                         for day in (SESSIONS if days is None else days)])


def index_page(days=None):
    return dict(rt_cd='0', output1=dict(bstp_cls_code='0001'),
                output2=[dict(stck_bsop_date=day.replace('-', ''), bstp_nmix_prpr='3000.12', acml_vol='100')
                         for day in (SESSIONS if days is None else days)])


def provider(*bodies, clock=None):
    calls = Requests(*bodies)
    return module().TechnicalProvider(request=calls, clock=clock or (lambda: NOW)), calls


def test_one_raw_krx_daily_request_carries_only_whitelisted_evidence():
    body = page()
    body['headers'] = {'authorization': 'never-store-secret'}
    body['output1']['appkey'] = 'never-store-secret'
    body['output2'][0]['appsecret'] = 'never-store-secret'
    value, calls = provider(body)
    result = value.fetch_history('005930', SESSIONS, NOW)
    assert len(result['bars']) == len(result['raw_bars']) == 20
    assert result['bars'][0]['date'] == '2026-10-19'
    assert result['bars'][-1]['close'] == 112
    assert result['raw_bars'][0]['stck_clpr'] == '112'
    assert result['name'] == '삼성전자' and result['fetched_at'] == '2026-11-13T12:00:00Z'
    assert result['source'] == 'KIS:FHKST03010100:J:D:1'
    assert result['source_contract']['price_basis'] == 'KIS_KRX_raw_J_D_1'
    assert len(calls.calls) == 1
    path, tr_id, params = calls.calls[0]
    assert path == '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
    assert tr_id == 'FHKST03010100'
    assert params == dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD='005930',
                         FID_INPUT_DATE_1='20261019', FID_INPUT_DATE_2='20261113',
                         FID_PERIOD_DIV_CODE='D', FID_ORG_ADJ_PRC='1')
    assert 'never-store-secret' not in str(result)


def test_paper_compatible_index_evidence_returns_twenty_actual_dates_in_one_query():
    body = index_page(['2026-10-15', '2026-10-16'] + SESSIONS)
    body['output2'][1]['acml_vol'] = '0'  # Zero activity never confirms an open session.
    value, calls = provider(body)
    result = value.fetch_sessions(NOW)
    assert result == dict(sessions=SESSIONS, source='KIS:KOSPI:FHKUP03500100',
                         captured_at='2026-11-13T12:00:00Z', through='2026-11-13')
    assert len(calls.calls) == 1
    path, tr_id, params = calls.calls[0]
    assert path.endswith('/inquire-daily-indexchartprice') and tr_id == 'FHKUP03500100'
    assert params['FID_COND_MRKT_DIV_CODE'] == 'U' and params['FID_INPUT_ISCD'] == '0001'
    assert params['FID_INPUT_DATE_2'] == '20261113' and params['FID_PERIOD_DIV_CODE'] == 'D'


def test_completed_through_uses_2030_kst_cutoff_and_rejects_naive_clocks():
    assert module().completed_through('2026-11-13T11:29:59Z') == '2026-11-12'
    assert module().completed_through('2026-11-13T11:30:00Z') == '2026-11-13'
    assert module().completed_through('2026-11-14T01:00:00+09:00') == '2026-11-13'
    with pytest.raises(ValueError, match='invalid_clock'):
        module().completed_through(datetime(2026, 11, 13))


@pytest.mark.parametrize('change,reason', [
    (lambda body: body['output1'].update(stck_shrn_iscd='000660'), 'daily_identity'),
    (lambda body: body['output1'].pop('stck_shrn_iscd'), 'daily_identity'),
    (lambda body: body['output2'][0].update(symbol='000660'), 'daily_identity'),
    (lambda body: body['output2'][0].update(stck_clpr='NaN'), 'daily_ohlcv'),
    (lambda body: body['output2'][0].update(stck_oprc='999'), 'daily_ohlcv'),
    (lambda body: body['output2'][0].update(acml_vol='-1'), 'daily_ohlcv'),
    (lambda body: body['output2'][0].update(acml_tr_pbmn='inf'), 'daily_ohlcv'),
    (lambda body: body['output2'][0].update(stck_bsop_date='20261116'), 'daily_future_row'),
    (lambda body: body['output2'][0].update(stck_bsop_date='20261018'), 'daily_session_mismatch'),
    (lambda body: body['output2'].append(deepcopy(body['output2'][0])), 'daily_duplicate'),
    (lambda body: body['output2'][0].update(mod_yn={'appkey': 'secret'}), 'daily_payload'),
])
def test_rejects_wrong_identity_nonfinite_and_non_session_rows(change, reason):
    body = page()
    change(body)
    value, _ = provider(body)
    with pytest.raises(ValueError) as error:
        value.fetch_history('005930', SESSIONS, NOW)
    assert error.value.code == reason


def test_alphanumeric_symbol_is_supported_and_invalid_symbol_never_calls_provider():
    value, calls = provider(page(symbol='0123A0'))
    assert value.fetch_history('0123A0', SESSIONS, NOW)['bars'][0]['symbol'] == '0123A0'
    for symbol in ['000000', 'A005930', '123', '0123a0', '../env', None]:
        with pytest.raises(ValueError, match='invalid_symbol'):
            value.fetch_history(symbol, SESSIONS, NOW)
    assert len(calls.calls) == 1


def test_price_events_and_zero_volume_are_preserved_for_engine_review():
    body = page(days=SESSIONS[-2:])
    body['output2'][0].update(flng_cls_code='02')
    body['output2'][1].update(acml_vol='0', acml_tr_pbmn='0')
    value, _ = provider(body)
    result = value.fetch_history('005930', SESSIONS, NOW)
    assert len(result['bars']) == 2
    assert result['bars'][0]['source_flags']['flng_cls_code'] == '02'
    assert result['bars'][1]['volume'] == 0


@pytest.mark.parametrize('change,reason', [
    (lambda body: body['output1'].update(bstp_cls_code='1001'), 'calendar_invalid'),
    (lambda body: body['output2'][0].update(stck_bsop_date='20261116'), 'calendar_invalid'),
    (lambda body: body['output2'][0].update(bstp_nmix_prpr='NaN'), 'calendar_invalid'),
    (lambda body: body['output2'][0].update(acml_vol='-1'), 'calendar_invalid'),
    (lambda body: body['output2'].append(deepcopy(body['output2'][0])), 'calendar_invalid'),
    (lambda body: body['output2'].pop(), 'calendar_incomplete'),
])
def test_index_session_evidence_never_fills_gaps_with_weekday_guesses(change, reason):
    body = index_page()
    change(body)
    value, _ = provider(body)
    with pytest.raises(ValueError) as error:
        value.fetch_sessions(NOW)
    assert error.value.code == reason


def test_history_before_completion_is_rejected_before_request():
    value, calls = provider(page())
    with pytest.raises(ValueError, match='daily_session_incomplete'):
        value.fetch_history('005930', SESSIONS, '2026-11-13T11:29:59Z')
    assert calls.calls == []


def test_capture_uses_actual_clock_and_cannot_move_backwards():
    value, _ = provider(page(), clock=lambda: NOW + timedelta(seconds=3))
    assert value.fetch_history('005930', SESSIONS, NOW)['fetched_at'] == '2026-11-13T12:00:03Z'
    value, _ = provider(index_page(), clock=lambda: NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match='invalid_clock'):
        value.fetch_sessions(NOW)


@pytest.mark.parametrize('response,reason', [
    (Response({}, 503), 'kis_http_failure'),
    (Response({'rt_cd': '1', 'msg1': 'secret-appkey'}), 'kis_api_failure'),
    (Response(ValueError('secret-appkey')), 'kis_payload_invalid'),
    (RuntimeError('secret-appkey'), 'kis_transport_failure'),
])
def test_errors_expose_only_shared_bounded_codes(response, reason, capsys):
    value, _ = provider(response)
    with pytest.raises(ValueError) as error:
        value.fetch_history('005930', SESSIONS, NOW)
    assert error.value.code == str(error.value) == reason
    profile = importlib.import_module('app.services.mirofish.kongming_technical.profile')
    assert isinstance(error.value, profile.ProfileError)
    captured = capsys.readouterr()
    assert 'secret-appkey' not in captured.out + captured.err + str(error.value)
