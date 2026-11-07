import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db, user as user_model
from app.models.user import AdminAuditLog, SubscriptionRequest, User
from app.routes import admin, auth
from app.services import kongming_verification


PLAN = 'aibain_kongming_conversion'
APPLY = '/api/auth/subscription/request'
STATUS = '/api/auth/subscription/status'
CATALYST = '/api/admin/mirofish/kongming/catalyst-validation'


@pytest.fixture
def checkout(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, '_notify_admin_telegram', lambda *a, **kw: None)
    monkeypatch.setattr(admin, '_notify_admin', lambda *a, **kw: None)
    monkeypatch.setattr(admin, '_notify_member', lambda *a, **kw: None)
    db_path = tmp_path / 'checkout.db'
    app = create_app({
        'TESTING': True, 'SECRET_KEY': 'conversion-test-secret',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with app.app_context():
        member = User(email='member@example.com', name='Member', password_hash='unused',
                      status='approved', tier='pro', aibain_enabled=True,
                      aibain_expires_at=now + timedelta(days=12), pro_paused_at=now,
                      pro_expires_at=now + timedelta(days=20))
        operator = User(email='admin@example.com', name='Admin', password_hash='unused',
                        status='approved', role='admin')
        db.session.add_all([member, operator])
        db.session.commit()
        return (
            app.test_client(), app, member.id,
            {'Authorization': f'Bearer {generate_token(member.id)}'},
            {'Authorization': f'Bearer {generate_token(operator.id)}'},
        )


def submit(client, headers, **changes):
    payload = {'plan': PLAN, 'expected_amount': 10000, 'depositor_name': ' Member '}
    return client.post(APPLY, headers=headers, json={**payload, **changes})


def test_conversion_changes_only_kongming_and_uses_captured_expiry(checkout, monkeypatch):
    client, app, member_id, headers, admin_headers = checkout
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda **kw: {'items': []})
    assert client.get(CATALYST, headers=admin_headers).status_code == 200
    before = client.get(STATUS, headers=headers).json['user']
    offer = before['ai_bundle_conversion']
    expected_expiry = datetime.fromisoformat(before['aibain_expires_at']).replace(tzinfo=timezone.utc)
    assert offer == {'eligible': True, 'amount': 10000,
                     'expires_at': expected_expiry.isoformat(), 'reason': 'eligible'}
    assert client.get(CATALYST, headers=headers).status_code == 403

    response = submit(client, headers, amount='1원')
    assert response.status_code == 201
    saved = response.json['request']
    assert saved['request_type'] == PLAN
    assert saved['amount'] == '10,000원'
    assert saved['depositor_name'] == 'Member'
    assert saved['conversion_expires_at'] == expected_expiry.isoformat()
    assert submit(client, headers).status_code == 409
    pending = client.get(STATUS, headers=headers).json
    assert pending['kongming_subscription']['state'] == 'activation_pending'
    assert pending['kongming_subscription']['pending_request']['id'] == saved['id']
    assert pending['user']['ai_bundle_conversion']['eligible'] is False

    path = f"/api/admin/subscriptions/{saved['id']}/approve"
    assert client.put(path, headers=headers).status_code == 403
    approved = client.put(path, headers=admin_headers)
    assert approved.status_code == 200
    after = approved.json['user']
    for field in ('tier', 'status', 'pro_expires_at', 'pro_paused_at', 'aibain_expires_at', 'approved_at'):
        assert after[field] == before[field]
    assert after['is_kongming_active'] is True
    assert datetime.fromisoformat(after['kongming_expires_at']) == expected_expiry.replace(tzinfo=None)
    catalyst = client.get(CATALYST, headers=headers)
    assert catalyst.status_code == 200
    assert catalyst.json == {'items': []}
    repeated = client.put(path, headers=admin_headers)
    assert repeated.json['already_processed'] is True
    assert repeated.json['user']['kongming_expires_at'] == after['kongming_expires_at']
    with app.app_context():
        logs = AdminAuditLog.query.filter_by(
            action='approve_aibain_kongming_conversion', target_user_id=member_id,
        ).all()
        assert len(logs) == 1
        assert logs[0].note == f"request_id={saved['id']}"


@pytest.mark.parametrize('changes, status', [
    ({'expected_amount': None}, 409),
    ({'expected_amount': 1}, 409),
    ({'expected_amount': '10000'}, 409),
    ({'depositor_name': '  '}, 400),
    ({'depositor_name': 1}, 400),
])
def test_conversion_rejects_invalid_payment_details(checkout, changes, status):
    client, app, _, headers, _ = checkout
    assert submit(client, headers, **changes).status_code == status
    with app.app_context():
        assert SubscriptionRequest.query.count() == 0


@pytest.mark.parametrize('changes', [
    {'role': 'admin'}, {'status': 'pending'}, {'status': 'suspended'},
    {'status': 'expired'}, {'aibain_enabled': False}, {'aibain_expires_at': None},
    {'aibain_expires_at': datetime(2020, 1, 1)},
    {'kongming_expires_at': datetime(2020, 1, 1)},
    {'kongming_expires_at': datetime(2099, 1, 1)},
])
def test_ineligible_accounts_cannot_apply(checkout, changes):
    client, app, member_id, headers, _ = checkout
    with app.app_context():
        member = db.session.get(User, member_id)
        for field, value in changes.items():
            setattr(member, field, value)
        db.session.commit()
    assert submit(client, {}).status_code == 401
    assert submit(client, headers).status_code in (403, 409)
    with app.app_context():
        assert SubscriptionRequest.query.count() == 0


@pytest.mark.parametrize('request_type,note', [
    (PLAN, None),
    ('aibain_kongming', None),
    ('aibain_addon', '[ai_bundle_v2] approved bundle'),
])
def test_archived_approved_entitlement_remains_conversion_history(checkout, request_type, note):
    client, app, member_id, headers, _ = checkout
    with app.app_context():
        db.session.add(SubscriptionRequest(
            user_id=member_id, request_type=request_type, from_tier='pro', to_tier='pro',
            status='approved', admin_note=note, archived_at=datetime(2020, 1, 1),
        ))
        db.session.commit()
    assert client.get(STATUS, headers=headers).json['user']['ai_bundle_conversion']['eligible'] is False
    assert submit(client, headers).status_code == 409


def test_rejected_conversion_can_be_resubmitted(checkout):
    client, _, _, headers, admin_headers = checkout
    first = submit(client, headers).json['request']['id']
    rejected = client.put(f'/api/admin/subscriptions/{first}/reject', headers=admin_headers, json={})
    assert rejected.status_code == 200
    assert client.get(STATUS, headers=headers).json['user']['ai_bundle_conversion']['eligible'] is True
    second = submit(client, headers)
    assert second.status_code == 201
    assert second.json['request']['id'] != first


@pytest.mark.parametrize('field,value', [
    ('status', 'suspended'),
    ('aibain_enabled', False),
    ('aibain_expires_at', datetime(2020, 1, 1)),
    ('aibain_expires_at', datetime(2099, 1, 1)),
    ('kongming_expires_at', datetime(2099, 1, 1)),
])
def test_pending_conversion_cannot_approve_changed_entitlement(checkout, field, value):
    client, app, member_id, headers, admin_headers = checkout
    request_id = submit(client, headers).json['request']['id']
    with app.app_context():
        setattr(db.session.get(User, member_id), field, value)
        db.session.commit()
    response = client.put(f'/api/admin/subscriptions/{request_id}/approve', headers=admin_headers)
    assert response.status_code == 409
    with app.app_context():
        assert db.session.get(SubscriptionRequest, request_id).status == 'pending'
        expected_kongming = value if field == 'kongming_expires_at' else None
        assert db.session.get(User, member_id).kongming_expires_at == expected_kongming




def test_startup_adds_nullable_conversion_expiry_to_legacy_database(tmp_path):
    db_path = tmp_path / 'legacy.db'
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
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
        connection.execute("""
            INSERT INTO subscription_requests (id, user_id, request_type, from_tier, to_tier, status)
            VALUES (1, 1, 'aibain_addon', 'pro', 'pro', 'approved')
        """)
    config = {
        'TESTING': True, 'SECRET_KEY': 'legacy-db-test',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    }
    for _ in range(2):
        app = create_app(config)
        with app.app_context():
            old_request = db.session.get(SubscriptionRequest, 1)
            assert old_request.status == 'approved'
            assert old_request.to_dict()['conversion_expires_at'] is None



def test_concurrent_conversion_submissions_and_approvals_grant_once(checkout):
    _, app, member_id, headers, admin_headers = checkout

    def concurrent_calls(call):
        barrier = Barrier(2)

        def run():
            client = app.test_client()
            barrier.wait(timeout=5)
            return call(client)

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            return [future.result(timeout=10) for future in futures]

    submitted = concurrent_calls(lambda client: submit(client, headers))
    assert sorted(response.status_code for response in submitted) == [201, 409]
    saved = next(response.json['request'] for response in submitted if response.status_code == 201)
    approved = concurrent_calls(lambda client: client.put(
        f"/api/admin/subscriptions/{saved['id']}/approve", headers=admin_headers,
    ))
    assert [response.status_code for response in approved] == [200, 200]
    assert sum(bool(response.json.get('already_processed')) for response in approved) == 1
    with app.app_context():
        assert SubscriptionRequest.query.filter_by(user_id=member_id).count() == 1
        assert AdminAuditLog.query.filter_by(
            target_user_id=member_id, action='approve_aibain_kongming_conversion',
        ).count() == 1


def test_elapsed_captured_expiry_prevents_approval(checkout, monkeypatch):
    client, app, member_id, headers, admin_headers = checkout
    saved = submit(client, headers).json['request']
    expiry = datetime.fromisoformat(saved['conversion_expires_at']).replace(tzinfo=None)

    class ClockAtExpiry(datetime):
        @classmethod
        def utcnow(cls):
            return expiry

    monkeypatch.setattr(user_model, 'datetime', ClockAtExpiry)
    approval = client.put(f"/api/admin/subscriptions/{saved['id']}/approve", headers=admin_headers)
    assert approval.status_code == 409
    with app.app_context():
        assert db.session.get(SubscriptionRequest, saved['id']).status == 'pending'
        assert db.session.get(User, member_id).kongming_expires_at is None
