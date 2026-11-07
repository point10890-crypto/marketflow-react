from datetime import datetime, timedelta, timezone
import json

from app import _apply_aibain_expiry_state
from app.models import db
from app.models.user import AdminAuditLog, SubscriptionRequest
from app.services.subscription_lifecycle import utc, ensure_archive_column
import app.routes.admin as admin_routes
from tests.test_admin_subscription_lifecycle import lifecycle, _member, _headers


def test_late_ai_expiry_resumes_at_actual_end_not_worker_time(lifecycle):
    now = datetime.now(timezone.utc)
    user = _member(pro_expires_at=now - timedelta(days=20),
                   pro_paused_at=now - timedelta(days=35), aibain_enabled=True,
                   aibain_expires_at=now - timedelta(days=10))
    # 25 paid AI days preserve 25 PRO days, not all 35 days of worker downtime.
    assert user.is_pro_paused is False
    assert user.is_pro_expired is False
    elapsed = _apply_aibain_expiry_state(user, now)
    assert abs(elapsed.total_seconds() - timedelta(days=25).total_seconds()) < 1
    assert abs((user.pro_expires_at - now).total_seconds() - timedelta(days=5).total_seconds()) < 1


def test_expired_pause_marker_cannot_grant_access_forever(lifecycle):
    now = datetime.now(timezone.utc)
    user = _member(pro_expires_at=now - timedelta(days=30),
                   pro_paused_at=now - timedelta(days=35), aibain_enabled=True,
                   aibain_expires_at=now - timedelta(days=10))
    assert user.is_pro_expired is True


def test_bundle_revoke_ends_both_services_preserves_pro_and_audits(lifecycle):
    now = datetime.now(timezone.utc)
    user = _member(pro_expires_at=now + timedelta(days=2), pro_paused_at=now - timedelta(days=5),
                   aibain_enabled=True, aibain_expires_at=now + timedelta(days=20),
                   kongming_expires_at=now + timedelta(days=20))
    result = lifecycle.client.post(f'/api/admin/users/{user.id}/ai-bundle/revoke',
                                  headers=lifecycle.headers, json={'note': 'operator withdrawal'})
    assert result.status_code == 200
    payload = result.get_json()['user']
    assert not payload['is_aibain_active'] and not payload['is_kongming_active']
    assert payload['status'] == 'approved' and not payload['is_pro_expired']
    assert payload['pro_paused_at'] is None
    assert AdminAuditLog.query.filter_by(action='revoke_ai_bundle', target_user_id=user.id).count() == 1
    expiry = payload['pro_expires_at']
    repeat = lifecycle.client.post(f'/api/admin/users/{user.id}/ai-bundle/revoke',
                                  headers=lifecycle.headers, json={'note': 'repeat'})
    assert utc(datetime.fromisoformat(repeat.get_json()['user']['pro_expires_at'])) == utc(datetime.fromisoformat(expiry))


def test_direct_bundle_grant_preserves_pending_payment_and_requires_base(lifecycle):
    user = _member(tier=None, status='pending', pro_expires_at=None)
    url = f'/api/admin/users/{user.id}/ai-bundle/grant'
    assert lifecycle.client.post(url, headers=lifecycle.headers, json={}).status_code == 409
    user.tier = 'pro'; user.status = 'approved'; user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=20)
    db.session.commit()
    success = lifecycle.client.post(url, headers=lifecycle.headers, json={'note': 'manual grant'})
    assert success.status_code == 200
    payload = success.get_json()['user']
    assert payload['is_aibain_active'] and payload['is_kongming_active'] and payload['is_pro_paused']
    pending = SubscriptionRequest(user_id=user.id, request_type='aibain_renewal', from_tier='pro', to_tier='pro')
    db.session.add(pending); db.session.commit()
    assert lifecycle.client.post(url, headers=lifecycle.headers, json={}).status_code == 409


def test_request_withdraw_and_delete_release_pending_without_erasing_audit(lifecycle):
    user = _member(tier=None, status='pending', requested_tier='pro', pro_expires_at=None)
    pending = SubscriptionRequest(user_id=user.id, request_type='upgrade', from_tier='none', to_tier='pro',
                                  amount='100,000원', admin_note='[ai_bundle_v2] AI Brain')
    db.session.add(pending); db.session.commit()
    request_id = pending.id
    url = f'/api/admin/subscriptions/{request_id}'
    denied = lifecycle.client.put(url + '/withdraw', headers=_headers(user), json={})
    assert denied.status_code == 403
    result = lifecycle.client.put(url + '/withdraw', headers=lifecycle.headers, json={'note': 'deposit cancelled'})
    assert result.status_code == 200 and result.get_json()['request']['status'] == 'withdrawn'
    assert user.get_pending_subscription_request() is None and user.requested_tier is None
    assert '[ai_bundle_v2]' in result.get_json()['request']['admin_note']
    deleted = lifecycle.client.delete(url, headers=lifecycle.headers)
    assert deleted.status_code == 200
    assert db.session.get(SubscriptionRequest, request_id).status == 'withdrawn'
    assert db.session.get(SubscriptionRequest, request_id).archived_at is not None
    assert not lifecycle.client.get('/api/admin/subscriptions', headers=lifecycle.headers).get_json()['requests']
    assert not lifecycle.client.get('/api/auth/subscription/status', headers=_headers(user)).get_json()['requests']
    audit = AdminAuditLog.query.filter_by(action='delete_subscription_request').one()
    assert json.loads(audit.before)['amount'] == '100,000원'


def test_approved_history_delete_does_not_revoke_paid_access(lifecycle):
    user = _member()
    req = SubscriptionRequest(user_id=user.id, request_type='renewal', from_tier='pro', to_tier='pro', status='approved')
    db.session.add(req); db.session.commit()
    url = f'/api/admin/subscriptions/{req.id}'
    assert lifecycle.client.put(url + '/withdraw', headers=lifecycle.headers, json={}).status_code == 409
    assert lifecycle.client.delete(url, headers=lifecycle.headers).status_code == 200
    assert user.status == 'approved' and not user.is_pro_expired
    assert db.session.get(SubscriptionRequest, req.id).status == 'approved'
    assert SubscriptionRequest.query.filter_by(status='approved').count() == 1
    assert db.session.get(SubscriptionRequest, req.id).archived_at is not None


def test_admin_subscription_filter_finds_unprocessed_base_and_ai_expiry(lifecycle):
    now = datetime.now(timezone.utc)
    base = _member(pro_expires_at=now - timedelta(hours=1))
    ai = _member(tier='premium', pro_expires_at=None, aibain_expires_at=now - timedelta(hours=1))
    _member()
    result = lifecycle.client.get('/api/admin/users?subscription_state=expired&page=1&per_page=10', headers=lifecycle.headers)
    assert result.status_code == 200
    assert {u['id'] for u in result.get_json()['users']} == {base.id, ai.id}
    assert all(u['subscription_lifecycle']['state'] == 'expired' for u in result.get_json()['users'])


def test_admin_cannot_revoke_or_grant_admin_account_bundle(lifecycle):
    for action in ['grant', 'revoke']:
        response = lifecycle.client.post(f'/api/admin/users/{lifecycle.admin.id}/ai-bundle/{action}',
                                         headers=lifecycle.headers, json={})
        assert response.status_code == 400


def test_request_mutation_rolls_back_when_audit_write_fails(lifecycle, monkeypatch):
    user = _member()
    req = SubscriptionRequest(user_id=user.id, request_type='renewal', from_tier='pro', to_tier='pro')
    db.session.add(req); db.session.commit()
    request_id = req.id
    def fail_audit(*args, **kwargs):
        raise RuntimeError('isolated audit failure')
    monkeypatch.setattr(admin_routes, '_record_audit', fail_audit)
    response = lifecycle.client.delete(f'/api/admin/subscriptions/{request_id}', headers=lifecycle.headers)
    assert response.status_code == 500
    assert db.session.get(SubscriptionRequest, request_id).status == 'pending'
    assert db.session.get(SubscriptionRequest, request_id).archived_at is None


def test_archive_migration_is_additive_and_repeatable():
    from sqlalchemy import create_engine, text
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE subscription_requests (id INTEGER PRIMARY KEY, status TEXT, amount TEXT)'))
        connection.execute(text("INSERT INTO subscription_requests VALUES (1, 'approved', '100000')"))
    ensure_archive_column(engine)
    ensure_archive_column(engine)
    with engine.connect() as connection:
        assert tuple(connection.execute(text('SELECT status, amount, archived_at FROM subscription_requests')).one()) == ('approved', '100000', None)
    engine.dispose()


def test_deleting_pending_application_allows_a_fresh_subscription(lifecycle):
    user = _member(status='pending', tier=None, requested_tier='pro', pro_expires_at=None)
    req = SubscriptionRequest(user_id=user.id, request_type='upgrade', from_tier='none', to_tier='pro')
    db.session.add(req); db.session.commit()
    assert lifecycle.client.delete(f'/api/admin/subscriptions/{req.id}', headers=lifecycle.headers).status_code == 200
    assert user.requested_tier is None and user.get_pending_subscription_request() is None
    result = lifecycle.client.post('/api/auth/subscription/request', headers=_headers(user), json={'to_tier': 'pro'})
    assert result.status_code == 201
    assert result.get_json()['request']['amount'] == '50,000원'


def test_renewing_after_late_ai_expiry_does_not_pause_the_unpaid_gap(lifecycle):
    now = datetime.now(timezone.utc)
    user = _member(pro_expires_at=now - timedelta(days=20), pro_paused_at=now - timedelta(days=35),
                   aibain_enabled=True, aibain_expires_at=now - timedelta(days=10),
                   kongming_expires_at=now - timedelta(days=10))
    result = lifecycle.client.post('/api/auth/subscription/request', headers=_headers(user),
                                   json={'to_tier': 'pro', 'includes_aibain': True, 'expected_amount': 50000})
    assert result.status_code == 201
    request_id = result.get_json()['request']['id']
    approved = lifecycle.client.put(f'/api/admin/subscriptions/{request_id}/approve', headers=lifecycle.headers)
    assert approved.status_code == 200
    payload = approved.get_json()['user']
    assert payload['is_pro_paused'] and payload['is_aibain_active'] and payload['is_kongming_active']
    assert abs((utc(datetime.fromisoformat(payload['pro_expires_at'])) - now - timedelta(days=5)).total_seconds()) < 2
    assert abs((utc(datetime.fromisoformat(payload['pro_paused_at'])) - now).total_seconds()) < 2
