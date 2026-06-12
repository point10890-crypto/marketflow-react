from datetime import datetime, timedelta, timezone

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import SubscriptionRequest, User
import app.routes.admin as admin_routes


def _app():
    return create_app({
        'TESTING': True,
        'SECRET_KEY': 'workflow-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })


def _user(email: str, name: str, password: str, *, status='pending', tier=None, role='user', pro_expires_at=None):
    user = User(email=email, name=name, status=status, tier=tier, role=role, pro_expires_at=pro_expires_at)
    user.set_password(password)
    return user


def test_pending_user_can_login_and_submit_subscription_request():
    app = _app()

    with app.app_context():
        member = _user('pending@example.com', '승인대기', 'Pass1234!', status='pending', tier=None)
        db.session.add(member)
        db.session.commit()

    client = app.test_client()
    login = client.post('/api/auth/login', json={
        'email': 'pending@example.com',
        'password': 'Pass1234!',
    })
    assert login.status_code == 200
    body = login.get_json()
    assert body['user']['status'] == 'pending'
    assert body['user']['tier'] is None
    token = body['token']

    request = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '승인대기'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert request.status_code == 201
    req_body = request.get_json()['request']
    assert req_body['status'] == 'pending'
    assert req_body['request_type'] == 'upgrade'
    assert req_body['amount'] == '50,000원'

    with app.app_context():
        member = User.query.filter_by(email='pending@example.com').first()
        assert member.requested_tier == 'pro'


def test_expired_pro_user_can_request_same_tier_renewal_and_approval_reactivates():
    app = _app()
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)

    with app.app_context():
        admin = _user('admin@example.com', '관리자', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'expired@example.com',
            '만료회원',
            'Pass1234!',
            status='expired',
            tier='pro',
            pro_expires_at=expired_at,
        )
        db.session.add_all([admin, member])
        db.session.commit()
        admin_token = generate_token(admin.id)

    client = app.test_client()
    login = client.post('/api/auth/login', json={
        'email': 'expired@example.com',
        'password': 'Pass1234!',
    })
    assert login.status_code == 200
    token = login.get_json()['token']

    renewal = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '만료회원'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert renewal.status_code == 201
    req = renewal.get_json()['request']
    assert req['request_type'] == 'renewal'
    assert req['from_tier'] == 'pro'
    assert req['to_tier'] == 'pro'
    assert req['amount'] == '50,000원'

    approved = client.put(
        f"/api/admin/subscriptions/{req['id']}/approve",
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert approved.status_code == 200

    with app.app_context():
        member = User.query.filter_by(email='expired@example.com').first()
        assert member.status == 'approved'
        assert member.tier == 'pro'
        assert member.pro_expires_at is not None
        expires = member.pro_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires > datetime.now(timezone.utc)


def test_subscription_approval_is_idempotent_and_sends_admin_notice_once(monkeypatch):
    app = _app()
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    sent = []
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda action, user, detail='': sent.append((action, user.email, detail)))

    with app.app_context():
        admin = _user('admin@example.com', 'admin', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'expired@example.com',
            'expired',
            'Pass1234!',
            status='expired',
            tier='pro',
            pro_expires_at=expired_at,
        )
        db.session.add_all([admin, member])
        db.session.flush()
        request = SubscriptionRequest(
            user_id=member.id,
            request_type='renewal',
            from_tier='pro',
            to_tier='pro',
            status='pending',
            amount='50,000원',
        )
        db.session.add(request)
        db.session.commit()
        admin_token = generate_token(admin.id)
        request_id = request.id

    client = app.test_client()
    first = client.put(
        f'/api/admin/subscriptions/{request_id}/approve',
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    second = client.put(
        f'/api/admin/subscriptions/{request_id}/approve',
        headers={'Authorization': f'Bearer {admin_token}'},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()['already_processed'] is True
    assert len(sent) == 1


def test_admin_telegram_dedupe_suppresses_identical_message(tmp_path, monkeypatch):
    dedupe_file = tmp_path / 'admin_notify_dedupe.json'
    monkeypatch.setattr(admin_routes, '_admin_notify_dedupe_path', lambda: dedupe_file)
    monkeypatch.setattr(admin_routes, '_ADMIN_NOTIFY_DEDUPE_TTL_SECONDS', 3600)

    message = 'admin approval: expired@example.com pro -> pro'

    assert admin_routes._admin_notify_recently_sent(message, now=1000.0) is False
    assert admin_routes._admin_notify_recently_sent(message, now=1001.0) is True
    assert admin_routes._admin_notify_recently_sent(message, now=4601.1) is False


def test_duplicate_active_renewal_approval_does_not_send_admin_notice(monkeypatch):
    app = _app()
    future_at = datetime.now(timezone.utc) + timedelta(days=20)
    sent = []
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda action, user, detail='': sent.append((action, user.email, detail)))

    with app.app_context():
        admin = _user('admin@example.com', 'admin', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'active@example.com',
            'active',
            'Pass1234!',
            status='approved',
            tier='pro',
            pro_expires_at=future_at,
        )
        db.session.add_all([admin, member])
        db.session.flush()
        request = SubscriptionRequest(
            user_id=member.id,
            request_type='renewal',
            from_tier='pro',
            to_tier='pro',
            status='pending',
            amount='50,000원',
        )
        db.session.add(request)
        db.session.commit()
        admin_token = generate_token(admin.id)
        request_id = request.id

    client = app.test_client()
    approved = client.put(
        f'/api/admin/subscriptions/{request_id}/approve',
        headers={'Authorization': f'Bearer {admin_token}'},
    )

    assert approved.status_code == 200
    body = approved.get_json()
    assert body['already_processed'] is True
    assert body['duplicate_ignored'] is True
    assert sent == []
