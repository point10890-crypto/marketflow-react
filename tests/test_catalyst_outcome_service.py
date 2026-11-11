from datetime import datetime, timezone
import json
import pytest
from app.services.catalyst_outcomes import service as s

NOW=datetime(2026,11,11,2,tzinfo=timezone.utc)


def test_kst_twice_daily_slots_and_next_run():
    assert s.schedule(NOW)['slot']=='2026-11-11T10:00:00+09:00'
    assert s.schedule(NOW)['next_run_at']=='2026-11-11T15:00:00+09:00'
    assert s.schedule(datetime(2026,11,11,7,tzinfo=timezone.utc))['next_run_at']=='2026-11-12T10:00:00+09:00'


def test_saved_empty_read_does_not_create_any_files(tmp_path):
    assert s.read_view(root=tmp_path,now=NOW)['status']=='missing'
    assert list(tmp_path.iterdir())==[]


def test_completed_slot_is_not_recollected_and_get_does_not_write(tmp_path,monkeypatch):
    from app.services.catalyst_outcomes import sources,prices
    monkeypatch.setattr(sources,'load_events',lambda *args:([],{'status':'ready','source_counts':{}}))
    monkeypatch.setattr(prices,'load_closes',lambda *args:({}, {'status':'ready'}))
    monkeypatch.setattr(prices,'load_current_prices',lambda *args,**kwargs:({}, {'pending_symbols':0,'errors':{}}))
    s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)
    monkeypatch.setattr(sources,'load_events',lambda *args:pytest.fail('completed slot reloaded'))
    assert s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)['status']=='ready'
    before=(tmp_path/'outcomes.sqlite3').read_bytes()
    view=s.read_view(root=tmp_path,now=NOW)
    assert view['coverage']['events_total']==0 and view['cases']==[]
    assert (tmp_path/'outcomes.sqlite3').read_bytes()==before


def test_invalid_filter_rejected_without_reads(tmp_path):
    for args in [dict(page=0),dict(page_size=51),dict(filter='winner'),dict(symbol='../secrets')]:
        with pytest.raises(ValueError): s.read_view(root=tmp_path,now=NOW,**args)


def test_policy_change_does_not_rewrite_completed_results(tmp_path,monkeypatch):
    from app.services.catalyst_outcomes import sources,prices
    monkeypatch.setattr(sources,'load_events',lambda *args:([],{'status':'ready','source_counts':{}}))
    monkeypatch.setattr(prices,'load_closes',lambda *args:({}, {'status':'ready'}))
    initial=s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)
    monkeypatch.setattr(s.analytics,'POLICY','different-policy')
    later=datetime(2026,11,11,7,tzinfo=timezone.utc)
    result=s.run_once(root=tmp_path,project_root=tmp_path,now=later)
    assert result['status']=='failed' and result['generated_at']==initial['generated_at']


def test_fully_read_upstream_partial_is_published_once_per_slot(tmp_path,monkeypatch):
    from app.services.catalyst_outcomes import sources,prices
    monkeypatch.setattr(sources,'load_events',lambda *args:([],{'status':'partial','source_counts':{},
        'sources':{'surge_trace':{'status':'partial','error':'upstream_partial'}}}))
    monkeypatch.setattr(prices,'load_closes',lambda *args:({}, {'status':'ready'}))
    initial=s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)
    assert initial['status']=='partial' and initial['operation']['state']=='complete_with_gaps'
    monkeypatch.setattr(sources,'load_events',lambda *args:pytest.fail('completed slot reacquired'))
    again=s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)
    assert again['generated_at']==initial['generated_at'] and again['status']=='partial'


def test_failed_refresh_keeps_previous_snapshot_but_marks_failure(tmp_path,monkeypatch):
    from app.services.catalyst_outcomes import sources,prices
    monkeypatch.setattr(sources,'load_events',lambda *args:([],{'status':'ready','source_counts':{}}))
    monkeypatch.setattr(prices,'load_closes',lambda *args:({}, {'status':'ready'}))
    monkeypatch.setattr(prices,'load_current_prices',lambda *args,**kwargs:({}, {'pending_symbols':0,'errors':{}}))
    s.run_once(root=tmp_path,project_root=tmp_path,now=NOW)
    monkeypatch.setattr(sources,'load_events',lambda *args:(_ for _ in ()).throw(ValueError('private error')))
    later=datetime(2026,11,11,7,tzinfo=timezone.utc)
    result=s.run_once(root=tmp_path,project_root=tmp_path,now=later)
    assert result['status']=='failed' and 'private error' not in json.dumps(result)
    assert result['generated_at']==NOW.astimezone(s.KST).isoformat()


def test_reconcile_syndication_preserves_first_receipt_and_withdrawals():
    from app.services.catalyst_outcomes.sources import event_keys
    old=dict(id='first',symbol='005930',name='삼성전자',title='삼성전자 공급 계약',url='https://example.com/first',
             published_at='2026-10-01T08:00:00+09:00',first_seen_at='2026-10-01T10:00:00+09:00',
             anchor_at='2026-10-01T10:00:00+09:00',analysis_basis='received')
    new={**old,'id':'second','url':'https://example.com/second','first_seen_at':'2026-10-02T10:00:00+09:00',
         'anchor_at':'2026-10-02T10:00:00+09:00'}
    rows=s._reconcile({'first':old},[new],{'identity_aliases':{'second':event_keys(new)}},[])
    assert len(rows)==1 and rows[0]['id']=='first' and rows[0]['anchor_at']==old['anchor_at']
    withdrawn=s._reconcile({'first':rows[0]},[],{},[['005930','url',new['url']]])
    assert withdrawn[0]['exclusion']=='withdrawn'


@pytest.mark.parametrize('title,correction',[
    ('삼성전자 공급 계약','삼성전자 공급 계약 정정'),
    ('삼성전자 영업이익 -100억','삼성전자 영업이익 +100억'),
    ('삼성전자 공급 계약 1.0조','삼성전자 공급 계약 10조'),
])
def test_same_article_rewrite_does_not_replace_original_claim(title,correction):
    old=dict(id='first',symbol='005930',name='삼성전자',title=title,url='https://example.com/first',
             source='omni',event_type='contract',published_at='2026-10-01T08:00:00+09:00',
             first_seen_at='2026-10-01T10:00:00+09:00',anchor_at='2026-10-01T10:00:00+09:00',analysis_basis='received')
    changed={**old,'title':correction,'published_at':'2026-10-02T08:00:00+09:00'}
    row=s._reconcile({'first':old},[changed],{},[])[0]
    assert row['title']==old['title'] and row['published_at']==old['published_at']
    assert row['exclusion']=='source_revised'
