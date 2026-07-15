from datetime import datetime, timedelta, timezone
import sqlite3

from app import create_app, _apply_aibain_expiry_state
import app as app_package
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import SubscriptionRequest, User
import app.routes.admin as admin_routes
import app.routes.auth as auth_routes


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


def test_expiry_workers_can_run_when_general_background_workers_are_disabled(monkeypatch):
    started = []
    monkeypatch.setenv('MARKETFLOW_BACKGROUND_WORKERS', 'false')
    monkeypatch.setenv('MARKETFLOW_EXPIRY_WORKERS_ENABLED', 'true')
    monkeypatch.setattr(app_package, '_start_expiry_checker', lambda app: started.append('pro'))
    monkeypatch.setattr(app_package, '_start_aibain_expiry_checker', lambda app: started.append('aibain'))

    app_package.create_app({
        'TESTING': False,
        'SECRET_KEY': 'expiry-worker-gate-test',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    assert started == ['pro', 'aibain']


def test_startup_migration_adds_aibain_columns_to_legacy_db(tmp_path):
    db_path = tmp_path / 'legacy-users.db'
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'user',
            tier VARCHAR(20),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            pro_expires_at DATETIME,
            stripe_customer_id VARCHAR(255),
            created_at DATETIME,
            approved_at DATETIME,
            approved_by INTEGER,
            last_login_at DATETIME,
            pro_expiry_alert_stage VARCHAR(10),
            requested_tier VARCHAR(20)
        )
    """)
    conn.execute("""
        CREATE TABLE subscription_requests (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            request_type VARCHAR(50) NOT NULL,
            from_tier VARCHAR(20) NOT NULL,
            to_tier VARCHAR(20) NOT NULL,
            status VARCHAR(20),
            payment_id VARCHAR(255),
            admin_note TEXT,
            created_at DATETIME,
            processed_at DATETIME,
            processed_by INTEGER
        )
    """)
    conn.commit()
    conn.close()

    create_app({
        'TESTING': True,
        'SECRET_KEY': 'migration-test-secret',
        'SQLALCHEMY_DATABASE_URI': f"sqlite:///{db_path.as_posix()}",
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    conn = sqlite3.connect(db_path)
    user_cols = {row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
    request_cols = {row[1] for row in conn.execute('PRAGMA table_info(subscription_requests)').fetchall()}
    conn.close()

    assert {'aibain_enabled', 'aibain_expires_at', 'aibain_alert_stage', 'pro_paused_at'} <= user_cols
    assert {'depositor_name', 'amount'} <= request_cols


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


def test_admin_telegram_suppresses_reserved_example_targets(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'dummy-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')
    monkeypatch.setattr(admin_routes, '_admin_notify_recently_sent', lambda message: (_ for _ in ()).throw(AssertionError('dedupe should not run')))

    target = type('Target', (), {'id': 2, 'email': 'expired@example.com', 'name': '만료회원'})()

    admin_routes._notify_admin('구독 요청 승인', target, 'pro -> pro')


class _TrapThread:
    """텔레그램 전송 스레드가 생성되면 기록 — 억제 검증용."""
    spawned: list

    def __init__(self, *args, **kwargs):
        type(self).spawned.append(kwargs)

    def start(self):
        pass


def test_auth_telegram_suppresses_reserved_example_targets(monkeypatch):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'dummy-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')
    _TrapThread.spawned = []
    monkeypatch.setattr(auth_routes.threading, 'Thread', _TrapThread)

    auth_routes._notify_admin_telegram(
        '💳 구독 요청 (테스트)', target_email='expired@example.com'
    )

    assert _TrapThread.spawned == []


def test_auth_telegram_skipped_in_testing_app(monkeypatch):
    app = _app()
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'dummy-token')
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '123')
    _TrapThread.spawned = []
    monkeypatch.setattr(auth_routes.threading, 'Thread', _TrapThread)

    with app.app_context():
        auth_routes._notify_admin_telegram(
            '💳 구독 요청', target_email='real-member@gmail.com'
        )

    assert _TrapThread.spawned == []


def test_subscription_request_passes_target_email_to_telegram(monkeypatch):
    app = _app()
    expired_at = datetime.now(timezone.utc) - timedelta(days=1)
    captured = []
    monkeypatch.setattr(
        auth_routes, '_notify_admin_telegram',
        lambda message, target_email=None: captured.append(target_email),
    )

    with app.app_context():
        member = _user(
            'expired@example.com',
            '만료회원',
            'Pass1234!',
            status='expired',
            tier='pro',
            pro_expires_at=expired_at,
        )
        db.session.add(member)
        db.session.commit()

    client = app.test_client()
    token = client.post('/api/auth/login', json={
        'email': 'expired@example.com',
        'password': 'Pass1234!',
    }).get_json()['token']

    renewal = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '만료회원'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert renewal.status_code == 201
    assert captured == ['expired@example.com']


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


def test_aibain_addon_approval_extends_existing_future_expiry(monkeypatch):
    app = _app()
    now = datetime.now(timezone.utc)
    current_aibain_expiry = now + timedelta(days=10)
    sent = []
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda action, user, detail='': sent.append((action, user.email, detail)))

    with app.app_context():
        admin = _user('admin@example.com', 'admin', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'aibain@example.com',
            'aibain',
            'Pass1234!',
            status='approved',
            tier='pro',
            pro_expires_at=now + timedelta(days=20),
        )
        member.aibain_enabled = True
        member.aibain_expires_at = current_aibain_expiry
        db.session.add_all([admin, member])
        db.session.flush()
        request = SubscriptionRequest(
            user_id=member.id,
            request_type='aibain_addon',
            from_tier='pro',
            to_tier='pro',
            status='pending',
            amount='40,000원',
            admin_note='AI Brain 알파 스캐너 애드온 신청',
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
    with app.app_context():
        member = User.query.filter_by(email='aibain@example.com').first()
        assert member.aibain_enabled is True
        expires = member.aibain_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires >= current_aibain_expiry + timedelta(days=29, hours=23)


def test_expired_aibain_user_gets_renewal_workflow_without_changing_base_period(monkeypatch):
    app = _app()
    now = datetime.now(timezone.utc)
    base_expiry = now + timedelta(days=17)
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda *args, **kwargs: None)

    with app.app_context():
        admin = _user('renew-admin@example.com', '관리자', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'renew-aibain@example.com',
            '재구독회원',
            'Pass1234!',
            status='approved',
            tier='pro',
            pro_expires_at=base_expiry,
        )
        member.aibain_enabled = False
        member.aibain_expires_at = now - timedelta(days=2)
        member.aibain_alert_stage = 'expired'
        db.session.add_all([admin, member])
        db.session.commit()
        admin_token = generate_token(admin.id)

    client = app.test_client()
    token = client.post('/api/auth/login', json={
        'email': 'renew-aibain@example.com',
        'password': 'Pass1234!',
    }).get_json()['token']

    before_request = client.get(
        '/api/auth/subscription/status',
        headers={'Authorization': f'Bearer {token}'},
    ).get_json()
    assert before_request['user']['tier'] == 'pro'
    assert before_request['user']['status'] == 'approved'
    assert before_request['user']['is_pro_paused'] is False
    assert before_request['aibain_subscription']['state'] == 'expired'
    assert before_request['aibain_subscription']['renewal_eligible'] is True

    renewal = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '재구독회원', 'includes_aibain': True},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert renewal.status_code == 201
    req = renewal.get_json()['request']
    assert req['request_type'] == 'aibain_renewal'
    assert req['amount'] == '40,000원'

    status = client.get(
        '/api/auth/subscription/status',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert status.status_code == 200
    state = status.get_json()['aibain_subscription']
    assert state['state'] == 'renewal_pending'
    assert state['pending_request']['id'] == req['id']
    assert state['renewal_eligible'] is False

    approved = client.put(
        f"/api/admin/subscriptions/{req['id']}/approve",
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert approved.status_code == 200

    with app.app_context():
        member = User.query.filter_by(email='renew-aibain@example.com').first()
        assert member.status == 'approved'
        assert member.tier == 'pro'
        assert member.aibain_enabled is True
        assert member.aibain_alert_stage is None
        assert member.pro_paused_at is not None
        saved_base_expiry = member.pro_expires_at
        if saved_base_expiry.tzinfo is None:
            saved_base_expiry = saved_base_expiry.replace(tzinfo=timezone.utc)
        assert abs((saved_base_expiry - base_expiry).total_seconds()) < 1
        aibain_expiry = member.aibain_expires_at
        if aibain_expiry.tzinfo is None:
            aibain_expiry = aibain_expiry.replace(tzinfo=timezone.utc)
        assert aibain_expiry > now + timedelta(days=29)


def test_pro_aibain_expiry_resumes_preserved_base_period_without_downgrade():
    now = datetime.now(timezone.utc)
    original_pro_expiry = now + timedelta(days=12)
    paused_at = now - timedelta(days=30)
    member = _user(
        'pro-expiry@example.com',
        'Pro만료회원',
        'Pass1234!',
        status='approved',
        tier='pro',
        pro_expires_at=original_pro_expiry,
    )
    member.aibain_enabled = True
    member.aibain_expires_at = now - timedelta(minutes=1)
    member.aibain_alert_stage = 'd1'
    member.pro_paused_at = paused_at
    member.pro_expiry_alert_stage = 'd3'

    elapsed = _apply_aibain_expiry_state(member, now)

    assert elapsed is not None
    assert abs((elapsed - timedelta(days=30)).total_seconds()) < 1
    assert member.aibain_enabled is False
    assert member.aibain_alert_stage == 'expired'
    assert member.aibain_expires_at == now - timedelta(minutes=1)
    assert member.tier == 'pro'
    assert member.status == 'approved'
    assert member.pro_paused_at is None
    assert member.pro_expiry_alert_stage is None
    assert abs((member.pro_expires_at - (original_pro_expiry + timedelta(days=30))).total_seconds()) < 1


def test_ultra_pro_returns_to_ultra_after_aibain_expiry_and_can_renew(monkeypatch):
    app = _app()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda *args, **kwargs: None)

    with app.app_context():
        admin = _user('ultra-admin@example.com', '관리자', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'ultra-renew@example.com',
            '울트라재구독',
            'Pass1234!',
            status='approved',
            tier='premium',
            pro_expires_at=None,
        )
        member.aibain_enabled = False
        member.aibain_expires_at = now - timedelta(days=1)
        member.aibain_alert_stage = 'expired'
        # 과거 Pro → Ultra Pro 변경에서 남을 수 있는 marker도 응답상 pause로 취급하면 안 된다.
        member.pro_paused_at = now - timedelta(days=31)
        db.session.add_all([admin, member])
        db.session.commit()
        admin_token = generate_token(admin.id)

    client = app.test_client()
    token = client.post('/api/auth/login', json={
        'email': 'ultra-renew@example.com',
        'password': 'Pass1234!',
    }).get_json()['token']

    status = client.get(
        '/api/auth/subscription/status',
        headers={'Authorization': f'Bearer {token}'},
    )
    assert status.status_code == 200
    status_body = status.get_json()
    assert status_body['user']['tier'] == 'premium'
    assert status_body['user']['status'] == 'approved'
    assert status_body['user']['pro_expires_at'] is None
    assert status_body['user']['is_pro_paused'] is False
    assert status_body['aibain_subscription']['state'] == 'expired'
    assert status_body['aibain_subscription']['renewal_eligible'] is True

    renewal = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'premium', 'depositor_name': '울트라재구독', 'includes_aibain': True},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert renewal.status_code == 201
    req = renewal.get_json()['request']
    assert req['request_type'] == 'aibain_renewal'
    assert req['from_tier'] == 'premium'
    assert req['to_tier'] == 'premium'
    assert req['amount'] == '40,000원'

    approved = client.put(
        f"/api/admin/subscriptions/{req['id']}/approve",
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert approved.status_code == 200

    with app.app_context():
        member = User.query.filter_by(email='ultra-renew@example.com').first()
        assert member.tier == 'premium'
        assert member.status == 'approved'
        assert member.pro_expires_at is None
        assert member.aibain_enabled is True
        assert member.is_aibain_active is True
        # Ultra Pro에서는 Pro 기간 pause가 새로 생성되지 않는다.
        assert member.pro_paused_at is None
        assert member.is_pro_paused is False


def test_expired_pro_with_aibain_is_full_base_renewal_not_addon(monkeypatch):
    app = _app()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(admin_routes, '_notify_admin', lambda *args, **kwargs: None)

    with app.app_context():
        admin = _user('full-admin@example.com', '관리자', 'Admin1234!', status='approved', tier='premium', role='admin')
        member = _user(
            'expired-full@example.com',
            '전체재구독',
            'Pass1234!',
            status='expired',
            tier='pro',
            pro_expires_at=now - timedelta(days=3),
        )
        member.aibain_enabled = False
        member.aibain_expires_at = now - timedelta(days=3)
        db.session.add_all([admin, member])
        db.session.commit()
        admin_token = generate_token(admin.id)

    client = app.test_client()
    token = client.post('/api/auth/login', json={
        'email': 'expired-full@example.com',
        'password': 'Pass1234!',
    }).get_json()['token']
    renewal = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '전체재구독', 'includes_aibain': True},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert renewal.status_code == 201
    req = renewal.get_json()['request']
    assert req['request_type'] == 'renewal'
    assert req['amount'] == '90,000원'

    approved = client.put(
        f"/api/admin/subscriptions/{req['id']}/approve",
        headers={'Authorization': f'Bearer {admin_token}'},
    )
    assert approved.status_code == 200
    body = approved.get_json()['user']
    assert body['status'] == 'approved'
    assert body['is_pro_expired'] is False
    assert body['is_aibain_active'] is True


def test_admin_user_search_is_server_side_paginated_and_supports_expired_aibain_filter():
    app = _app()
    now = datetime.now(timezone.utc)

    with app.app_context():
        admin = _user('search-admin@example.com', '검색관리자', 'Admin1234!', status='approved', tier='premium', role='admin')
        alpha = _user('alpha.member@example.com', '김알파', 'Pass1234!', status='approved', tier='pro', pro_expires_at=now + timedelta(days=10))
        beta = _user('beta.member@example.com', '박베타', 'Pass1234!', status='approved', tier='premium')
        percent = _user('literal@example.com', '수익률 100%', 'Pass1234!', status='approved', tier='pro', pro_expires_at=now + timedelta(days=10))
        expired_ai = _user('expired.ai@example.com', '만료브레인', 'Pass1234!', status='approved', tier='premium')
        expired_ai.aibain_enabled = False
        expired_ai.aibain_expires_at = now - timedelta(days=1)
        db.session.add_all([admin, alpha, beta, percent, expired_ai])
        db.session.commit()
        admin_token = generate_token(admin.id)
        alpha_id = alpha.id

    client = app.test_client()
    headers = {'Authorization': f'Bearer {admin_token}'}

    by_name = client.get('/api/admin/users?q=김알파&page=1&per_page=50', headers=headers)
    assert by_name.status_code == 200
    assert [u['email'] for u in by_name.get_json()['users']] == ['alpha.member@example.com']

    by_id = client.get(f'/api/admin/users?q={alpha_id}&page=1&per_page=50', headers=headers)
    assert by_id.status_code == 200
    assert any(u['id'] == alpha_id for u in by_id.get_json()['users'])

    literal_wildcard = client.get('/api/admin/users?q=%25&page=1&per_page=50', headers=headers)
    assert literal_wildcard.status_code == 200
    assert [u['email'] for u in literal_wildcard.get_json()['users']] == ['literal@example.com']

    expired = client.get('/api/admin/users?tier=aibain_expired&page=1&per_page=50', headers=headers)
    assert expired.status_code == 200
    assert [u['email'] for u in expired.get_json()['users']] == ['expired.ai@example.com']

    page = client.get('/api/admin/users?page=1&per_page=2', headers=headers).get_json()
    assert page['total'] == 5
    assert len(page['users']) == 2
    assert page['total_pages'] == 3
