from types import SimpleNamespace
import pytest
from flask import Flask
from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish.kongming_technical import service

URL = '/api/admin/mirofish/kongming/technical-profiles'


@pytest.fixture
def gateway(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(id=42, email='fixture@example.test', status='approved',
        is_admin=True, is_aibain_active=False, is_kongming_active=False))
    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)
    calls = []
    def read(**kw):
        calls.append(('read', kw))
        return dict(schema_version=1, agent='volume_profile_20d_v1', status='waiting', last_run_at=None,
            items=[dict(symbol='0162D0', name='동원파츠', status='pending', poc=None, bins=[], raw='private')], secret='private')
    def enqueue(symbol):
        calls.append(('enqueue', symbol))
        return dict(schema_version=1, status='queued', symbol=symbol)
    monkeypatch.setattr(service, 'read_view', read)
    monkeypatch.setattr(service, 'enqueue', enqueue)
    monkeypatch.setattr(service, 'run_once', lambda *a, **kw: pytest.fail('HTTP must not run providers'))
    return app.test_client(), caller, calls


@pytest.mark.parametrize('method', ['get', 'post'])
@pytest.mark.parametrize('role,status', [('anonymous',401),('basic',403),('legacy_ai',403),('suspended',403),('admin',200),('bundle',200)])
def test_entitlement_contract(gateway, method, role, status):
    client, caller, calls = gateway
    if role == 'anonymous': caller.user = None
    elif role == 'suspended': caller.user.status = 'suspended'
    elif role != 'admin':
        caller.user.is_admin = False
        caller.user.is_aibain_active = role == 'legacy_ai'
        caller.user.is_kongming_active = role == 'bundle'
    response = getattr(client, method)(URL, **({'json':dict(symbol='0162D0')} if method=='post' else {}))
    assert response.status_code == (202 if method=='post' and status==200 else status)
    if status != 200: assert not calls


def test_saved_projection_and_symbol_read_are_private_no_store(gateway):
    client, _, calls = gateway
    response = client.get(URL+'?symbol=0162D0')
    assert response.status_code == 200
    assert calls == [('read', dict(symbol='0162D0'))]
    assert response.json['items'][0]['poc'] is None
    assert 'private' not in response.get_data(as_text=True)
    assert 'no-store' in response.headers['Cache-Control']


@pytest.mark.parametrize('suffix', ['?refresh=1','?symbol=../x','?symbol=005930&symbol=000660'])
def test_invalid_query_never_reaches_store(gateway, suffix):
    client, _, calls = gateway
    assert client.get(URL+suffix).status_code == 400
    assert not calls


@pytest.mark.parametrize('body', [None,[],{'symbol':'005930','refresh':True},{'symbol':'000000'}, {'symbol':'abc123'}])
def test_invalid_queue_body_never_reaches_store(gateway, body):
    client, _, calls = gateway
    assert client.post(URL,json=body).status_code == 400
    assert not calls


def test_store_failures_and_queue_capacity_are_safe(gateway, monkeypatch):
    client, _, _ = gateway
    def fail(**kw): raise ValueError('private store')
    monkeypatch.setattr(service,'read_view',fail)
    response=client.get(URL)
    assert response.status_code==503 and 'private store' not in response.get_data(as_text=True)
    def full(symbol): raise ValueError('technical_queue_full')
    monkeypatch.setattr(service,'enqueue',full)
    assert client.post(URL,json=dict(symbol='005930')).status_code==429


def test_new_numeric_and_zone_fields_survive_projection(gateway,monkeypatch):
    client,_,_=gateway
    row=dict(symbol='005930',name='삼성전자',status='ready',reason=None,as_of='2026-11-12',
        fetched_at='2026-11-13T03:00:00Z',window_start='2026-10-16',window_end='2026-11-12',
        sessions_required=20,sessions_used=20,reference_price=100.,total_volume=1000.,total_traded_value=100000.,
        poc=dict(index=0,low=90.,high=100.,volume=600.,volume_pct=60.,traded_value=60000.),
        support=None,resistance=None,current_zone=None,bins=[],method='daily_uniform_range_overlap_v1',
        source='KIS:FHKST03010100:J:D:1',calendar_source='KIS:KOSPI:FHKUP03500100',
        price_basis='KIS_KRX_raw_J_D_1',limitations=['일봉 추정'],fingerprint='a'*64,retry_at=None)
    monkeypatch.setattr(service,'read_view',lambda **kw:dict(schema_version=1,items=[row]))
    assert client.get(URL).json['items']==[row]
