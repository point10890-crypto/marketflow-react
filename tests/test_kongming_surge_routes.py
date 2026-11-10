import http.client
from types import SimpleNamespace

import pytest
from flask import Flask

from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp

URL = '/api/admin/mirofish/kongming/surge-traces'


@pytest.fixture
def gateway(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(id=42, email='fixture@example.test',
        status='approved', is_admin=True, is_aibain_active=False, is_kongming_active=False))
    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)
    monkeypatch.setattr(http.client, 'HTTPConnection', lambda *a, **k: pytest.fail('GET cannot acquire'))
    return app.test_client(), caller


@pytest.mark.parametrize('case,expected', [('anonymous',401), ('member',403), ('blocked',403),
                                         ('legacy_ai',403)])
def test_surge_trace_access(gateway, case, expected):
    client, caller = gateway
    if case == 'anonymous': caller.user = None
    elif case == 'blocked': caller.user.status = 'suspended'
    else:
        caller.user.is_admin = False
        caller.user.is_aibain_active = case == 'legacy_ai'
    assert client.get(URL).status_code == expected


@pytest.mark.parametrize('admin', [True, False])
def test_surge_trace_saved_only_private_projection(gateway, monkeypatch, admin):
    from app.services.surge_trace import service
    client, caller = gateway
    caller.user.is_admin = admin
    caller.user.is_kongming_active = not admin
    payload = dict(schema_version=1, status='ready', generated_at=None, source_as_of=None,
        threshold=dict(change_pct=5, trading_value=2000000000), items=[],
        operation=dict(state='ready',last_run_at=None,source_status='fresh',processed=0,pending=0),
        private_response='not-public')
    monkeypatch.setattr(service, 'read_view', lambda: payload)
    monkeypatch.setattr(service, 'run_once', lambda *a, **k: pytest.fail('GET started worker'))
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json['items'] == []
    assert 'private_response' not in response.json
    assert 'no-store' in response.headers['Cache-Control']
    assert client.post(URL, json={}).status_code == 405


def test_surge_trace_rejects_query_and_saved_failure(gateway, monkeypatch):
    from app.services.surge_trace import service
    client, _ = gateway
    monkeypatch.setattr(service, 'read_view', lambda: (_ for _ in ()).throw(ValueError('private transport detail')))
    assert client.get(URL+'?force=true').status_code == 400
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json == {'error':'surge_trace_unavailable'}


def test_surge_trace_invalid_saved_schema_is_not_a_success(gateway, monkeypatch):
    from app.services.surge_trace import service
    client, _ = gateway
    monkeypatch.setattr(service, 'read_view', lambda: {'items': 'not-a-list'})
    assert client.get(URL).status_code == 503
