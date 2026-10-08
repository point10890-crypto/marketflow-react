"""Strict provider and operator wrappers: offline fixtures, no broker requests."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

NOW = datetime(2026, 10, 6, 0, 5, tzinfo=timezone.utc)  # 09:05 KST
ROOT = Path(__file__).resolve().parents[1]


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.market_provider')
    except ModuleNotFoundError:
        pytest.fail('The strict market provider is missing')


class Response:
    def __init__(self, body, status=200):
        self.status_code, self.body = status, body

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Requests:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __call__(self, path, tr_id, params):
        self.calls.append((path, tr_id, deepcopy(params)))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def calendar():
    return dict(rt_cd='0', output=[dict(bass_dt='20261002', tr_day_yn='Y', opnd_yn='Y'),
        dict(bass_dt='20261003', tr_day_yn='N', opnd_yn='N'),
        dict(bass_dt='20261004', tr_day_yn='N', opnd_yn='N'),
        dict(bass_dt='20261005', tr_day_yn='N', opnd_yn='N'),
        dict(bass_dt='20261006', tr_day_yn='Y', opnd_yn='Y')])


def detail():
    return dict(rt_cd='0', output=dict(stck_shrn_iscd='196170', stck_prpr='103', stck_oprc='101',
                                     acml_vol='1000', temp_stop_yn='N'))


def minutes():
    return dict(rt_cd='0', output1=dict(stck_prpr='104'), output2=[
        dict(stck_bsop_date='20261006', stck_cntg_hour='090500', stck_prpr='104', stck_oprc='103', cntg_vol='0'),
        dict(stck_bsop_date='20261006', stck_cntg_hour='090400', stck_prpr='102', stck_oprc='102', cntg_vol='99')])


def provider(*bodies):
    requests = Requests([Response(body) for body in bodies])
    return module().KISMarketProvider(request=requests), requests


def test_calendar_normalizes_only_official_rows_and_both_open_flags_without_mutating():
    body = calendar(); body['output'].reverse(); before = deepcopy(body)
    body['output'][1]['opnd_yn'] = 'Y'  # Trade-day N still cannot certify open.
    before = deepcopy(body)
    value, calls = provider(body)
    result = value.fetch_calendar('2026-10-02', now=NOW)
    assert result == dict(source='KIS:CTCA0903R', captured_at='2026-10-06T00:05:00Z', days=[
        dict(date='2026-10-02', is_open=True), dict(date='2026-10-03', is_open=False),
        dict(date='2026-10-04', is_open=False), dict(date='2026-10-05', is_open=False),
        dict(date='2026-10-06', is_open=True)])
    assert calls.calls == [('/uapi/domestic-stock/v1/quotations/chk-holiday', 'CTCA0903R',
                            dict(BASS_DT='20261002', CTX_AREA_FK='', CTX_AREA_NK=''))]
    assert body == before


@pytest.mark.parametrize('change', [
    lambda b: b.update(output=[]), lambda b: b.update(output={}),
    lambda b: b['output'].append(deepcopy(b['output'][0])),
    lambda b: b['output'][0].update(bass_dt='20260230'),
    lambda b: b['output'][0].update(bass_dt='2026-10-02'),
    lambda b: b['output'][0].update(tr_day_yn=True),
    lambda b: b['output'][0].update(opnd_yn='unknown'),
    lambda b: b['output'][0].pop('tr_day_yn'),
    lambda b: b['output'][0].update(bass_dt='20261001'),
])
def test_calendar_invalid_rows_never_become_weekday_guesses(change):
    body = calendar(); change(body); value, _ = provider(body)
    with pytest.raises(module().MarketDataError, match='calendar_invalid'):
        value.fetch_calendar('2026-10-02', now=NOW)


@pytest.mark.parametrize('response,error', [
    (Response({'rt_cd': '0', 'output': []}, 503), 'kis_http_failure'),
    (Response({'rt_cd': '1', 'output': calendar()['output'], 'msg1': 'secret-token'}), 'kis_api_failure'),
    (Response({'output': calendar()['output']}), 'kis_api_failure'),
    (Response({'rt_cd': 0, 'output': calendar()['output']}), 'kis_api_failure'),
    (Response(ValueError('secret-token')), 'kis_payload_invalid'),
    (Response([]), 'kis_payload_invalid'), (RuntimeError('secret-token'), 'kis_transport_failure'),
])
def test_http_api_and_transport_failures_never_accept_success_shaped_output_or_leak(response, error, capsys):
    value = module().KISMarketProvider(request=Requests([response]))
    with pytest.raises(module().MarketDataError) as caught:
        value.fetch_calendar('2026-10-02', now=NOW)
    assert str(caught.value) == error and caught.value.code == error
    assert 'secret-token' not in capsys.readouterr().out+capsys.readouterr().err


def test_quote_uses_daily_open_and_timestamped_minute_close_not_minute_open():
    daily, bars = detail(), minutes(); before = deepcopy((daily, bars))
    value, calls = provider(daily, bars)
    result = value.fetch_quote('196170', now=NOW)
    assert result == dict(symbol='196170', price=104., opening_price=101.,
        quote_at='2026-10-06T00:05:00Z', fetched_at='2026-10-06T00:05:00Z',
        source='KIS:J:FHKST03010200+FHKST01010100')
    assert calls.calls == [('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
        dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD='196170')),
        ('/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice', 'FHKST03010200',
        dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD='196170', FID_INPUT_HOUR_1='090500',
             FID_PW_DATA_INCU_YN='N', FID_ETC_CLS_CODE=''))]
    assert (daily, bars) == before


def test_quote_chooses_newest_observation_independent_of_response_order_and_accepts_age120():
    bars = minutes(); bars['output2'].reverse()
    value, _ = provider(detail(), bars)
    assert value.fetch_quote('196170', now=NOW+timedelta(seconds=120))['quote_at'] == '2026-10-06T00:05:00Z'


@pytest.mark.parametrize('change,error', [
    (lambda b: b['output2'].clear(), 'quote_invalid'),
    (lambda b: b.update(output2={}), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_bsop_date='20261005'), 'quote_session_mismatch'),
    (lambda b: b['output2'][0].update(stck_bsop_date='20261007'), 'quote_session_mismatch'),
    (lambda b: b['output2'][0].update(stck_cntg_hour='090501'), 'quote_future'),
    (lambda b: b['output2'][0].update(stck_cntg_hour='246000'), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_cntg_hour=True), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_prpr=True), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_prpr='NaN'), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_prpr='Infinity'), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_prpr='0'), 'quote_invalid'),
    (lambda b: b['output2'][0].update(stck_shrn_iscd='005930'), 'quote_invalid'),
])
def test_invalid_future_wrong_session_or_nonfinite_minute_quote_holds(change, error):
    bars = minutes(); change(bars); value, _ = provider(detail(), bars)
    with pytest.raises(module().MarketDataError, match=error):
        value.fetch_quote('196170', now=NOW)


def test_stale_minute_cannot_be_recaptured_as_current_quote():
    value, _ = provider(detail(), minutes())
    with pytest.raises(module().MarketDataError, match='quote_stale'):
        value.fetch_quote('196170', now=NOW+timedelta(seconds=120, microseconds=1))


@pytest.mark.parametrize('change,error', [
    (lambda b: b['output'].update(stck_oprc='0'), 'quote_invalid'),
    (lambda b: b['output'].update(stck_oprc=False), 'quote_invalid'),
    (lambda b: b['output'].update(stck_prpr='nan'), 'quote_invalid'),
    (lambda b: b['output'].update(stck_shrn_iscd='005930'), 'quote_invalid'),
    (lambda b: b['output'].update(acml_vol='0'), 'quote_nontradable'),
    (lambda b: b['output'].update(temp_stop_yn='Y'), 'quote_nontradable'),
    (lambda b: b['output'].pop('temp_stop_yn'), 'quote_nontradable'),
    (lambda b: b['output'].update(temp_stop_yn=True), 'quote_nontradable'),
    (lambda b: b['output'].update(temp_stop_yn='unknown'), 'quote_nontradable'),
    (lambda b: b['output'].update(temp_stop_yn=None), 'quote_nontradable'),
])
def test_daily_open_identity_and_tradability_are_verified(change, error):
    daily = detail(); change(daily); value, _ = provider(daily, minutes())
    with pytest.raises(module().MarketDataError, match=error):
        value.fetch_quote('196170', now=NOW)


@pytest.mark.parametrize('symbol', [True, None, '123', 'ABCDEF', '000000', '196170?x=1'])
def test_invalid_symbol_is_rejected_before_request(symbol):
    value, calls = provider(detail(), minutes())
    with pytest.raises(module().MarketDataError, match='invalid_symbol'):
        value.fetch_quote(symbol, now=NOW)
    assert calls.calls == []


@pytest.mark.parametrize('now', [True, None, 'invalid', datetime(2026, 10, 6)])
def test_invalid_explicit_clock_is_rejected_before_request(now):
    value, calls = provider(calendar())
    # None uses the injected clock, which this fixture deliberately makes unaware.
    if now is None:
        value = module().KISMarketProvider(request=calls, clock=lambda: datetime(2026, 10, 6))
    with pytest.raises(module().MarketDataError, match='invalid_clock'):
        value.fetch_calendar('2026-10-02', now=now)
    assert calls.calls == []


def install_fake_kis(monkeypatch, *, responses, tokens=('test-token',)):
    calls, tokens = [], iter(tokens)
    responses = iter(responses)
    def http_get(url, **kwargs):
        calls.append(('get', url, kwargs['params'], kwargs['timeout']))
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result
    fake = SimpleNamespace(BASE_URL='https://fixture.invalid', get_token=lambda: next(tokens),
        _pace_api_request=lambda: calls.append(('pace',)), _http_get=http_get,
        _headers=lambda token, tr: {}, invalidate_token=lambda **kwargs: calls.append(('invalidate',)),
        _publish_shared_rate_limit_backoff=lambda delay: calls.append(('backoff', delay)),
        _rate_limit_backoff_seconds=lambda: 1.)
    monkeypatch.setattr(importlib.import_module('app.services'), 'kis_screener', fake, raising=False)
    monkeypatch.setitem(sys.modules, 'app.services.kis_screener', fake)
    return calls


def test_default_transport_reuses_shared_pacing_and_retries_expired_token_once(monkeypatch):
    calls = install_fake_kis(monkeypatch, responses=[Response({'rt_cd': '1'}, 401), Response(calendar())],
                            tokens=('test-old', 'test-new'))
    value = module().KISMarketProvider()
    assert value.fetch_calendar('2026-10-02', now=NOW)['days'][0]['is_open'] is True
    assert [row[0] for row in calls] == ['pace', 'get', 'invalidate', 'pace', 'get']
    assert all(row[-1] == 10 for row in calls if row[0] == 'get')


def test_default_transport_rate_failure_shares_backoff_but_does_not_loop(monkeypatch):
    calls = install_fake_kis(monkeypatch, responses=[Response(dict(rt_cd='1', msg_cd='EGW00201', msg1='secret-token'))])
    with pytest.raises(module().MarketDataError, match='kis_api_failure'):
        module().KISMarketProvider().fetch_calendar('2026-10-02', now=NOW)
    assert [row[0] for row in calls] == ['pace', 'get', 'backoff']


@pytest.mark.parametrize('tokens,responses,error', [
    ((None,), [], 'kis_token_unavailable'),
    (('test-token',), [RuntimeError('secret-token')], 'kis_transport_failure'),
    (('test-old', 'test-new'), [Response({}, 401), Response({}, 401)], 'kis_http_failure'),
])
def test_default_transport_missing_tokens_errors_and_repeat_expiry_are_bounded(monkeypatch, tokens, responses, error, capsys):
    calls = install_fake_kis(monkeypatch, responses=responses, tokens=tokens)
    with pytest.raises(module().MarketDataError) as caught:
        module().KISMarketProvider().fetch_calendar('2026-10-02', now=NOW)
    assert str(caught.value) == error
    assert sum(row[0] == 'get' for row in calls) <= 2
    captured = capsys.readouterr(); assert 'secret-token' not in captured.out+captured.err


def cli():
    path = ROOT/'scripts/run_alpha_lab_monitor.py'
    if not path.is_file():
        pytest.fail('The monitor CLI is missing')
    spec = importlib.util.spec_from_file_location('alpha_monitor_cli_fixture', path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class Monitor:
    def __init__(self, is_open=None, failed=False):
        self.is_open, self.failed, self.calls = is_open, failed, []

    def calendar_check(self, root, provider, now=None):
        self.calls.append(('calendar', root, provider, now))
        return dict(is_open=self.is_open, calendar_status='ready', market_state='closed', reasons=[])

    def run_monitor(self, root, provider, now=None):
        self.calls.append(('monitor', root, provider, now))
        if self.failed:
            raise RuntimeError('secret-token')
        return dict(schema_version=1, cadence=dict(market_state='closed', calendar_status='ready'),
                    monitoring=dict(status='held', quotes=[]))


@pytest.mark.parametrize('opened,code', [(True, 0), (False, 10), (None, 2)])
def test_cli_calendar_exit_codes_are_explicit_and_do_not_launch_research(tmp_path, capsys, opened, code):
    monitor = Monitor(opened); value = object()
    assert cli().main(['calendar-check', '--root', str(tmp_path)], provider=value, monitor_module=monitor, now=NOW) == code
    assert monitor.calls == [('calendar', tmp_path, value, NOW)]
    assert 'secret-token' not in capsys.readouterr().out


@pytest.mark.parametrize('mode', ['prime', 'tick'])
def test_cli_prime_tick_use_one_bounded_monitor_call(tmp_path, mode):
    monitor = Monitor(); value = object()
    assert cli().main([mode, '--root', str(tmp_path)], provider=value, monitor_module=monitor, now=NOW) == 0
    assert monitor.calls == [('monitor', tmp_path, value, NOW)]


def test_cli_failure_is_generic_and_never_prints_transport_text(tmp_path, capsys):
    assert cli().main(['tick', '--root', str(tmp_path)], provider=object(), monitor_module=Monitor(failed=True), now=NOW) == 2
    captured = capsys.readouterr()
    assert 'secret-token' not in captured.out+captured.err and 'monitor_unavailable' in captured.out


def test_actual_cli_keeps_unfrozen_clock_and_loads_only_project_env_before_provider(tmp_path, monkeypatch):
    calls, value, monitor = [], object(), Monitor()
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(load_dotenv=lambda path, **kwargs: calls.append(('env', path, kwargs))))
    monkeypatch.setattr(module(), 'KISMarketProvider', lambda: calls.append(('provider',)) or value)
    script = cli()
    assert script.main(['prime', '--root', str(tmp_path)], monitor_module=monitor) == 0
    assert calls == [('env', ROOT/'.env', {'override': False}), ('provider',)]
    assert monitor.calls == [('monitor', tmp_path, value, None)]


def test_refresh_checks_calendar_before_sources_and_installer_is_bounded():
    refresh = (ROOT/'scripts/refresh_alpha_lab.ps1').read_text(encoding='utf-8')
    installer = ROOT/'scripts/install_alpha_lab_tasks.ps1'
    assert 'calendar-check' in refresh and refresh.index('calendar-check') < refresh.index('& $pythonPath $collectorPath --fetch')
    assert '$calendarExit -eq 10' in refresh and '$calendarExit -ne 0' in refresh
    assert installer.is_file()
    text = installer.read_text(encoding='utf-8')
    for expected in ('20:30', '08:55', '09:00', 'PT5M', 'PT6H31M', 'IgnoreNew', 'WindowStyle Hidden'):
        assert expected in text
    assert '.Repetition = ' in text  # Daily trigger repetition starts null; initialize it first.
    assert 'Start-ScheduledTask' not in text  # Installation does not trigger a live cycle.
