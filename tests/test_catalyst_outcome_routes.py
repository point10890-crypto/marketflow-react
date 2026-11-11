from types import SimpleNamespace
import pytest
from flask import Flask
from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.catalyst_outcomes import service

URL='/api/admin/mirofish/kongming/catalyst-outcomes'


@pytest.fixture
def gateway(monkeypatch):
    app=Flask(__name__);app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app);app.register_blueprint(admin_mirofish_bp,url_prefix='/api/admin/mirofish')
    caller=SimpleNamespace(user=SimpleNamespace(id=42,email='test@example.com',status='approved',is_admin=True,is_aibain_active=False,is_kongming_active=False))
    monkeypatch.setattr(auth,'_get_current_user',lambda:caller.user)
    monkeypatch.setattr(service,'run_once',lambda **kwargs:pytest.fail('GET triggered work'))
    monkeypatch.setattr(service,'read_view',lambda **kwargs:{**service._empty(None),'private_secret':'not-public'})
    return app.test_client(),caller


def test_auth_and_private_saved_only(gateway):
    client,caller=gateway
    r=client.get(URL);assert r.status_code==200
    assert 'private_secret' not in r.json and 'no-store' in r.headers['Cache-Control']
    caller.user.is_admin=False;assert client.get(URL).status_code==403
    caller.user.is_kongming_active=True;assert client.get(URL).status_code==200
    caller.user=None;assert client.get(URL).status_code==401


@pytest.mark.parametrize('query',['?refresh=1','?page=0','?page_size=100','?symbol=../env','?filter=winner','?page=1&page=2'])
def test_invalid_query(gateway,query):
    assert gateway[0].get(URL+query).status_code==400


def test_queries_and_no_post(gateway,monkeypatch):
    client,_=gateway;seen={}
    def read(**kwargs): seen.update(kwargs);return service._empty(None)
    monkeypatch.setattr(service,'read_view',read)
    assert client.get(URL+'?page=2&page_size=20&symbol=005930&filter=all').status_code==200
    assert seen==dict(page=2,page_size=20,symbol='005930',filter='all')
    assert client.post(URL).status_code==405
