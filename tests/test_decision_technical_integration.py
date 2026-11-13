from copy import deepcopy
from types import SimpleNamespace
import pytest
from flask import Flask

from app.services.mirofish import decision_brief as brief, decision_cache, decision_jobs


def envelope(symbol='005930', status='pending'):
    return dict(schema_version=1, agent='volume_profile_20d_v1', symbol=symbol,
                market='KR', status=status, profile=None, summary='매물대 확인',
                observations=[], independent_evidence=False)


@pytest.fixture
def runtime(monkeypatch):
    from app.routes.kr_market import kr_bp
    from app.auth import decorators
    from app.services.mirofish import decision_technical as technical
    from app.services.mirofish.kongming_technical import service
    app = Flask('decision-technical-test')
    app.config.update(TESTING=True, SECRET_KEY='test-only')
    app.register_blueprint(kr_bp, url_prefix='/api/kr')
    user = SimpleNamespace(id=5, status='approved', is_admin=True, is_aibain_active=False,
                           is_kongming_active=False)
    monkeypatch.setattr(decorators, '_get_current_user', lambda: user)
    monkeypatch.setattr(brief, 'resolve_symbol', lambda raw: ({'삼성전자':'005930'}.get(raw, str(raw).upper()), None))
    monkeypatch.setattr(decision_cache, 'cache_get', lambda *a, **kw: None)
    monkeypatch.setattr(decision_cache, 'cache_put', lambda *a, **kw: None)
    monkeypatch.setattr(technical, 'read_analysis', lambda code, **kw: envelope(code))
    monkeypatch.setattr(service, 'enqueue', lambda code: dict(schema_version=1, symbol=code, status='queued'))
    return app.test_client(), user, technical, service


@pytest.mark.parametrize('path,kind', [('/005930','brief'),('/005930/analyze','deep')])
def test_cached_decision_attaches_current_profile_without_mutating_result(runtime, monkeypatch, path, kind):
    client, _, technical, _ = runtime
    original = dict(symbol='005930', status='watch', signals=[{'source':'price'}], confidence_cap=.7,
                    technical_analysis=envelope(status='ready'),
                    technical_profile_used={'fingerprint':'original-generation'})
    before = deepcopy(original)
    monkeypatch.setattr(decision_cache, 'cache_get', lambda *a, **kw: original)
    monkeypatch.setattr(technical, 'read_analysis', lambda code, **kw: envelope(code, 'stale'))
    response=client.open('/api/kr/decision'+path, method='GET' if kind=='brief' else 'POST', json={} if kind=='deep' else None)
    assert response.status_code == 200
    assert response.json['technical_analysis']['status'] == 'stale'
    assert response.json['technical_profile_used'] == original['technical_profile_used']
    assert response.json['signals'] == before['signals'] and response.json['confidence_cap'] == .7
    assert original == before


@pytest.mark.parametrize('in_memory', [True, False])
def test_completed_job_current_profile_is_separate_from_immutable_analysis(runtime, monkeypatch, in_memory):
    client, _, _, _ = runtime
    old = dict(symbol='005930', verdict={'verdict':'HOLD'})
    status = dict(state='done', payload=old) if in_memory else dict(state='none')
    before=deepcopy(status)
    monkeypatch.setattr(decision_jobs, 'status', lambda key: status)
    monkeypatch.setattr(decision_cache, 'cache_get', lambda *a, **kw: old)
    response=client.get('/api/kr/decision/005930/analyze/status')
    assert response.json['payload']['technical_analysis']['symbol'] == '005930'
    assert 'technical_profile_used' not in response.json['payload']
    assert status == before and 'technical_analysis' not in old


def test_uncached_route_includes_profile_when_builder_is_older(runtime, monkeypatch):
    client, _, _, _ = runtime
    monkeypatch.setattr(brief,'build_decision_brief', lambda s: {'symbol':s,'signals':[],'errors':{}})
    response=client.get('/api/kr/decision/005930')
    assert response.json['technical_analysis']['symbol'] == '005930'


def test_partial_background_sources_do_not_poison_daily_cache(runtime, monkeypatch):
    client, _, _, _ = runtime
    writes=[]
    monkeypatch.setattr(decision_cache, 'cache_put', lambda *a, **kw: writes.append(a))
    monkeypatch.setattr(brief, 'build_decision_brief', lambda s: {
        'symbol':s, 'signals':[{'source':'price'}],
        'errors':{'scanner':'SnapshotPending: scanner_snapshot_refresh_pending'},
        'pending_sources':['scanner'],
    })
    response=client.get('/api/kr/decision/005930')
    assert response.status_code==200
    assert response.json['technical_analysis']['symbol']=='005930'
    assert writes==[]


@pytest.mark.parametrize('role,code', [('admin',200),('ai',200),('bundle',200),('none',403),('blocked',403),('anonymous',401)])
@pytest.mark.parametrize('method', ['GET','POST'])
def test_profile_endpoint_follows_decision_access(runtime, monkeypatch, role, code, method):
    client, user, _, _ = runtime
    from app.auth import decorators
    user.is_admin=role=='admin';user.is_aibain_active=role in ('ai','blocked');user.is_kongming_active=role=='bundle'
    if role=='blocked': user.status='suspended'
    if role=='anonymous': monkeypatch.setattr(decorators,'_get_current_user',lambda:None)
    response=client.open('/api/kr/decision/005930/technical-profile',method=method,json={} if method=='POST' else None)
    assert response.status_code == (202 if code==200 and method=='POST' else code)
    if code==200:
        assert response.json['symbol']=='005930'
        assert 'no-store' in response.headers['Cache-Control']


def test_profile_get_never_enqueues_or_runs_analysis(runtime, monkeypatch):
    client, _, _, service = runtime
    monkeypatch.setattr(service,'enqueue',lambda *a,**kw:pytest.fail('GET cannot enqueue'))
    monkeypatch.setattr(brief,'build_decision_brief',lambda *a,**kw:pytest.fail('No full-source fanout'))
    monkeypatch.setattr(decision_jobs,'start',lambda *a,**kw:pytest.fail('No LLM'))
    assert client.get('/api/kr/decision/005930/technical-profile').status_code==200


@pytest.mark.parametrize('path,body', [('/AAPL/technical-profile',{}),('/005930/technical-profile?force=1',{}),('/005930/technical-profile',{'force':True})])
def test_invalid_profile_queue_does_not_acquire(runtime, monkeypatch, path, body):
    client, _, _, service=runtime
    monkeypatch.setattr(service,'enqueue',lambda *a,**kw:pytest.fail('Invalid queue request'))
    assert client.post('/api/kr/decision'+path,json=body).status_code==400


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_profile_rejects_blank_code(runtime, method):
    client, _, _, _ = runtime
    response = client.open('/api/kr/decision/%20/technical-profile', method=method,
                           json={} if method == 'POST' else None)
    assert response.status_code == 400


def test_profile_queue_failure_is_bounded(runtime, monkeypatch):
    client, _, _, service=runtime
    def fail(*a,**kw): raise OSError('private path and credentials')
    monkeypatch.setattr(service,'enqueue',fail)
    response=client.post('/api/kr/decision/005930/technical-profile',json={})
    assert response.status_code==503 and 'private' not in response.get_data(as_text=True)


@pytest.mark.parametrize('symbol,expected_status', [('AAPL',400), ('0162D0',202)])
def test_profile_uses_canonical_code_without_fuzzy_name_resolution(runtime, monkeypatch, symbol, expected_status):
    client, _, technical, service = runtime
    monkeypatch.setattr(brief, 'resolve_symbol', lambda raw: ('005930', 'wrong fuzzy match'))
    reads, queued = [], []
    monkeypatch.setattr(technical, 'read_analysis', lambda code: reads.append(code) or envelope(code))
    monkeypatch.setattr(service, 'enqueue', lambda code: queued.append(code) or {'status':'queued'})
    result = client.get(f'/api/kr/decision/{symbol}/technical-profile')
    assert result.status_code == 200 and result.json['symbol'] == symbol
    result = client.post(f'/api/kr/decision/{symbol}/technical-profile', json={})
    assert result.status_code == expected_status
    assert all(code == symbol for code in reads)
    assert queued == ([symbol] if expected_status == 202 else [])


def test_brief_profile_never_changes_votes_or_confidence(monkeypatch):
    from app.services.mirofish import decision_technical as technical
    monkeypatch.setattr(brief,'resolve_symbol',lambda raw:('005930','삼성전자'))
    monkeypatch.setattr(brief,'SOURCE_READERS',{'price':lambda code:{'stance':'positive','grade':'A'}})
    monkeypatch.setattr(brief,'_read_news',lambda code:{'count':0,'items':[]})
    monkeypatch.setattr(brief,'_read_regime',lambda:{'phase':None,'conflict':False})
    monkeypatch.setattr(technical,'read_analysis',lambda *a,**kw:envelope(status='not_requested'))
    missing=brief.build_decision_brief('005930')
    monkeypatch.setattr(technical,'read_analysis',lambda *a,**kw:envelope(status='ready'))
    ready=brief.build_decision_brief('005930')
    assert ready['technical_analysis']['status']=='ready'
    for key in ('signals','agreement','status','strong_evidence','confidence_cap','data_gaps'):
        assert ready[key]==missing[key]


def test_new_deep_analysis_uses_one_bounded_profile_context(monkeypatch):
    from app.services.mirofish import decision_technical as technical, retrieval
    from app.services.mirofish.tradingagents import engine
    monkeypatch.setattr(brief,'resolve_symbol',lambda raw:('005930','삼성전자'))
    data=dict(envelope(status='ready'),profile={'fingerprint':'f'*64,'as_of':'2026-11-12','fetched_at':'2026-11-13T06:00:00Z'})
    monkeypatch.setattr(technical,'read_analysis',lambda *a,**kw:data)
    monkeypatch.setattr(technical,'format_context',lambda a:'PROFILE_CONTEXT')
    monkeypatch.setattr(retrieval,'retrieve_for_symbol',lambda *a,**kw:{})
    monkeypatch.setattr(retrieval,'format_context_line',lambda a:'EXISTING_NEWS')
    calls=[]
    monkeypatch.setattr(engine,'run_deep_analysis',lambda *a,**kw:calls.append(kw) or {})
    result=brief.run_deep_analysis_for('005930')
    assert len(calls)==1 and calls[0]['context_line']=='EXISTING_NEWS\nPROFILE_CONTEXT'
    assert result['technical_profile_used']==dict(fingerprint='f'*64,as_of='2026-11-12',fetched_at='2026-11-13T06:00:00Z',context_text='PROFILE_CONTEXT')


@pytest.mark.parametrize('failure_name', ['SnapshotPending','SnapshotUnavailable'])
def test_scanner_background_gap_keeps_technical_result_and_marks_transient(monkeypatch, failure_name):
    from app.services.mirofish import decision_scanner, decision_technical
    def unavailable():
        raise getattr(decision_scanner, failure_name)()
    monkeypatch.setattr(decision_scanner, 'read_snapshot', unavailable)
    monkeypatch.setattr(brief, 'resolve_symbol', lambda raw: ('005930','삼성전자'))
    monkeypatch.setattr(brief, 'SOURCE_READERS', {'scanner':brief._src_scanner,
        'price':lambda code:{'stance':'positive','grade':'A'}})
    monkeypatch.setattr(brief, '_read_news', lambda code:{'count':0,'items':[]})
    monkeypatch.setattr(brief, '_read_regime', lambda:{'phase':None,'conflict':False})
    monkeypatch.setattr(decision_technical, 'read_analysis', lambda *a,**kw:envelope(status='ready'))
    result=brief.build_decision_brief('005930')
    assert result['pending_sources']==['scanner']
    assert result['data_gaps']==['scanner']
    assert result['technical_analysis']['status']=='ready'
    assert [row['source'] for row in result['signals']]==['price']
