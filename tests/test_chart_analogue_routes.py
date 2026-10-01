from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from app.models import db
import app.auth.decorators as auth
import app.routes.admin_mirofish as routes


@pytest.fixture
def client(monkeypatch):
    app=Flask(__name__)
    app.config.update(TESTING=True,SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',SECRET_KEY='chart-route-test')
    db.init_app(app)
    app.register_blueprint(routes.admin_mirofish_bp,url_prefix='/api/admin/mirofish')
    monkeypatch.setattr(auth,'_get_current_user',lambda:SimpleNamespace(id=1,email='fixture@example.test',status='approved',is_admin=True,is_aibain_active=False))
    return app.test_client()


def service(monkeypatch,predict=None):
    provider=SimpleNamespace(predict=predict or Mock(return_value={'symbol':'003690','status':'ready','mode':'shadow','sample_count':5}),status=Mock(return_value={'status':'ready'}))
    monkeypatch.setattr(routes,'_chart_analogue_service',lambda:provider,raising=False)
    return provider


def test_readonly_prediction_delegates_symbol_and_has_private_cache(client,monkeypatch):
    provider=service(monkeypatch)
    result=client.get('/api/admin/mirofish/chart-analogue/003690')
    assert result.status_code==200
    assert result.json['sample_count']==5
    provider.predict.assert_called_once_with('003690')
    assert 'private' in result.headers['Cache-Control']


def test_status_is_separate_cheap_operation(client,monkeypatch):
    provider=service(monkeypatch)
    assert client.get('/api/admin/mirofish/chart-analogue/status').json['status']=='ready'
    provider.predict.assert_not_called()


def test_status_provider_error_is_generic_and_private(client,monkeypatch):
    provider=service(monkeypatch)
    provider.status.side_effect=OSError('private-index-path')
    result=client.get('/api/admin/mirofish/chart-analogue/status')
    assert result.status_code==503
    assert 'private-index-path' not in result.get_data(as_text=True)
    assert 'private' in result.headers['Cache-Control']


@pytest.mark.parametrize('user,expected',[(None,401),(SimpleNamespace(status='approved',is_admin=False,is_aibain_active=False),403),(SimpleNamespace(id=2,email='fixture@example.test',status='approved',is_admin=False,is_aibain_active=True),200)])
def test_prediction_access_uses_existing_aibain_gate(client,monkeypatch,user,expected):
    provider=service(monkeypatch)
    monkeypatch.setattr(auth,'_get_current_user',lambda:user)
    assert client.get('/api/admin/mirofish/chart-analogue/003690').status_code==expected
    if expected!=200:provider.predict.assert_not_called()


@pytest.mark.parametrize('symbol',['ABC','123','003690.KS'])
def test_invalid_symbol_rejected_before_provider(client,monkeypatch,symbol):
    provider=service(monkeypatch)
    assert client.get('/api/admin/mirofish/chart-analogue/'+symbol).status_code==400
    provider.predict.assert_not_called()


def test_missing_index_is_visible_and_not_a_fabricated_forecast(client,monkeypatch):
    service(monkeypatch,Mock(return_value={'symbol':'003690','status':'missing_index','horizons':[],'fan':[]}))
    result=client.get('/api/admin/mirofish/chart-analogue/003690')
    assert result.status_code==200 and result.json['status']=='missing_index'
    assert result.json['fan']==[]


def test_provider_error_does_not_expose_host_paths(client,monkeypatch):
    service(monkeypatch,Mock(side_effect=OSError('private-host-path')))
    result=client.get('/api/admin/mirofish/chart-analogue/003690')
    assert result.status_code==503
    assert 'private-host-path' not in result.get_data(as_text=True)


def test_prediction_has_no_mutating_method(client,monkeypatch):
    provider=service(monkeypatch)
    assert client.post('/api/admin/mirofish/chart-analogue/003690').status_code==405
    provider.predict.assert_not_called()
