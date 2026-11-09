from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.mirofish.alpha_lab.regular_source import (
    KISRegularProvider, RegularSourceError, SOURCE_CONTRACT, replay,
)

DAY = '2026-11-10'
NOW = datetime(2026, 11, 10, 11, 31, tzinfo=timezone.utc)


def _row(hms, **updates):
    return dict(dict(stck_bsop_date='20261110', stck_cntg_hour=hms,
                     stck_oprc='100', stck_hgpr='103', stck_lwpr='99',
                     stck_prpr='102', cntg_vol='5', acml_tr_pbmn='10000',
                     irrelevant='secret-test-marker'), **updates)


def _pages():
    opened = datetime.fromisoformat(f'{DAY}T09:00:00')
    regular = [_row((opened + timedelta(minutes=i)).strftime('%H%M%S')) for i in range(380)]
    regular[0].update(stck_oprc='101')
    regular[10].update(stck_hgpr='105')
    regular[200].update(stck_lwpr='98')
    rows = [_row('153000', stck_prpr='103'), *reversed(regular),
            _row('085900', stck_hgpr='1000')]
    return [rows[i:i+120] for i in range(0, len(rows), 120)]


def _provider(pages, *, now=NOW, round_cursor=False):
    requests = []
    iterator = iter(pages)

    def request(path, tr, params):
        requests.append((path, tr, dict(params)))
        rows = next(iterator)
        if round_cursor:
            cursor = datetime.strptime(params['FID_INPUT_HOUR_1'], '%H%M%S')
            if cursor.second:
                cursor = cursor.replace(second=0) + timedelta(minutes=1)
            rows = [row for page in pages for row in page
                    if row['stck_cntg_hour'] <= cursor.strftime('%H%M%S')][:120]
        return SimpleNamespace(status_code=200, json=lambda: dict(rt_cd='0',
            output1=dict(stck_shrn_iscd='005930', other='secret-test-marker'),
            output2=rows, other='secret-test-marker'))

    return KISRegularProvider(request=request, clock=lambda: now), requests


def test_four_page_regular_bar_ignores_preopen_and_replays():
    provider, calls = _provider(_pages())
    result = provider.fetch_session('005930', DAY)
    assert result['bar'] == dict(open=101, high=105, low=98, close=103,
                                 volume=1905, traded_value=10000)
    assert result['source'] == SOURCE_CONTRACT
    assert [p['FID_INPUT_HOUR_1'] for _, _, p in calls] == ['153000', '132000', '112000', '092000']
    assert calls[0] == (
        '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
        'FHKST03010230',
        dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD='005930',
             FID_INPUT_DATE_1='20261110', FID_INPUT_HOUR_1='153000',
             FID_PW_DATA_INCU_YN='N', FID_FAKE_TICK_INCU_YN=''),
    )
    assert 'secret-test-marker' not in repr(result)
    assert replay(result, '005930', DAY, NOW) == result


def test_pagination_uses_minute_cursors_for_kis_rounding():
    provider, _ = _provider(_pages(), round_cursor=True)
    result = provider.fetch_session('005930', DAY)
    observed = [row['stck_cntg_hour'] for page in result['pages']
                for row in page['response']['output2'] if row['stck_cntg_hour'] >= '090000']
    assert observed == ['153000', *(
        (datetime.fromisoformat(f'{DAY}T15:19:00') - timedelta(minutes=i)).strftime('%H%M%S')
        for i in range(380)
    )]


@pytest.mark.parametrize('edit', [
    lambda p: p[0].pop(0),
    lambda p: p[-1].pop(-2),
    lambda p: p[0][0].update(cntg_vol='0'),
    lambda p: p[0][0].update(stck_bsop_date='20261111'),
    lambda p: p[0][0].update(stck_cntg_hour='195900'),
    lambda p: p[0][0].update(stck_hgpr='NaN'),
    lambda p: p[1].__setitem__(0, deepcopy(p[0][-1])),
    lambda p: p[0].__setitem__(1, dict(p[0][0], stck_prpr='100')),
    lambda p: p.__setitem__(1, []),
])
def test_rejects_unsafe_provider_pages(edit):
    pages = _pages()
    edit(pages)
    provider, _ = _provider(pages)
    with pytest.raises(RegularSourceError):
        provider.fetch_session('005930', DAY)


@pytest.mark.parametrize('edit', [
    lambda r: r['source'].update(market='UN'),
    lambda r: r['bar'].update(close=102),
    lambda r: r['pages'][1]['params'].update(FID_INPUT_HOUR_1='130059'),
    lambda r: r['pages'][1]['params'].update(FID_INPUT_DATE_1='20261109'),
    lambda r: r['pages'][1]['response']['output2'][0].update(stck_lwpr='1'),
    lambda r: r['pages'][1].update(captured_at='2026-11-10T11:29:00Z'),
    lambda r: r['pages'].pop(0),
    lambda r: r['capture'].update(last='2026-11-10T12:00:00Z'),
])
def test_replay_rejects_mutated_evidence(edit):
    provider, _ = _provider(_pages())
    result = provider.fetch_session('005930', DAY)
    edit(result)
    with pytest.raises(RegularSourceError):
        replay(result, '005930', DAY, NOW)


def test_rejects_capture_before_buffer_without_request():
    provider, calls = _provider(_pages(), now=NOW - timedelta(minutes=2))
    with pytest.raises(RegularSourceError):
        provider.fetch_session('005930', DAY)
    assert not calls
