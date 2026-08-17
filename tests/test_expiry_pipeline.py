# -*- coding: utf-8 -*-
"""만료 스윕 회귀 테스트 — 만료는 '정지'가 아니라 '재구독 유도' 상태다.

2026-08-16 이전: _expiry_loop 가 만료 Pro 를 tier=None + status='suspended' 로
만들어 로그인 자체가 403(수동 정지와 동일 취급)으로 막히고 재구독 경로가
차단됐다. API 게이트 경로(status='expired', tier 보존)와 결과를 통일한다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.models import db
from app.models.user import User
from app.services.pro_expiry import build_expiry_alert_message, run_expiry_sweep


@pytest.fixture()
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'expiry-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        yield application
        db.session.remove()


def _mk_user(email, **kw):
    u = User(email=email, name=email.split('@')[0], status='approved',
             tier='pro', role='user')
    u.set_password('pw12345678')
    for k, v in kw.items():
        setattr(u, k, v)
    db.session.add(u)
    db.session.commit()
    return u


def test_expired_pro_becomes_expired_not_suspended(app):
    past = datetime.now(timezone.utc) - timedelta(days=2)
    u = _mk_user('gone@example.com', pro_expires_at=past)
    run_expiry_sweep(notify=lambda *a, **k: None)
    db.session.refresh(u)
    assert u.status == 'expired'            # suspended 가 아니다
    assert u.tier == 'pro'                  # 플랜 이력 보존 (재구독 UX 재료)
    assert u.pro_expires_at is not None     # 만료일 보존
    assert u.pro_expiry_alert_stage == 'expired'


def test_active_pro_untouched(app):
    future = datetime.now(timezone.utc) + timedelta(days=10)
    u = _mk_user('alive@example.com', pro_expires_at=future)
    run_expiry_sweep(notify=lambda *a, **k: None)
    db.session.refresh(u)
    assert u.status == 'approved' and u.tier == 'pro'


def test_paused_pro_skipped(app):
    past = datetime.now(timezone.utc) - timedelta(days=2)
    u = _mk_user('paused@example.com', pro_expires_at=past,
                 pro_paused_at=datetime.now(timezone.utc))
    run_expiry_sweep(notify=lambda *a, **k: None)
    db.session.refresh(u)
    assert u.status == 'approved'


def test_d1_stage_advances_once(app):
    soon = datetime.now(timezone.utc) + timedelta(hours=12)
    u = _mk_user('d1@example.com', pro_expires_at=soon)
    calls = []
    run_expiry_sweep(notify=lambda user, stage, when: calls.append(stage))
    run_expiry_sweep(notify=lambda user, stage, when: calls.append(stage))
    db.session.refresh(u)
    assert u.pro_expiry_alert_stage == 'd1'
    assert calls == ['d1']  # 두 번째 스윕은 중복 알림 없음


def test_d3_stage(app):
    later = datetime.now(timezone.utc) + timedelta(days=2)
    u = _mk_user('d3@example.com', pro_expires_at=later)
    calls = []
    run_expiry_sweep(notify=lambda user, stage, when: calls.append(stage))
    db.session.refresh(u)
    assert u.pro_expiry_alert_stage == 'd3'
    assert calls == ['d3']


def test_expired_user_can_still_login(app):
    """expired 상태는 로그인 가능해야 재구독 플로우에 진입한다."""
    past = datetime.now(timezone.utc) - timedelta(days=2)
    _mk_user('relogin@example.com', pro_expires_at=past)
    run_expiry_sweep(notify=lambda *a, **k: None)

    client = app.test_client()
    r = client.post('/api/auth/login', json={
        'email': 'relogin@example.com', 'password': 'pw12345678',
    })
    assert r.status_code == 200, r.get_json()
    assert r.get_json()['user']['status'] == 'expired'


def test_expired_alert_message_contains_resubscribe_link():
    msg = build_expiry_alert_message(
        name='홍길동', email='u@example.com', user_id=7,
        stage='expired', when='2026-08-16T00:00:00',
    )
    assert 'plan-select?resubscribe=1' in msg
    assert '정지' not in msg
