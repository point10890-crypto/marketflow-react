# -*- coding: utf-8 -*-
"""만료 스레드가 suspended 로 굳혀버린 회원을 expired 로 복구한다 (1회성).

2026-08-16 이전 만료 스레드는 만료 Pro 를 tier=None + status='suspended' 로
만들었다. suspended 는 로그인 자체가 403 이라 재구독 경로가 차단된다.
이 스크립트는 그 피해자만 골라 status='expired' + tier 복원으로 되돌린다.

선별 기준 (전부 만족):
  - status = 'suspended'
  - pro_expiry_alert_stage = 'expired'   (만료 스레드가 남긴 흔적)
  - AdminAuditLog 에 관리자의 set_status→suspended 기록 없음 (수동 정지 제외)

tier 복원 우선순위: 마지막 approved SubscriptionRequest.to_tier
  → audit set_tier 의 before.tier → 'pro'

    python scripts/restore_expired_members.py           # dry-run (변경 없음)
    python scripts/restore_expired_members.py --apply   # 실제 복구
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def find_restorable():
    """만료 스레드 피해자 목록 (수동 정지 회원 제외)."""
    from app.models.user import AdminAuditLog, User

    candidates = User.query.filter(
        User.status == 'suspended',
        User.pro_expiry_alert_stage == 'expired',
    ).all()

    restorable = []
    for user in candidates:
        # 이 유저의 마지막 set_status 가 수동 suspended 면 관리자 의사 존중.
        last_set_status = (
            AdminAuditLog.query
            .filter_by(action='set_status', target_user_id=user.id)
            .order_by(AdminAuditLog.id.desc())
            .first()
        )
        if last_set_status is not None:
            try:
                after = json.loads(last_set_status.after or '{}')
            except (TypeError, ValueError):
                after = {}
            if after.get('status') == 'suspended':
                continue
        restorable.append(user)
    return restorable


def _recover_tier(user) -> str:
    from app.models.user import AdminAuditLog, SubscriptionRequest

    last_approved = (
        SubscriptionRequest.query
        .filter_by(user_id=user.id, status='approved')
        .order_by(SubscriptionRequest.id.desc())
        .first()
    )
    if last_approved and last_approved.to_tier in ('pro', 'premium'):
        return last_approved.to_tier

    last_set_tier = (
        AdminAuditLog.query
        .filter_by(action='set_tier', target_user_id=user.id)
        .order_by(AdminAuditLog.id.desc())
        .first()
    )
    if last_set_tier is not None:
        try:
            before = json.loads(last_set_tier.before or '{}')
        except (TypeError, ValueError):
            before = {}
        if before.get('tier') in ('pro', 'premium'):
            return before['tier']

    return 'pro'


def restore(users, *, apply: bool) -> list[dict]:
    """대상 유저들을 expired 로 복구. apply=False 면 리포트만."""
    from app.models import db
    from app.models.user import AdminAuditLog

    now = datetime.now(timezone.utc)
    report = []
    for user in users:
        tier = user.tier if user.tier in ('pro', 'premium') else _recover_tier(user)
        entry = {
            'id': user.id, 'email': user.email, 'name': user.name,
            'restored_tier': tier,
        }
        report.append(entry)
        if not apply:
            continue

        before = {'status': user.status, 'tier': user.tier}
        user.status = 'expired'
        user.tier = tier
        # premium 은 무기한이지만 여기서는 '만료된 회원' 복구이므로 재구독을
        # 거쳐야 활성화된다. is_pro_expired 판정이 가능하도록 과거 시각을 준다.
        if user.pro_expires_at is None:
            user.pro_expires_at = now - timedelta(seconds=1)
        db.session.add(AdminAuditLog(
            admin_id=None, admin_email='system:restore_expired_members',
            action='restore_expired', target_user_id=user.id,
            target_email=user.email,
            before=json.dumps(before, ensure_ascii=False),
            after=json.dumps({'status': 'expired', 'tier': tier}, ensure_ascii=False),
            note='expiry-thread suspension rollback (2026-08-16)',
        ))
    if apply:
        db.session.commit()
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='실제로 복구 (기본: dry-run)')
    args = parser.parse_args()

    from app import create_app
    app = create_app()
    with app.app_context():
        users = find_restorable()
        print(f"복구 대상: {len(users)}명")
        report = restore(users, apply=args.apply)
        for e in report:
            print(f"  #{e['id']:4} {e['name']:16} {e['email']:32} -> expired / tier={e['restored_tier']}")
        if not args.apply:
            print("(dry-run — 적용하려면 --apply)")
        else:
            print("복구 완료. audit action='restore_expired' 로 기록됨.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
