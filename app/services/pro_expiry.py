# -*- coding: utf-8 -*-
"""Pro 구독 만료 스윕 — 만료는 '정지'가 아니라 '재구독 유도' 상태다.

app/__init__.py 의 1시간 주기 스레드에서 호출된다. 예전에는 이 로직이 스레드
클로저 안에 인라인으로 있어 테스트가 불가능했고, 만료 시 tier=None +
status='suspended' 로 만들어 로그인 자체가 막혔다(수동 정지와 동일 취급).
API 게이트(_enforce_pro_access)의 처리와 결과를 통일한다:

    status='expired'  +  tier / pro_expires_at 보존

- tier 보존: 재구독 플로우가 "이전 플랜" 을 보여주고 같은 플랜 재신청 예외
  (is_expired_resubscribe) 를 판정하는 재료다.
- status='expired' 는 로그인 허용 → 프론트 가드가 /plan-select?resubscribe=1
  로 안내한다. 'suspended' 는 관리자 수동 정지 전용.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

RESUBSCRIBE_URL = 'https://bit-man.net/plan-select?resubscribe=1'

# notify(user, stage, when) — stage: 'd3' | 'd1' | 'expired'
Notify = Callable[[object, str, str], None]


def build_expiry_alert_message(*, name: str, email: str, user_id: int,
                               stage: str, when: str) -> str:
    """만료 단계별 관리자 텔레그램 본문."""
    label_map = {'d3': 'D-3 만료 임박', 'd1': 'D-1 만료 임박', 'expired': '만료 — 재구독 대기'}
    lines = [
        f"⏰ <b>Pro 구독 {label_map.get(stage, stage)}</b>",
        "",
        f"👤 {name} ({email})",
        f"📅 만료일: {when}",
        f"🆔 user_id={user_id}",
    ]
    if stage == 'expired':
        lines.append(f"🔁 재구독 안내: {RESUBSCRIBE_URL}")
    return "\n".join(lines)


def run_expiry_sweep(notify: Notify | None = None) -> dict:
    """만료/D-1/D-3 3단계 스윕. Flask app context 안에서 호출해야 한다.

    반환: {'expired': n, 'd1': n, 'd3': n}
    """
    from app.models import db
    from app.models.user import User

    if notify is None:
        notify = lambda user, stage, when: None  # noqa: E731

    now = datetime.now(timezone.utc)
    d1_window = now + timedelta(days=1)
    d3_window = now + timedelta(days=3)

    # 1) 만료 — paused 유저 skip (AI Brain 활성 중 Pro 카운터 일시정지)
    expired = User.query.filter(
        User.tier == 'pro',
        User.pro_expires_at.isnot(None),
        User.pro_expires_at < now,
        User.pro_paused_at.is_(None),
        User.status != 'expired',   # 이미 처리된 유저 재방문 방지
    ).all()
    for user in expired:
        when = user.pro_expires_at.isoformat() if user.pro_expires_at else '?'
        print(f"[Expiry] {user.email}: pro → expired (재구독 대기, {user.pro_expires_at})")
        if user.pro_expiry_alert_stage != 'expired':
            notify(user, 'expired', when)
        # '정지'가 아니라 '만료' — tier/만료일 보존. 재구독 플로우가 이 정보를 쓴다.
        user.status = 'expired'
        user.pro_expiry_alert_stage = 'expired'

    # 2) D-1 임박
    d1_users = User.query.filter(
        User.tier == 'pro',
        User.pro_expires_at.isnot(None),
        User.pro_expires_at >= now,
        User.pro_expires_at < d1_window,
        User.pro_paused_at.is_(None),
    ).all()
    d1_notified = []
    for user in d1_users:
        if user.pro_expiry_alert_stage in ('d1', 'expired'):
            continue
        notify(user, 'd1', user.pro_expires_at.isoformat())
        user.pro_expiry_alert_stage = 'd1'
        d1_notified.append(user)

    # 3) D-3 임박
    d3_users = User.query.filter(
        User.tier == 'pro',
        User.pro_expires_at.isnot(None),
        User.pro_expires_at >= d1_window,
        User.pro_expires_at < d3_window,
        User.pro_paused_at.is_(None),
    ).all()
    d3_notified = []
    for user in d3_users:
        if user.pro_expiry_alert_stage in ('d3', 'd1', 'expired'):
            continue
        notify(user, 'd3', user.pro_expires_at.isoformat())
        user.pro_expiry_alert_stage = 'd3'
        d3_notified.append(user)

    if expired or d1_notified or d3_notified:
        db.session.commit()

    return {'expired': len(expired), 'd1': len(d1_notified), 'd3': len(d3_notified)}
