import http.client
import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask

from app.auth import decorators as auth
from app.routes.admin_mirofish import admin_mirofish_bp
from app.services import kongming_article_candidates, kongming_verification


PREFIX = '/api/admin/mirofish/kongming'
STATUS = PREFIX + '/catalyst-validation'
HISTORY = PREFIX + '/catalyst-validation-history'
ARTICLES = PREFIX + '/article-candidates'
AT = '2026-11-07T09:00:00+09:00'


@pytest.fixture
def gateway(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    auth.db.init_app(app)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    caller = SimpleNamespace(user=SimpleNamespace(
        id=42, email='fixture@example.test', status='approved', is_admin=True,
        is_aibain_active=False, is_kongming_active=False,
    ))
    calls = []

    def forbid_network(*args, **kwargs):
        pytest.fail('A verification GET must not reach the original server')

    def saved_view(*, article_id):
        calls.append(('dashboard', article_id))
        return {'source': 'marketflow', 'items': []}

    def saved_history(*, article_id):
        calls.append(('history', article_id))
        return {'source': 'marketflow', 'items': []}

    def saved_articles():
        calls.append(('articles', None))
        return {'items': [], 'operation': {'state': 'ready'}}

    monkeypatch.setattr(auth, '_get_current_user', lambda: caller.user)
    monkeypatch.setattr(http.client, 'HTTPConnection', forbid_network)
    monkeypatch.setattr(kongming_verification, 'read_dashboard', saved_view)
    monkeypatch.setattr(kongming_verification, 'read_history', saved_history)
    monkeypatch.setattr(kongming_article_candidates, 'read_view', saved_articles)
    return app.test_client(use_cookies=False), caller, calls


@pytest.mark.parametrize(('case', 'status'), [
    ('anonymous', 401), ('member', 403), ('suspended', 403),
    ('legacy_aibain', 403), ('expired_bundle', 403), ('pending_bundle', 403),
    ('rejected_admin', 403),
])
@pytest.mark.parametrize('path', [STATUS, HISTORY, ARTICLES])
def test_denies_anonymous_blocked_or_unentitled_users(gateway, case, status, path):
    client, caller, calls = gateway
    if case == 'anonymous':
        caller.user = None
    elif case == 'member':
        caller.user.is_admin = False
    elif case == 'suspended':
        caller.user.status = 'suspended'
        caller.user.is_kongming_active = True
    elif case in ('legacy_aibain', 'expired_bundle', 'pending_bundle'):
        caller.user.is_admin = False
        caller.user.is_aibain_active = case != 'pending_bundle'
    elif case == 'rejected_admin':
        caller.user.status = 'rejected'

    assert client.get(path).status_code == status
    assert not calls


@pytest.mark.parametrize('path', [STATUS, HISTORY, ARTICLES])
@pytest.mark.parametrize('is_admin', [True, False])
def test_admin_and_bundle_read_the_local_store(gateway, monkeypatch, path, is_admin):
    client, caller, calls = gateway
    caller.user.is_admin = is_admin
    caller.user.is_kongming_active = not is_admin
    monkeypatch.setenv('KONGMING_CATALYST_ALLOWED_USER_IDS', '7,73')

    response = client.get(path)

    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    assert len(calls) == 1


def test_bundle_does_not_grant_general_mirofish_run_creation(gateway):
    client, caller, _ = gateway
    caller.user.is_admin = False
    caller.user.is_kongming_active = True
    assert client.post('/api/admin/mirofish/runs', json={}).status_code == 403


def test_dashboard_projects_safe_local_evidence(gateway, monkeypatch):
    client, _, _ = gateway
    raw = {
        'source': 'marketflow', 'computed_at': AT, 'history_count': 2, 'private_path': 'hidden',
        'live': {'last_run_at': AT, 'age_seconds': 0, 'stalled': False, 'worker_interval_seconds': 60,
                 'internal_path': 'hidden'},
        'operation': {'state': 'ready', 'task_count': 1, 'private_error': 'hidden'},
        'items': [{'article_id': '11', 'task_id': 'saved', 'symbol': '005930',
                   'primary': {'status': 'related_filing_found', 'checks': [{
                       'filing': {'report_nm': '영업실적', 'rcept_dt': '20261106', 'private': 'hidden'},
                   }]},
                   'price': {'status': 'verified', 'close': 71000, 'observed_at': AT, 'raw_price': 'hidden'}}],
    }
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda *, article_id: raw)

    response = client.get(STATUS + '?url=https://wrong.example.test/')

    assert response.status_code == 200
    body = response.get_json()
    assert 'hidden' not in str(body)
    assert body['live']['worker_interval_seconds'] == 60
    assert body['items'][0]['price']['close'] == 71000
    assert body['items'][0]['primary']['checks'][0]['filing']['rcept_dt'] == '20261106'


def test_article_filter_reaches_both_readers_and_rejects_non_ids(gateway):
    client, _, calls = gateway
    assert client.get(STATUS + '?article_id=451440').status_code == 200
    assert client.get(HISTORY + '?article_id=451440').status_code == 200
    assert client.get(HISTORY + '?article_id=../other').status_code == 400
    assert calls == [('dashboard', '451440'), ('history', '451440')]


def test_store_failure_is_generic_and_private(gateway, monkeypatch):
    client, _, _ = gateway

    def failed(*, article_id):
        raise sqlite3.OperationalError('private local path')

    monkeypatch.setattr(kongming_verification, 'read_dashboard', failed)
    response = client.get(STATUS)

    assert response.status_code == 503
    assert response.get_json() == {'error': 'kongming_catalyst_unavailable'}
    assert 'no-store' in response.headers['Cache-Control']


def test_routes_are_read_only_and_do_not_proxy_original_app(gateway):
    client, _, calls = gateway
    assert client.get(PREFIX + '/businesspost').status_code == 404
    for path in (STATUS, HISTORY, ARTICLES):
        assert client.post(path).status_code == 405
    assert not calls
