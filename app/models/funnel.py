"""퍼널 이벤트 — 가입 → 구독 신청 → 승인 전환 계측.

IP 등 식별 정보는 저장하지 않는다 (user_id + 이벤트명 + 소량 meta 만).
기록은 best-effort: 실패해도 호출한 요청 흐름을 절대 깨지 않는다.

이벤트명(EVENT_*):
    register             회원가입 성공
    subscription_request 구독 신청 생성
    approve              관리자 구독요청 승인
    reject               관리자 구독요청 거절
    tier_grant           관리자 tier 직접 부여 (PUT /users/<id>/tier)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from app.models import db

EVENT_REGISTER = 'register'
EVENT_SUBSCRIPTION_REQUEST = 'subscription_request'
EVENT_APPROVE = 'approve'
EVENT_REJECT = 'reject'
EVENT_TIER_GRANT = 'tier_grant'

FUNNEL_EVENTS = (
    EVENT_REGISTER,
    EVENT_SUBSCRIPTION_REQUEST,
    EVENT_APPROVE,
    EVENT_REJECT,
    EVENT_TIER_GRANT,
)


class FunnelEvent(db.Model):
    __tablename__ = 'funnel_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=True, index=True)
    event = db.Column(db.String(40), nullable=False, index=True)
    meta = db.Column(db.Text, nullable=True)  # JSON
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        try:
            meta = json.loads(self.meta) if self.meta else None
        except Exception:
            meta = None
        return {
            'id': self.id,
            'user_id': self.user_id,
            'event': self.event,
            'meta': meta,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


def record_funnel_event(event: str, user_id: int | None = None, meta: dict | None = None) -> bool:
    """퍼널 이벤트 1건 기록 (best-effort, 자체 commit).

    이 함수가 commit 을 수행하므로 각 호출부는 본 트랜잭션 commit 직후에 부른다 —
    미완성 변경이 섞여 commit 되는 일이 없도록.
    """
    try:
        row = FunnelEvent(
            user_id=user_id,
            event=event,
            meta=json.dumps(meta, ensure_ascii=False, default=str) if meta else None,
        )
        db.session.add(row)
        db.session.commit()
        return True
    except Exception as e:  # noqa: BLE001 — 계측 실패는 요청 흐름을 깨지 않는다
        print(f"[FunnelEvent] failed: {type(e).__name__}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return False
