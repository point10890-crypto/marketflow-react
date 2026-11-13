from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.forecast_league import regular_vi

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def result(*, delayed=True, vi=True, symbol='005930', session='2026-11-12', now=NOW):
    close = '153200' if delayed else '153000'
    def row(hour, price, low=None, high=None):
        return dict(stck_bsop_date=session.replace('-', ''), stck_cntg_hour=hour,
                    stck_oprc=str(price), stck_prpr=str(price), stck_lwpr=str(low or price),
                    stck_hgpr=str(high or price), cntg_vol='10')
    def request(path, tr, params):
        if tr == 'FHPST01390000':
            body = {'rt_cd': '0', 'output': [dict(mksc_shrn_iscd=symbol, bsop_date=session.replace('-', ''),
                    vi_cls_code='N', cntg_vi_hour='153002', vi_cncl_hour='153217')] if vi else []}
        else:
            body = {'rt_cd': '0', 'output1': {'stck_shrn_iscd': symbol},
                    'output2': [row(close, 105), row('151900', 100), row('090000', 100, 95, 110)]}
        return SimpleNamespace(status_code=200, json=lambda: body)
    return regular_vi.LeagueRegularProvider(request=request, clock=lambda: now).fetch_session(symbol, session)


def test_vi_release_auction_is_replayed_without_afterhours():
    value = result()
    assert value['bar']['close'] == 105
    assert value['closing_time'] == '153200'
    assert regular_vi.replay(value, '005930', '2026-11-12', NOW) == value


def test_normal_close_needs_no_vi_request():
    assert result(delayed=False)['vi'] is None


def test_late_print_without_matching_vi_is_rejected():
    with pytest.raises(ValueError):
        result(vi=False)


@pytest.mark.parametrize('change', ['price', 'symbol', 'release', 'early_capture', 'afterhours'])
def test_changed_evidence_cannot_replay(change):
    value = deepcopy(result())
    if change == 'price':
        value['bar']['close'] += 1
    elif change == 'symbol':
        value['vi']['response']['output'][0]['mksc_shrn_iscd'] = '000660'
    elif change == 'release':
        value['vi']['response']['output'][0]['vi_cncl_hour'] = '153317'
    elif change == 'early_capture':
        value['capture']['first'] = '2026-11-12T10:00:00Z'
    else:
        value['pages'][0]['response']['output2'][0]['stck_cntg_hour'] = '160000'
    with pytest.raises(ValueError):
        regular_vi.replay(value, '005930', '2026-11-12', NOW)


def test_announced_late_session_uses_its_actual_open_and_close():
    session = '2026-11-19'
    now = datetime(2026, 11, 19, 12, tzinfo=timezone.utc)
    def request(path, tr, params):
        assert params['FID_INPUT_HOUR_1'] == '163900'
        rows = [dict(stck_bsop_date='20261119', stck_cntg_hour=t, stck_oprc='100',
                     stck_prpr='100', stck_hgpr='100', stck_lwpr='100', cntg_vol='10')
                for t in ['163000', '161900', '100000']]
        return SimpleNamespace(status_code=200, json=lambda: {'rt_cd':'0','output1':{},'output2':rows})
    value = regular_vi.LeagueRegularProvider(request=request, clock=lambda: now).fetch_session('005930', session)
    assert value['closing_time'] == '163000'
    assert regular_vi.replay(value, '005930', session, now) == value
