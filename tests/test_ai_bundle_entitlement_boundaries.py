"""New bundle pricing and the effective PRO/AI access boundary, with no live accounts."""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app, _apply_aibain_expiry_state
from app.auth.decorators import generate_token, pro_required, admin_or_aibain_required
from app.models import db, user as user_model
from app.models.user import User
from app.routes import auth, admin
from app.services import kongming_verification, subscription_lifecycle, pro_expiry
from app.services.pro_expiry import run_expiry_sweep


@pytest.mark.parametrize('tier,base_days,expected_amount', [
    ('pro', 12, 50_000), ('premium', None, 50_000), (None, None, 100_000),
])
def test_new_bundle_keeps_base_access_through_ai_expiry(monkeypatch, tier, base_days, expected_amount):
    monkeypatch.setattr(auth, '_notify_admin_telegram', lambda *a, **k: None)
    monkeypatch.setattr(admin, '_notify_admin', lambda *a, **k: None)
    monkeypatch.setattr(admin, '_notify_member', lambda *a, **k: None)
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda **kw: {'items': []})
    monkeypatch.setattr(pro_expiry, '_notify_member_expiry', lambda *a, **k: None)
    app = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-policy-boundary',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:', 'SQLALCHEMY_ENGINE_OPTIONS': {}})

    @app.get('/api/kr/policy-base-probe')
    @pro_required
    def base_probe():
        return {'access': 'pro'}

    @app.get('/api/policy-ai-probe')
    @admin_or_aibain_required
    def ai_probe():
        return {'access': 'ai'}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    original_expiry = now+timedelta(days=base_days) if base_days else None
    with app.app_context():
        member = User(email='boundary@example.test', name='Boundary', password_hash='unused',
                      status='approved' if tier else 'pending', tier=tier, pro_expires_at=original_expiry)
        operator = User(email='operator@example.test', name='Operator', password_hash='unused',
                        status='approved', role='admin')
        db.session.add_all([member, operator]); db.session.commit()
        member_id = member.id
        headers = {'Authorization': 'Bearer '+generate_token(member.id)}
        operator_headers = {'Authorization': 'Bearer '+generate_token(operator.id)}

    client = app.test_client()
    target = tier or 'pro'
    requested = client.post('/api/auth/subscription/request', headers=headers, json={
        'to_tier': target, 'includes_aibain': True, 'expected_amount': expected_amount,
    })
    assert requested.status_code == 201
    saved = requested.json['request']
    assert saved['amount'] == f'{expected_amount:,}원'
    approved = client.put(f"/api/admin/subscriptions/{saved['id']}/approve", headers=operator_headers)
    assert approved.status_code == 200
    user = approved.json['user']
    ai_expiry = datetime.fromisoformat(user['aibain_expires_at']).replace(tzinfo=timezone.utc)
    assert user['aibain_expires_at'] == user['kongming_expires_at']
    assert user['tier'] == target and user['status'] == 'approved'

    point = ai_expiry-timedelta(seconds=1)
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return point.astimezone(tz) if tz else point.replace(tzinfo=None)
        @classmethod
        def utcnow(cls):
            return point.replace(tzinfo=None)
    monkeypatch.setattr(user_model, 'datetime', FrozenClock)
    monkeypatch.setattr(subscription_lifecycle, 'datetime', FrozenClock)
    monkeypatch.setattr(pro_expiry, 'datetime', FrozenClock)
    paths = ['/api/kr/policy-base-probe', '/api/policy-ai-probe',
             '/api/admin/mirofish/kongming/catalyst-validation']
    assert [client.get(path, headers=headers).status_code for path in paths] == [200, 200, 200]
    with app.app_context():
        run_expiry_sweep(notify=lambda *a, **k: None)
        assert db.session.get(User, member_id).status == 'approved'

    point = ai_expiry
    assert [client.get(path, headers=headers).status_code for path in paths] == [200, 403, 403]
    assert [client.get(path, headers=operator_headers).status_code for path in paths] == [200, 200, 200]
    with app.app_context():
        member = db.session.get(User, member_id)
        assert member.status == 'approved'
        _apply_aibain_expiry_state(member, ai_expiry+timedelta(days=2))
        db.session.commit()
        settled_expiry = member.pro_expires_at
        _apply_aibain_expiry_state(member, ai_expiry+timedelta(days=4))
        db.session.commit()
        assert member.pro_expires_at == settled_expiry
        if target == 'pro':
            expected_days = base_days or 30
            remaining = settled_expiry.replace(tzinfo=timezone.utc)-ai_expiry
            assert abs(remaining.total_seconds()-expected_days*86400) < 5
        else:
            assert settled_expiry is None
    if target == 'pro':
        point = settled_expiry.replace(tzinfo=timezone.utc)
        assert client.get(paths[0], headers=headers).status_code == 403
