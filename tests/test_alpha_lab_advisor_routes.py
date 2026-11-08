from types import SimpleNamespace

import pytest
from flask import Flask

from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp

PATH = '/api/admin/mirofish/alpha-lab/top3-advisor'


@pytest.fixture
def gateway(monkeypatch):
    from app.services.mirofish.alpha_lab import advisor
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(id=42, email='fixture@example.test', status='approved',
        is_admin=True, is_aibain_active=False, is_kongming_active=False))
    calls = []
    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)
    def read():
        calls.append('read')
        return dict(schema_version=1, status='waiting', top3=[], live_orders=False)
    def queue():
        calls.append('queue')
        return dict(status='queued')
    def paid(**_kwargs):
        pytest.fail('HTTP must not run inference')
    monkeypatch.setattr(advisor, 'read_view', read)
    monkeypatch.setattr(advisor, 'request_refresh', queue)
    monkeypatch.setattr(advisor, 'run_once', paid)
    return app.test_client(), caller, calls


@pytest.mark.parametrize('method', ['get', 'post'])
@pytest.mark.parametrize('case,code', [('anonymous',401),('free',403),('blocked',403)])
def test_unauthorized_before_any_store_access(gateway, method, case, code):
    client, caller, calls = gateway
    if case == 'anonymous':
        caller.user = None
    elif case == 'free':
        caller.user.is_admin = False
    else:
        caller.user.status = 'suspended'
    response = getattr(client, method)(PATH)
    assert response.status_code == code
    assert 'no-store' in response.headers['Cache-Control']
    assert not calls


@pytest.mark.parametrize('entitlement', ['is_aibain_active','is_kongming_active'])
def test_members_read_but_only_admin_can_queue(gateway, entitlement):
    client, caller, calls = gateway
    caller.user.is_admin = False
    setattr(caller.user, entitlement, True)
    response = client.get(PATH)
    assert response.status_code == 200
    assert response.json['live_orders'] is False
    assert client.post(PATH, json={}).status_code == 403
    assert calls == ['read']


def test_admin_get_is_saved_and_post_only_queues(gateway):
    client, _, calls = gateway
    assert client.get(PATH).status_code == 200
    response = client.post(PATH, json={})
    assert response.status_code == 202 and response.json['status'] == 'queued'
    assert 'no-store' in response.headers['Cache-Control']
    assert calls == ['read','queue']


@pytest.mark.parametrize('method,kwargs', [
    ('get',dict(query_string='refresh=true')),('get',dict(data='{}')),
    ('post',dict(json={'force':True})),('post',dict(json=[])),
    ('post',dict(data='null',content_type='application/json')),
    ('post',dict(data='{}',content_type='text/plain')),
    ('post',dict(query_string='symbol=005930')),
])
def test_endpoint_rejects_noncontract_inputs(gateway,method,kwargs):
    client, _, calls = gateway
    assert getattr(client,method)(PATH,**kwargs).status_code == 400
    assert not calls


def test_store_failure_redacts_details(gateway,monkeypatch):
    from app.services.mirofish.alpha_lab import advisor
    def fail():
        raise ValueError('sk-private-secret')
    monkeypatch.setattr(advisor,'read_view',fail)
    response=gateway[0].get(PATH)
    assert response.status_code == 503
    assert 'sk-private-secret' not in response.get_data(as_text=True)


def test_http_boundary_strips_nested_private_receipt_fields(gateway,monkeypatch):
    from app.services.mirofish.alpha_lab import advisor
    monkeypatch.setattr(advisor,'read_view',lambda:dict(schema_version=1,status='degraded',raw='private-secret',
        top3=[dict(symbol='005930',name='삼성전자',market='KR',raw='private-secret',
            plan=dict(entry_price=100,private_error='private-secret'))],
        sources=[dict(evidence_id='candidate:005930',text='private-secret')],
        debate=dict(debate_complete=False,stages=[dict(role='analyst',raw_receipts=['private-secret'])])))
    response=gateway[0].get(PATH)
    assert response.status_code==200
    assert 'private-secret' not in response.get_data(as_text=True)
    assert response.json['top3'][0]['plan']==dict(entry_price=100)
