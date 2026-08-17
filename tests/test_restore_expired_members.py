# -*- coding: utf-8 -*-
"""suspended 로 굳은 '만료' 회원 복구 선별 테스트.

만료 스레드가 2026-08-16 이전에 만료 Pro 를 suspended 로 만들어버린 회원을
expired 로 복구한다. 선별 기준:

    status='suspended' AND pro_expiry_alert_stage='expired'
    AND 관리자 set_status→suspended audit 기록 없음

관리자가 수동 정지한 회원은 절대 건드리지 않는다.
"""
from datetime import datetime, timezone

import pytest

from app import create_app
from app.models import db
from app.models.user import AdminAuditLog, SubscriptionRequest, User
from scripts.restore_expired_members import find_restorable, restore


@pytest.fixture()
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'restore-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        yield application
        db.session.remove()


def _mk(email, status, stage=None, tier=None):
    u = User(email=email, name=email.split('@')[0], status=status,
             tier=tier, role='user', pro_expiry_alert_stage=stage)
    u.set_password('pw12345678')
    db.session.add(u)
    db.session.commit()
    return u


def test_selects_only_expiry_suspended(app):
    loop_victim = _mk('victim@example.com', 'suspended', stage='expired')
    manual = _mk('manual@example.com', 'suspended', stage='expired')
    db.session.add(AdminAuditLog(admin_id=1, target_user_id=manual.id,
                                 action='set_status',
                                 after='{"status": "suspended"}'))
    manual_no_stage = _mk('manual2@example.com', 'suspended')  # 스레드 흔적 없음
    normal = _mk('ok@example.com', 'approved', tier='pro')
    db.session.commit()

    ids = {u.id for u in find_restorable()}
    assert loop_victim.id in ids
    assert manual.id not in ids           # 수동 정지 audit 있음 → 제외
    assert manual_no_stage.id not in ids  # 만료 스레드 흔적 없음 → 제외
    assert normal.id not in ids


def test_manual_unsuspend_then_resuspend_still_excluded(app):
    """정지→해제→재정지 이력이 있어도 마지막이 수동 정지면 제외."""
    u = _mk('flip@example.com', 'suspended', stage='expired')
    db.session.add(AdminAuditLog(admin_id=1, target_user_id=u.id,
                                 action='set_status', after='{"status": "approved"}'))
    db.session.add(AdminAuditLog(admin_id=1, target_user_id=u.id,
                                 action='set_status', after='{"status": "suspended"}'))
    db.session.commit()
    assert u.id not in {x.id for x in find_restorable()}


def test_restore_sets_expired_and_recovers_tier(app):
    u = _mk('victim2@example.com', 'suspended', stage='expired')
    db.session.add(SubscriptionRequest(user_id=u.id, request_type='upgrade',
                                       from_tier='none', to_tier='premium',
                                       status='approved'))
    db.session.commit()
    report = restore([u], apply=True)
    db.session.refresh(u)
    assert u.status == 'expired'
    assert u.tier == 'premium'            # 마지막 승인 요청에서 복원
    assert u.pro_expires_at is not None   # is_pro_expired 판정 가능
    assert report[0]['restored_tier'] == 'premium'
    # audit 기록이 남는다
    log = AdminAuditLog.query.filter_by(action='restore_expired',
                                        target_user_id=u.id).first()
    assert log is not None


def test_restore_defaults_to_pro_without_history(app):
    u = _mk('nohist@example.com', 'suspended', stage='expired')
    restore([u], apply=True)
    db.session.refresh(u)
    assert u.tier == 'pro'


def test_dry_run_changes_nothing(app):
    u = _mk('dry@example.com', 'suspended', stage='expired')
    restore([u], apply=False)
    db.session.refresh(u)
    assert u.status == 'suspended'
    assert AdminAuditLog.query.filter_by(action='restore_expired').count() == 0
