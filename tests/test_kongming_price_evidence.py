"""Point-in-time KRX evidence with the native KIS wire contract."""
from datetime import datetime

import pytest


def ts(value):
    return datetime.fromisoformat(value)


def bar(hhmm, *, day='20261106', price='100', volume='10', symbol='005930'):
    return dict(stck_bsop_date=day, stck_cntg_hour=hhmm + '00', stck_prpr=price,
                cntg_vol=volume, stck_shrn_iscd=symbol)


def article(published='2026-11-06T14:31:02+09:00', received='2026-11-06T14:40:13+09:00'):
    return dict(published_at=published, first_seen_at=received, entities=[dict(symbol='005930')])


class Feed:
    def __init__(self, bars, *, missing_day=None, status=200):
        self.bars = bars
        self.missing_day = missing_day
        self.status = status
        self.calls = []

    def __call__(self, path, tr_id, params):
        self.calls.append((path, tr_id, params))
        if tr_id == 'CTCA0903R':
            rows = [('20261106', 'Y'), ('20261107', 'N'), ('20261108', 'N'), ('20261109', 'Y')]
            body = {'rt_cd': '0', 'output': [
                dict(bass_dt=day, tr_day_yn=is_open, opnd_yn=is_open)
                for day, is_open in rows if day != self.missing_day and day >= params['BASS_DT']
            ]}
        else:
            body = dict(rt_cd='0', output1={}, output2=self.bars)
        return Response(body, self.status if tr_id != 'CTCA0903R' else 200)


class Response:
    def __init__(self, body, status):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def provider(feed, *, now='2026-11-07T20:00:00+09:00', max_requests=6):
    try:
        from app.services.kongming_price_evidence import KongmingPriceProvider
    except ModuleNotFoundError as exc:
        if exc.name == 'app.services.kongming_price_evidence':
            pytest.fail('Independent article price evidence provider has not been implemented')
        raise
    return KongmingPriceProvider(request=feed, clock=lambda: ts(now), max_requests=max_requests)


def test_weekend_historical_krx_evidence_starts_after_publication_and_receipt():
    feed = Feed([bar('1510', price='110'), bar('1509', volume='0'), bar('1441'),
                 bar('1440', price='90'), bar('1432', price='70')])
    result = provider(feed).verify(article(), '005930')
    assert result['status'] == 'verified'
    assert result['source'] == 'KIS:J:FHKST03010230'
    assert result['calendar_source'] == 'KIS:CTCA0903R'
    assert result['session'] == '2026-11-06'
    assert result['reference_at'] == '2026-11-06T05:40:13Z'
    assert result['observed_at'] == '2026-11-06T05:41:00Z'
    assert result['fetched_at'] == '2026-11-07T11:00:00Z'
    assert result['latest_observed_at'] == '2026-11-06T06:10:00Z'
    assert (result['close'], result['latest_close'], result['change_pct']) == (100., 110., 10.)
    assert result['window_complete'] is True
    assert feed.calls[-1] == ('/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
                             'FHKST03010230', {'FID_COND_MRKT_DIV_CODE': 'J',
                                              'FID_INPUT_ISCD': '005930',
                                              'FID_INPUT_HOUR_1': '151000',
                                              'FID_INPUT_DATE_1': '20261106',
                                              'FID_PW_DATA_INCU_YN': 'N',
                                              'FID_FAKE_TICK_INCU_YN': ''})


def test_late_friday_news_waits_for_confirmed_monday_session():
    story = article(received='2026-11-06T15:30:00+09:00')
    saturday = Feed([])
    assert provider(saturday).verify(story, '005930')['status'] == 'awaiting_session'
    assert [call[1] for call in saturday.calls] == ['CTCA0903R']

    monday = Feed([bar('0900', day='20261109'), bar('0901', day='20261109', price='105'),
                   bar('0904', day='20261109', price='110')])
    result = provider(monday, now='2026-11-09T09:05:00+09:00').verify(story, '005930')
    assert result['status'] == 'verified'
    assert result['session'] == '2026-11-09'
    assert result['observed_at'] == '2026-11-09T00:01:00Z'
    assert result['latest_observed_at'] == '2026-11-09T00:04:00Z'
    assert result['window_complete'] is False


def test_missing_calendar_date_cannot_be_guessed_closed():
    feed = Feed([bar('0901', day='20261109')], missing_day='20261108')
    story = article(received='2026-11-06T15:30:00+09:00')
    result = provider(feed, now='2026-11-09T09:10:00+09:00').verify(story, '005930')
    assert result['status'] == 'calendar_unavailable'
    assert [call[1] for call in feed.calls] == ['CTCA0903R']


@pytest.mark.parametrize('bars', [
    [bar('1441', symbol='000660')], [bar('1441', day='20261105')],
    [bar('1441', price='nan')], [bar('1441'), bar('1441', price='200')],
])
def test_bad_kis_identity_or_prices_cannot_be_verified(bars):
    result = provider(Feed(bars)).verify(article(), '005930')
    assert result['status'] == 'source_unavailable'
    assert 'close' not in result


def test_no_post_receipt_positive_volume_never_becomes_price_evidence():
    result = provider(Feed([bar('1440'), bar('1441', volume='0')])).verify(article(), '005930')
    assert result['status'] == 'awaiting_post_receipt_data'
    assert result['window_complete'] is True
    assert 'close' not in result


def test_wrong_article_identity_and_naive_or_future_clocks_stop_before_io():
    feed = Feed([])
    lookup = provider(feed)
    assert lookup.verify(article(), '000660')['status'] == 'invalid_identity'
    assert lookup.verify(article(received='2026-11-06T14:42:00'), '005930')['status'] == 'invalid_identity'
    assert lookup.verify(article(received='2026-11-10T14:42:00+09:00'), '005930')['status'] == 'invalid_identity'
    assert feed.calls == []


def test_batch_reuses_successful_kis_page_and_defers_new_queries_at_budget():
    feed = Feed([bar('1441')])
    lookup = provider(feed, max_requests=2)
    assert lookup.verify(article(), '005930')['status'] == 'verified'
    assert lookup.verify(article(), '005930')['status'] == 'verified'
    assert lookup.verify(article(received='2026-11-06T14:42:00+09:00'), '005930')['status'] == 'deferred'
    assert len(feed.calls) == lookup.requests_used == 2


def test_kis_http_failure_is_bounded_and_does_not_retry_per_article():
    feed = Feed([], status=503)
    lookup = provider(feed)
    assert lookup.verify(article(), '005930')['reason'] == 'kis_http_failure'
    assert lookup.verify(article(), '005930')['reason'] == 'kis_http_failure'
    assert len(feed.calls) == 2


def test_krx_alphanumeric_issue_code_keeps_same_article_and_kis_identity():
    feed = Feed([bar('1441', symbol='0036R0')])
    story = article()
    story['entities'] = [dict(symbol='0036R0')]
    result = provider(feed).verify(story, '0036R0')
    assert result['status'] == 'verified'
    assert result['symbol'] == '0036R0'
    assert feed.calls[-1][2]['FID_INPUT_ISCD'] == '0036R0'


def test_calendar_attempt_persisted_across_worker_restart(tmp_path):
    from app.services.kongming_price_evidence import KongmingPriceProvider

    calendar_path = tmp_path / 'calendar.json'
    clock = lambda: ts('2026-11-07T20:00:00+09:00')
    first_feed = Feed([bar('1441')])
    first = KongmingPriceProvider(request=first_feed, clock=clock, calendar_path=calendar_path)
    assert first.verify(article(), '005930')['status'] == 'verified'
    assert calendar_path.is_file()

    restarted_feed = Feed([bar('1441')])
    restarted = KongmingPriceProvider(request=restarted_feed, clock=clock, calendar_path=calendar_path)
    assert restarted.verify(article(), '005930')['status'] == 'verified'
    assert [call[1] for call in restarted_feed.calls] == ['FHKST03010230']


def test_worker_death_cannot_repeat_reserved_daily_calendar_call(tmp_path):
    from app.services.kongming_price_evidence import KongmingPriceProvider

    calendar_path = tmp_path / 'calendar.json'
    clock = lambda: ts('2026-11-07T20:00:00+09:00')

    def stopped_before_response(path, tr_id, params):
        raise KeyboardInterrupt()

    first = KongmingPriceProvider(request=stopped_before_response, clock=clock,
                                  calendar_path=calendar_path)
    with pytest.raises(KeyboardInterrupt):
        first.verify(article(), '005930')

    restarted_feed = Feed([bar('1441')])
    restarted = KongmingPriceProvider(request=restarted_feed, clock=clock,
                                      calendar_path=calendar_path)
    assert restarted.verify(article(), '005930')['status'] == 'calendar_unavailable'
    assert restarted_feed.calls == []


def test_transient_calendar_failure_recovers_after_persisted_cooldown(tmp_path):
    from app.services.kongming_price_evidence import KongmingPriceProvider

    path = tmp_path / 'calendar.json'
    def unavailable(path, tr_id, params):
        return Response({}, 503)

    def batch(request, now):
        return KongmingPriceProvider(request=request, clock=lambda: ts(now), calendar_path=path)

    first = batch(unavailable, '2026-11-07T20:00:00+09:00').verify(article(), '005930')
    assert (first['status'], first['reason']) == ('calendar_unavailable', 'kis_http_failure')

    retry_feed = Feed([bar('1441')])
    early = batch(retry_feed, '2026-11-07T20:14:59+09:00').verify(article(), '005930')
    assert (early['status'], early['reason']) == ('calendar_unavailable', 'kis_http_failure')
    assert not retry_feed.calls

    recovered = batch(retry_feed, '2026-11-07T20:15:00+09:00').verify(article(), '005930')
    assert recovered['status'] == 'verified'
    assert [call[1] for call in retry_feed.calls] == ['CTCA0903R', 'FHKST03010230']


def test_failed_calendar_lookup_uses_at_most_two_attempts_per_day(tmp_path):
    from app.services.kongming_price_evidence import KongmingPriceProvider

    calls = []
    def unavailable(path, tr_id, params):
        calls.append(tr_id)
        return Response({}, 503)

    for clock in ['20:00:00', '20:15:00', '20:30:00']:
        batch = KongmingPriceProvider(request=unavailable, calendar_path=tmp_path / 'calendar.json',
                                    clock=lambda: ts(f'2026-11-07T{clock}+09:00'))
        assert batch.verify(article(), '005930')['reason'] == 'kis_http_failure'
    assert calls == ['CTCA0903R', 'CTCA0903R']


def test_valid_calendar_with_missing_coverage_does_not_retry_or_guess(tmp_path):
    from app.services.kongming_price_evidence import KongmingPriceProvider

    feed = Feed([bar('1441')], missing_day='20261106')
    for clock in ['20:00:00', '20:20:00']:
        batch = KongmingPriceProvider(request=feed, calendar_path=tmp_path / 'calendar.json',
                                    clock=lambda: ts(f'2026-11-07T{clock}+09:00'))
        result = batch.verify(article(), '005930')
        assert (result['status'], result['reason']) == ('calendar_unavailable', 'calendar_day_unconfirmed')
    assert [call[1] for call in feed.calls] == ['CTCA0903R']


def test_paper_mode_uses_official_krx_holiday_dates_and_actual_dated_minutes(tmp_path, monkeypatch):
    from app.services import kongming_price_evidence as evidence

    official = KrxCalendar()
    monkeypatch.setattr(evidence.requests, 'Session', lambda: official)
    feed = Feed([bar('0901', day='20261109')])
    story = article(published='2026-11-06T15:30:00+09:00', received='2026-11-06T15:32:00+09:00')
    worker = evidence.KongmingPriceProvider(
        request=feed, clock=lambda: ts('2026-11-09T09:05:00+09:00'),
        calendar_path=tmp_path / 'calendar.json', paper=True,
    )
    result = worker.verify(story, '005930')
    assert result['status'] == 'verified'
    assert result['calendar_source'] == 'KRX:official-holiday-schedule'
    assert result['session'] == '2026-11-09'
    assert [call[1] for call in feed.calls] == ['FHKST03010230']
    assert len(official.calls) == 2
    assert worker.requests_used == 3


def test_paper_mode_official_krx_holiday_can_skip_a_weekday(tmp_path, monkeypatch):
    from app.services import kongming_price_evidence as evidence

    official = KrxCalendar(closures=['2026-11-06'])
    monkeypatch.setattr(evidence.requests, 'Session', lambda: official)
    feed = Feed([bar('0901', day='20261109')])
    worker = evidence.KongmingPriceProvider(
        request=feed, clock=lambda: ts('2026-11-09T09:05:00+09:00'),
        calendar_path=tmp_path / 'calendar.json', paper=True,
    )
    result = worker.verify(article(), '005930')
    assert (result['status'], result['session']) == ('verified', '2026-11-09')


def test_paper_mode_krx_failure_uses_only_positive_same_date_index_evidence(tmp_path, monkeypatch):
    from app.services import kongming_price_evidence as evidence

    official = KrxCalendar(failure=True)
    monkeypatch.setattr(evidence.requests, 'Session', lambda: official)
    feed = IndexFeed([bar('1441')], traded=['20261106'])
    worker = evidence.KongmingPriceProvider(
        request=feed, clock=lambda: ts('2026-11-07T20:00:00+09:00'),
        calendar_path=tmp_path / 'calendar.json', paper=True,
    )
    result = worker.verify(article(), '005930')
    assert result['status'] == 'verified'
    assert result['calendar_source'] == 'KIS:KOSPI:FHKUP03500100'
    assert [call[1] for call in feed.calls] == ['FHKUP03500100', 'FHKST03010230']
    # Missing weekdays are unknown and must not be bypassed to reach Friday.
    wednesday = article('2026-11-04T11:00:00+09:00', '2026-11-04T11:01:00+09:00')
    assert worker.verify(wednesday, '005930')['status'] == 'calendar_unavailable'
    assert [call[1] for call in feed.calls] == ['FHKUP03500100', 'FHKST03010230']


class IndexFeed(Feed):
    def __init__(self, bars, *, traded):
        super().__init__(bars)
        self.traded = traded

    def __call__(self, path, tr_id, params):
        if tr_id != 'FHKUP03500100':
            return super().__call__(path, tr_id, params)
        self.calls.append((path, tr_id, params))
        return Response(dict(rt_cd='0', output1=dict(bstp_cls_code='0001'), output2=[
            dict(stck_bsop_date=day, acml_vol='100', bstp_nmix_prpr='5059.69') for day in self.traded
        ]), 200)


class KrxCalendar:
    def __init__(self, *, closures=(), failure=False):
        self.calls = []
        self.failure = failure
        self.closures = closures
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return KrxReply(503 if self.failure else 200, 'a' * 216)

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        year = kwargs['data']['search_bas_yy']
        return KrxReply(200, 'holiday-list', {'block1': [
            {'calnd_dd': day, 'calnd_dd_dy': day, 'holdy_nm': 'KRX holiday'}
            for day in (f'{year}-01-01', *self.closures, f'{year}-12-31')
        ]})


class KrxReply(Response):
    def __init__(self, status, text, body=None):
        super().__init__(body, status)
        self.text = text
        self.content = text.encode()
