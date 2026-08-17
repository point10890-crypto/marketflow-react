# -*- coding: utf-8 -*-
"""관리자 API — 만료 회원 노출/필터/이탈 지표 회귀 테스트.

사각지대 제로 원칙의 만료 확장: 만료 회원은 '재구독 유도 대상' 으로
/api/admin/subscriptions 에 떠야 하고, users 필터와 stats 에서도 보인다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import SubscriptionRequest, User


@pytest.fixture()
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'admin-expired-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        yield application
        db.session.remove()


def _mk(email, *, status='approved', tier='pro', role='user',
        expires=None, last_login=None):
    u = User(email=email, name=email.split('@')[0], status=status, tier=tier,
             role=role, pro_expires_at=expires, last_login_at=last_login)
    u.set_password('pw12345678')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def admin_client(app):
    admin = _mk('admin@example.com', role='admin', tier='premium')
    client = app.test_client()
    token = generate_token(admin.id)
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    return client


def test_subscriptions_exposes_expired_members(app, admin_client):
    past = datetime.now(timezone.utc) - timedelta(days=5)
    _mk('lapsed@example.com', status='expired', tier='pro', expires=past)
    _mk('active@example.com', status='approved', tier='pro',
        expires=datetime.now(timezone.utc) + timedelta(days=10))

    r = admin_client.get('/api/admin/subscriptions')
    assert r.status_code == 200
    body = r.get_json()
    assert 'expired_members' in body
    emails = [m['email'] for m in body['expired_members']]
    assert 'lapsed@example.com' in emails
    assert 'active@example.com' not in emails
    m = next(x for x in body['expired_members'] if x['email'] == 'lapsed@example.com')
    assert m['tier'] == 'pro'
    assert m['days_since_expiry'] >= 4


def test_expired_member_with_pending_request_moves_to_requests(app, admin_client):
    """재구독 신청을 낸 만료 회원은 requests 갈래에만 — 중복 노출 방지."""
    past = datetime.now(timezone.utc) - timedelta(days=2)
    u = _mk('applied@example.com', status='expired', tier='pro', expires=past)
    db.session.add(SubscriptionRequest(user_id=u.id, request_type='renewal',
                                       from_tier='pro', to_tier='pro',
                                       status='pending'))
    db.session.commit()

    body = admin_client.get('/api/admin/subscriptions').get_json()
    assert 'applied@example.com' not in [m['email'] for m in body['expired_members']]
    assert any(r['user_email'] == 'applied@example.com' for r in body['requests'])


def test_users_filter_expired(app, admin_client):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _mk('exp@example.com', status='expired', tier='pro', expires=past)
    _mk('app@example.com', status='approved', tier='pro')

    r = admin_client.get('/api/admin/users?status=expired')
    emails = [u['email'] for u in r.get_json()['users']]
    assert emails == ['exp@example.com']


def test_stats_churn_metrics(app, admin_client):
    now = datetime.now(timezone.utc)
    _mk('d3@example.com', status='approved', tier='pro',
        expires=now + timedelta(days=2))
    _mk('lapsed@example.com', status='expired', tier='pro',
        expires=now - timedelta(days=3))
    resub = _mk('back@example.com', status='approved', tier='pro',
                expires=now + timedelta(days=28))
    db.session.add(SubscriptionRequest(
        user_id=resub.id, request_type='renewal', from_tier='pro',
        to_tier='pro', status='approved', processed_at=now))
    db.session.commit()

    stats = admin_client.get('/api/admin/dashboard').get_json()
    assert 'churn' in stats
    assert stats['churn']['expiring_d3'] >= 1
    assert stats['churn']['expired_unrenewed'] >= 1
    assert stats['churn']['resubscribed_this_month'] >= 1
    assert stats['expired_users'] >= 1
