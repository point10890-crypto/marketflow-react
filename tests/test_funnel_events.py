# -*- coding: utf-8 -*-
"""퍼널 이벤트 계측 — 가입 / 구독 신청 / 승인 / 거절 / tier 부여 기록 + 관리자 요약 엔드포인트."""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.funnel import FunnelEvent, record_funnel_event
from app.models.user import SubscriptionRequest, User


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'funnel-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        yield application
        db.session.remove()


def _mk_user(email, **kw):
    u = User(email=email, name=email.split('@')[0], status='approved', tier='premium', role='user')
    u.set_password('Pass1234!')
    for k, v in kw.items():
        setattr(u, k, v)
    db.session.add(u)
    db.session.commit()
    return u


def _auth(user):
    return {'Authorization': f'Bearer {generate_token(user.id)}'}


def _events(event=None):
    q = FunnelEvent.query
    if event:
        q = q.filter_by(event=event)
    return q.order_by(FunnelEvent.id).all()


def test_register_records_funnel_event(app):
    _mk_user('admin@example.com', role='admin')  # 첫 유저(부트스트랩) 우회
    res = app.test_client().post('/api/auth/register', json={
        'email': 'new@example.com', 'password': 'Pass1234!', 'name': '신규', 'requested_tier': 'pro',
    })
    assert res.status_code == 201
    new_id = res.get_json()['user']['id']

    rows = _events('register')
    assert len(rows) == 1
    assert rows[0].user_id == new_id
    assert rows[0].to_dict()['meta'] == {'requested_tier': 'pro', 'is_first_user': False}


def test_full_funnel_events_and_summary(app):
    admin = _mk_user('admin@example.com', role='admin')
    client = app.test_client()

    reg = client.post('/api/auth/register', json={
        'email': 'buyer@example.com', 'password': 'Pass1234!', 'name': '구매자',
    })
    assert reg.status_code == 201
    member_token = reg.get_json()['token']
    member_id = reg.get_json()['user']['id']

    req = client.post(
        '/api/auth/subscription/request',
        json={'to_tier': 'pro', 'depositor_name': '구매자'},
        headers={'Authorization': f'Bearer {member_token}'},
    )
    assert req.status_code == 201
    req_id = req.get_json()['request']['id']
    ev = _events('subscription_request')
    assert len(ev) == 1 and ev[0].user_id == member_id
    assert ev[0].to_dict()['meta']['request_id'] == req_id
    assert ev[0].to_dict()['meta']['request_type'] == 'upgrade'

    approved = client.put(f'/api/admin/subscriptions/{req_id}/approve', headers=_auth(admin))
    assert approved.status_code == 200
    ev = _events('approve')
    assert len(ev) == 1 and ev[0].user_id == member_id
    assert ev[0].to_dict()['meta']['request_id'] == req_id

    summary = client.get('/api/admin/funnel/summary?days=30', headers=_auth(admin))
    assert summary.status_code == 200
    body = summary.get_json()
    assert body['days'] == 30
    assert body['counts'] == {
        'register': 1, 'subscription_request': 1, 'approve': 1, 'reject': 0, 'tier_grant': 0,
    }
    assert body['users'] == {'registered': 1, 'requested': 1, 'approved': 1}
    assert body['conversion'] == {
        'register_to_request': 1.0, 'request_to_approve': 1.0, 'register_to_approve': 1.0,
    }
    assert body['approved_requests_sampled'] == 1
    assert body['median_request_to_approve_hours'] is not None
    assert 0 <= body['median_request_to_approve_hours'] < 1


def test_reject_and_tier_grant_record_events(app):
    admin = _mk_user('admin@example.com', role='admin')
    member = _mk_user('pending@example.com', status='pending', tier=None)
    req = SubscriptionRequest(user_id=member.id, request_type='upgrade', from_tier='none', to_tier='pro')
    db.session.add(req)
    db.session.commit()
    client = app.test_client()

    res = client.put(f'/api/admin/subscriptions/{req.id}/reject', json={'note': '미입금'}, headers=_auth(admin))
    assert res.status_code == 200
    rej = _events('reject')
    assert len(rej) == 1 and rej[0].user_id == member.id
    assert rej[0].to_dict()['meta']['request_id'] == req.id

    res = client.put(f'/api/admin/users/{member.id}/tier', json={'tier': 'pro'}, headers=_auth(admin))
    assert res.status_code == 200
    grant = _events('tier_grant')
    assert len(grant) == 1 and grant[0].user_id == member.id
    assert grant[0].to_dict()['meta'] == {'from_tier': None, 'to_tier': 'pro', 'was_status': 'pending'}

    body = client.get('/api/admin/funnel/summary', headers=_auth(admin)).get_json()
    assert body['counts']['reject'] == 1 and body['counts']['tier_grant'] == 1
    # tier 직접 부여도 '승인' 으로 집계, 가입 이벤트가 없으니 register 기준 비율은 null
    assert body['users']['approved'] == 1
    assert body['users']['registered'] == 0
    assert body['conversion']['register_to_request'] is None
    assert body['conversion']['register_to_approve'] is None
    assert body['median_request_to_approve_hours'] is None


def test_summary_window_and_days_clamp(app):
    admin = _mk_user('admin@example.com', role='admin')
    old = FunnelEvent(user_id=1, event='register',
                      created_at=datetime.now(timezone.utc) - timedelta(days=40))
    recent = FunnelEvent(user_id=2, event='register',
                         created_at=datetime.now(timezone.utc) - timedelta(days=5))
    db.session.add_all([old, recent])
    db.session.commit()
    client = app.test_client()

    assert client.get('/api/admin/funnel/summary?days=30', headers=_auth(admin)).get_json()['counts']['register'] == 1
    assert client.get('/api/admin/funnel/summary?days=60', headers=_auth(admin)).get_json()['counts']['register'] == 2
    body = client.get('/api/admin/funnel/summary?days=99999', headers=_auth(admin)).get_json()
    assert body['days'] == 365
    body = client.get('/api/admin/funnel/summary?days=abc', headers=_auth(admin)).get_json()
    assert body['days'] == 30


def test_summary_requires_admin(app):
    member = _mk_user('member@example.com')
    res = app.test_client().get('/api/admin/funnel/summary', headers=_auth(member))
    assert res.status_code in (401, 403)
    assert app.test_client().get('/api/admin/funnel/summary').status_code == 401


def test_record_funnel_event_is_best_effort(app, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('db down')

    monkeypatch.setattr(db.session, 'commit', boom)
    assert record_funnel_event('register', 1, {'x': 1}) is False
