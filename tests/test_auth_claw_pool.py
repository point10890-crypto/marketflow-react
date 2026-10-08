"""Claw polling releases auth connections before its independent file/ledger work."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from flask import request
from sqlalchemy import inspect

from app import create_app
import app.auth.decorators as auth
from app.models import db
from app.models.user import User
from marketflow_claw import observation, overview


@pytest.fixture
def claw_app(tmp_path):
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'claw-pool-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (tmp_path / 'users.db').as_posix(),
        'SQLALCHEMY_ENGINE_OPTIONS': {
            'pool_size': 2, 'max_overflow': 0, 'pool_timeout': 0.1,
            'connect_args': {'check_same_thread': False},
        },
    })
    identities = {}
    with application.app_context():
        for name, values in {
            'admin': {'role': 'admin'},
            'pro': {},
            'aibain': {'aibain_enabled': True},
            'suspended': {'role': 'admin', 'status': 'suspended'},
            'rejected': {'status': 'rejected'},
            'expired': {'tier': 'pro', 'pro_expires_at': datetime.now(timezone.utc) - timedelta(days=1)},
            'pending': {'status': 'pending'},
            'no_tier': {'tier': None},
            'aibain_expired': {'aibain_enabled': True, 'aibain_expires_at': datetime.now(timezone.utc) - timedelta(days=1)},
            'password_revoked': {'password_changed_at': datetime.now(timezone.utc) + timedelta(minutes=1)},
        }.items():
            fields = {'role': 'user', 'tier': 'premium', 'status': 'approved', **values}
            user = User(email=f'{name}@example.com', name=name, password_hash='unused', **fields)
            db.session.add(user)
            db.session.flush()
            identities[name] = {'id': user.id, 'token': auth.generate_token(user.id)}
        db.session.commit()
        engine = db.engine
    yield application, identities, engine
    engine.dispose()


def headers(identities, name):
    return {'Authorization': 'Bearer ' + identities[name]['token']}


@pytest.mark.parametrize('endpoint,service,name', [
    ('overview', 'build_overview', 'admin'),
    ('overview', 'build_overview', 'pro'),
    ('close-leaders', 'build_close_leaders', 'pro'),
    ('quality', 'build_quality', 'admin'),
    ('quality', 'build_quality', 'aibain'),
    ('scorecards', 'build_scorecards', 'aibain'),
])
def test_claw_service_has_no_auth_connection_and_reuses_verified_identity(claw_app, monkeypatch, endpoint, service, name):
    application, identities, engine = claw_app
    lookups = []
    session_get = db.session.get

    def track_get(*args, **kwargs):
        lookups.append(args)
        return session_get(*args, **kwargs)

    monkeypatch.setattr(db.session, 'get', track_get)

    def project(*args, **kwargs):
        user = request.current_user
        assert auth._get_current_user() is user
        assert auth._get_current_user() is user
        return {'checked_out': engine.pool.checkedout(), 'detached': inspect(user).detached}

    target = overview if endpoint in {'overview', 'close-leaders'} else observation
    monkeypatch.setattr(target, service, project)
    response = application.test_client().get('/api/kr/claw/' + endpoint, headers=headers(identities, name))
    assert response.status_code == 200
    assert response.get_json() == {'checked_out': 0, 'detached': True}
    assert len(lookups) == 1
    assert engine.pool.checkedout() == 0


def test_slow_claw_requests_cannot_starve_unrelated_authentication(claw_app, monkeypatch):
    application, identities, engine = claw_app
    entered = threading.Barrier(3)
    release = threading.Event()
    results = []

    def slow_projection():
        entered.wait(timeout=3)
        assert release.wait(timeout=3)
        return {'ok': True}

    monkeypatch.setattr(overview, 'build_overview', slow_projection)

    def poll():
        try:
            results.append(application.test_client().get('/api/kr/claw/overview', headers=headers(identities, 'pro')).status_code)
        except Exception as error:
            results.append(type(error).__name__)

    workers = [threading.Thread(target=poll) for _ in range(2)]
    for worker in workers:
        worker.start()
    try:
        entered.wait(timeout=3)
        assert engine.pool.checkedout() == 0
        response = application.test_client().get('/api/auth/me', headers=headers(identities, 'pro'))
        assert response.status_code == 200
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=3)
    assert results == [200, 200]
    assert engine.pool.checkedout() == 0


@pytest.mark.parametrize('name,endpoint,expected', [
    (None, 'overview', 401),
    ('suspended', 'overview', 403),
    ('rejected', 'overview', 403),
    ('pending', 'overview', 403),
    ('no_tier', 'overview', 403),
    ('expired', 'overview', 403),
    ('password_revoked', 'overview', 401),
    ('pro', 'quality', 403),
    ('aibain_expired', 'quality', 403),
])
def test_claw_auth_release_preserves_denials(claw_app, monkeypatch, name, endpoint, expected):
    application, identities, engine = claw_app
    monkeypatch.setattr(overview, 'build_overview', lambda: pytest.fail('denied request entered service'))
    monkeypatch.setattr(observation, 'build_quality', lambda: pytest.fail('denied request entered service'))
    response = application.test_client().get('/api/kr/claw/' + endpoint, headers=headers(identities, name) if name else {})
    assert response.status_code == expected
    assert engine.pool.checkedout() == 0
    if name == 'expired':
        with application.app_context():
            user = db.session.get(User, identities[name]['id'])
            assert user.status == user.pro_expiry_alert_stage == 'expired'


def test_cached_claw_identity_is_request_scoped_and_does_not_trust_current_user(claw_app, monkeypatch):
    application, identities, engine = claw_app
    monkeypatch.setattr(observation, 'build_quality', lambda: {'ok': True})

    @application.before_request
    def unverified_identity():
        request.current_user = SimpleNamespace(is_admin=True, is_aibain_active=True, status='approved')

    client = application.test_client()
    assert client.get('/api/kr/claw/quality', headers=headers(identities, 'pro')).status_code == 403
    assert client.get('/api/kr/claw/quality', headers=headers(identities, 'aibain')).status_code == 200
    with application.app_context():
        user = db.session.get(User, identities['aibain']['id'])
        user.aibain_enabled = False
        db.session.commit()
    assert client.get('/api/kr/claw/quality', headers=headers(identities, 'aibain')).status_code == 403
    assert engine.pool.checkedout() == 0


def test_non_claw_profile_mutation_keeps_orm_persistence(claw_app):
    application, identities, engine = claw_app
    response = application.test_client().put('/api/auth/profile', json={'name': 'updated'}, headers=headers(identities, 'pro'))
    assert response.status_code == 200
    with application.app_context():
        assert db.session.get(User, identities['pro']['id']).name == 'updated'
    assert engine.pool.checkedout() == 0
