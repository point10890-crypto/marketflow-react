"""Claw polling releases auth connections before its independent file/ledger work."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from flask import has_request_context, request
from sqlalchemy import inspect

from app import create_app
import app.auth.decorators as auth
from app.models import db
from app.models.user import User
from marketflow_claw import observation, overview
import app.routes.kr_claw as claw_routes


@pytest.fixture
def claw_app(tmp_path, monkeypatch):
    # The production factory supplies the real global gate, but this fixture
    # must never load local credentials or import unrelated operational routes.
    monkeypatch.setattr('dotenv.load_dotenv', lambda *args, **kwargs: False)

    def register_test_blueprints(application):
        from app.routes.auth import auth_bp

        application.register_blueprint(auth_bp, url_prefix='/api/auth')
        application.register_blueprint(claw_routes.kr_claw_bp, url_prefix='/api/kr/claw')
        application.add_url_rule('/api/data-version', view_func=lambda: {})

    monkeypatch.setattr('app.routes.register_blueprints', register_test_blueprints)
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

    def auth_state():
        user = request.current_user
        assert auth._get_current_user() is user
        assert auth._get_current_user() is user
        return {'checked_out': engine.pool.checkedout(), 'detached': inspect(user).detached}

    checked = []
    dispatch = claw_routes._project

    def check_before_dispatch(*args, **kwargs):
        checked.append(auth_state())
        return dispatch(*args, **kwargs)

    monkeypatch.setattr(claw_routes, '_project', check_before_dispatch)

    def project(*args, **kwargs):
        if endpoint == 'close-leaders':
            return auth_state()
        assert not has_request_context()
        return {'checked_out': engine.pool.checkedout(), 'detached': checked[0]['detached']}

    target = overview if endpoint in {'overview', 'close-leaders'} else observation
    monkeypatch.setattr(target, service, project)
    response = application.test_client().get('/api/kr/claw/' + endpoint, headers=headers(identities, name))
    assert response.status_code == 200
    payload = response.get_json()
    payload.pop('projection', None)
    assert payload == {'checked_out': 0, 'detached': True}
    assert len(lookups) == 1
    assert engine.pool.checkedout() == 0


def test_slow_claw_requests_cannot_starve_unrelated_authentication(claw_app, monkeypatch):
    application, identities, engine = claw_app
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    results = []

    def slow_projection():
        entered.set()
        assert release.wait(timeout=3)
        finished.set()
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
        assert entered.wait(timeout=3)
        for worker in workers:
            worker.join(timeout=1)
        assert results == [503, 503]
        # The second request may still authenticate when the first builder
        # enters. Measure released checkouts after both HTTP requests finish,
        # while their shared source I/O is demonstrably still blocked.
        assert not finished.is_set()
        assert not release.is_set()
        assert engine.pool.checkedout() == 0
        response = application.test_client().get('/api/auth/me', headers=headers(identities, 'pro'))
        assert response.status_code == 200
        assert engine.pool.checkedout() == 0
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=3)
        assert finished.wait(timeout=1)
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
