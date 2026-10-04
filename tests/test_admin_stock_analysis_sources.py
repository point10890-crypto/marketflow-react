"""Source acquisition is per-target, cached-first, and never part of GET."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

from tests.test_admin_stock_analysis import snapshot, NOW


def source_module():
    from app.services.mirofish.alpha_lab import symbol_sources
    return symbol_sources


def test_current_canonical_symbol_reuses_snapshot_and_whole_calendar_without_collection(monkeypatch,tmp_path):
    from app.services.mirofish.alpha_lab import service
    source=source_module();data=snapshot();other=deepcopy(data['prices_by_symbol']['196170'])
    for row in other:row['symbol']='005930'
    data['prices_by_symbol']['005930']=other;data['names']['005930']='삼성전자'
    saved_report=dict(schema_version=1,mode='research',input_fingerprint=data['input_fingerprint'],
        decision_at=data['decision_at'],latest_session=data['latest_session'],provenance=data['provenance'],
        opportunity_scan=dict(audit_hash='b'*64),proposal_window=data['proposal_window'])
    monkeypatch.setattr(service,'resolve_inputs',lambda root:('prices','manifest','scope'))
    monkeypatch.setattr(service,'load_inputs',lambda *args,**kwargs:deepcopy(data))
    monkeypatch.setattr(service,'read_status',lambda:dict(state='held',report=saved_report))
    monkeypatch.setattr(source,'_collect',lambda *args,**kwargs:pytest.fail('fresh cached symbols must not collect'))
    result=source.acquire_inputs(dict(symbol='196170',name='알테오젠',market='KR'),root=tmp_path,now=NOW)
    assert result['source_mode']=='saved_snapshot'
    assert set(result['prices_by_symbol'])=={'196170'}
    assert result['reference_calendar']==data['reference_calendar']
    assert result['quality']['status']=='passed'
    assert result['proposal_window']['valid_until']=='2026-10-05T06:30:00Z'


def test_fresh_price_snapshot_can_obtain_its_own_official_window(monkeypatch,tmp_path):
    from app.services.mirofish.alpha_lab import service
    source=source_module();data=snapshot();data.pop('proposal_window')
    monkeypatch.setattr(service,'resolve_inputs',lambda root:('prices','manifest','scope'))
    monkeypatch.setattr(service,'load_inputs',lambda *args,**kwargs:deepcopy(data))
    monkeypatch.setattr(service,'read_status',lambda:dict(state='missing',report=None))
    calendar=dict(source='KIS:CTCA0903R',captured_at=NOW,days=[dict(date='2026-10-03',is_open=False),
        dict(date='2026-10-04',is_open=False),dict(date='2026-10-05',is_open=True)])
    check=Mock(return_value=(calendar,'2026-10-02'));monkeypatch.setattr(source,'_calendar',check)
    result=source.acquire_inputs(dict(symbol='196170',name='알테오젠',market='KR'),root=tmp_path,now=NOW)
    assert result['proposal_window']['valid_until']=='2026-10-05T06:30:00Z'
    assert result['source_mode']=='saved_snapshot' and check.call_count==1


def test_new_verified_closed_session_failure_does_not_silently_reuse_old_prices(monkeypatch,tmp_path):
    from app.services.mirofish.alpha_lab import service
    source=source_module();data=snapshot();data.pop('proposal_window')
    monkeypatch.setattr(service,'resolve_inputs',lambda root:('prices','manifest','scope'))
    monkeypatch.setattr(service,'load_inputs',lambda *args,**kwargs:deepcopy(data))
    monkeypatch.setattr(service,'read_status',lambda:dict(state='missing',report=None))
    monkeypatch.setattr(source,'_calendar',lambda now:({},'2026-10-05'))
    def failed(*args,**kwargs):raise RuntimeError('new-price-fetch-failed')
    monkeypatch.setattr(source,'_collect',failed)
    with pytest.raises(RuntimeError):
        source.acquire_inputs(dict(symbol='196170',name='알테오젠',market='KR'),root=tmp_path,now='2026-10-05T08:00:00Z')


def test_targeted_cache_revalidates_calendar_on_a_new_day_and_holds_if_unavailable(monkeypatch,tmp_path):
    source=source_module();data=snapshot();data['source_mode']='targeted_collection'
    data['official_calendar']=dict(source='KIS:CTCA0903R',captured_at='2026-10-03T00:00:00Z',
        days=[dict(date='2026-10-02',is_open=True),dict(date='2026-10-03',is_open=False),dict(date='2026-10-04',is_open=False),dict(date='2026-10-05',is_open=True)])
    source.store._write(tmp_path/'sources'/'inputs.json',dict(inputs=data,sha256=source.store._hash(data)))
    monkeypatch.setattr(source,'_canonical',lambda now:None)
    monkeypatch.setattr(source,'_collect',lambda *args,**kwargs:pytest.fail('price stage is already complete'))
    check=Mock(side_effect=ValueError('calendar_unavailable'));monkeypatch.setattr(source,'_calendar',check)
    result=source.acquire_inputs(dict(symbol='196170',name='알테오젠',market='KR'),root=tmp_path,now=NOW)
    assert result['status']=='held' and 'official_calendar_unavailable' in result['reasons']
    assert check.call_count==1 and result['prices_by_symbol']==data['prices_by_symbol']


def test_missing_symbol_collects_only_exact_target_and_stale_cached_source_never_falls_back(monkeypatch,tmp_path):
    from app.services.mirofish.alpha_lab import service
    source=source_module();data=snapshot();data['provenance']['captured_at']='2026-09-01T00:00:00Z'
    monkeypatch.setattr(service,'resolve_inputs',lambda root:('prices','manifest','scope'))
    monkeypatch.setattr(service,'load_inputs',lambda *args,**kwargs:deepcopy(data))
    collect=Mock(return_value=dict(marker='targeted'))
    monkeypatch.setattr(source,'_collect',collect)
    target=dict(symbol='080580',name='오킨스전자',market='KR')
    assert source.acquire_inputs(target,root=tmp_path,now=NOW)==dict(marker='targeted')
    assert collect.call_args.args[0]==target
    collect.side_effect=RuntimeError('failed-private-transport')
    with pytest.raises(RuntimeError):source.acquire_inputs(target,root=tmp_path,now=NOW)


def test_identity_resolution_requires_exact_known_kr_code(monkeypatch):
    from app.services.mirofish import live_data
    from app.services.mirofish.alpha_lab import symbol_analysis
    monkeypatch.setattr(live_data,'_load_ticker_map',lambda:{'196170':dict(name='알테오젠',market='KOSDAQ'),
        '123456':dict(name='US',market='NASDAQ')})
    assert symbol_analysis.resolve_target('196170')['market']=='KR'
    for value in ('999990','123456','000000','196170 ','../123','１９６１７０',196170):
        with pytest.raises(ValueError):symbol_analysis.resolve_target(value)


def test_semantically_identical_recapture_preserves_original_window(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    from app.services.mirofish.alpha_lab import symbol_analysis as mod
    controlled(monkeypatch);data=snapshot()
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    data['input_fingerprint']='c'*64;data['decision_at']='2026-10-05T08:00:00Z'
    data['provenance']['captured_at']='2026-10-05T07:00:00Z'
    data['proposal_window'].update(input_fingerprint='c'*64,origin_at=data['decision_at'],entry_session='2026-10-06',valid_until='2026-10-06T06:30:00Z')
    second=mod.analyze_once('196170',root=tmp_path,now='2026-10-05T08:00:00Z')
    assert second['result']['candidate']['proposal']['valid_until']==first['result']['candidate']['proposal']['valid_until']
    assert second['result']['candidate']['proposal']['proposed_weight']==0.


def test_completed_price_stage_is_reused_when_dart_stage_failed(monkeypatch,tmp_path):
    source=source_module()
    from app.services.mirofish.alpha_lab import store
    params=dict(symbol='080580',requestType='1',startTime='20050101',endTime='20261002',timeframe='day')
    prices=SimpleNamespace(fetch_payload=Mock(return_value=dict(payload=b'raw-bars',captured_at=NOW,http_status=200)),atomic_write=lambda path,payload:(path.parent.mkdir(parents=True,exist_ok=True),path.write_bytes(payload)))
    first=source._price_capture(prices,'080580',params,tmp_path,NOW)
    second=source._price_capture(prices,'080580',params,tmp_path,NOW)
    assert second['payload']==first['payload'] and prices.fetch_payload.call_count==1


@pytest.mark.parametrize('listing_failure',[False,True])
def test_targeted_collection_scopes_history_listing_financials_and_public_provenance(monkeypatch,tmp_path,listing_failure):
    source=source_module();data=snapshot();rows=data['prices_by_symbol']['196170']
    prices=SimpleNamespace(PRICE_BASIS='provider_reported_unverified',SOURCE='naver_sise_json_public',
        fetch_payload=Mock(return_value=dict(payload=b'raw-bars',captured_at=NOW,http_status=200)),
        parse_payload=lambda *args:dict(bars=rows),
        atomic_write=lambda path,payload:(path.parent.mkdir(parents=True,exist_ok=True),path.write_bytes(payload)))
    listing=tmp_path/'listing.csv';listing.write_text('test')
    row=dict(symbol='196170',name='알테오젠',market='KOSDAQ',date='2026-10-02',source='dated_KRX_listing_input',
        market_cap=1e12,volume=1000.,share_type='common')
    financial=dict(symbol='196170',available_date='2026-08-14',period_end='2026-06-30',source='OpenDART',
        fs_div='CFS',fetched_at=NOW,equity=100.,liabilities=50.,net_income=10.,operating_profit=12.)
    screen=SimpleNamespace(fetch_listing=Mock(return_value=listing),load_listing=lambda *args:([row],{}),
        fetch_financials=Mock(return_value=([financial],dict(fetched_at_by_batch=[NOW]))))
    if listing_failure:screen.fetch_listing.side_effect=RuntimeError('private source body')
    refresh=SimpleNamespace(_period=lambda *args:(2026,'11012'),latest_closed_weekday=lambda now:'2026-10-02')
    modules={'scripts.collect_large_cap_price_history':prices,'scripts.screen_large_cap_kelly':screen,
             'scripts.refresh_alpha_lab_inputs':refresh}
    monkeypatch.setattr(source,'import_module',lambda name:modules[name])
    from datetime import date,timedelta
    start=date(2026,9,24)
    calendar=dict(source='KIS:CTCA0903R',captured_at=NOW,days=[dict(date=(start+timedelta(days=i)).isoformat(),
        is_open=(start+timedelta(days=i)).weekday()<5) for i in range(20)])
    monkeypatch.setattr(source,'_calendar',lambda now:(calendar,'2026-10-02'))
    monkeypatch.setattr(source.store,'timestamp',lambda now=None:NOW)
    result=source._collect(dict(symbol='196170',name='알테오젠',market='KR'),root=tmp_path,now=NOW,canonical=data)
    assert result['source_mode']=='targeted_collection' and set(result['prices_by_symbol'])=={'196170'}
    assert result['quality']['status']==('unavailable' if listing_failure else 'passed')
    assert result['provenance']['analysis_ready'] is False
    assert result['universe']['selection']=='administrator_selected_symbol'
    if listing_failure:screen.fetch_financials.assert_not_called()
    else:assert screen.fetch_financials.call_args.args[0]=={'196170'}
    assert prices.fetch_payload.call_args.args[0]=='196170'
    assert result['proposal_window']['valid_until']=='2026-10-05T06:30:00Z'
    assert result['prices_by_symbol']['196170'][-1]['close']==100.
    assert 'private source body' not in str(result)


def test_worker_limit_rejects_other_symbols_without_publishing_false_running(monkeypatch,tmp_path):
    from filelock import FileLock
    from app.services.mirofish.alpha_lab import symbol_analysis as mod
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name=symbol,market='KR'))
    with FileLock(str(tmp_path/'analysis.lock'),thread_local=False).acquire(timeout=0):
        result=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert result['state']=='failed' and result['error']=='analysis_busy' and result['result'] is None
    assert not (tmp_path/'196170'/'status.json').exists()


def test_busy_reanalysis_keeps_prices_but_suppresses_saved_buy(monkeypatch,tmp_path):
    from filelock import FileLock
    from tests.test_alpha_lab_discovery import controlled
    from app.services.mirofish.alpha_lab import symbol_analysis as mod
    controlled(monkeypatch)
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:snapshot())
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert first['result']['candidate']['proposal']['action']=='buy'
    with FileLock(str(tmp_path/'analysis.lock'),thread_local=False).acquire(timeout=0):
        busy=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert busy['result']['candidate']['proposal']['action']=='wait'
    assert busy['result']['candidate']['proposal']['proposed_weight']==0.
    assert busy['result']['candidate']['plan']==first['result']['candidate']['plan']
