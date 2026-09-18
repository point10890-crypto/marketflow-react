"""Admin API routes — 관리자 전용 엔드포인트

Wave 2-4 추가:
- 모든 mutation에 audit log + 텔레그램 알림 (best-effort)
- /users 페이지네이션 + status/tier/q 필터 (backward-compatible: 단일 페이지면 기존 users 키 그대로)
- /users/<id>/extend, /users/<id>/expiry — 만료일 관리
- /users/bulk-tier, /users/bulk-approve — 일괄 처리
- /audit-log — 감사 로그 조회
"""

import os
import json
import hashlib
import time
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_
from app.models import db
from app.models.user import User, SubscriptionRequest, AdminAuditLog, AdminNotification
from app.models.funnel import (
    FunnelEvent, record_funnel_event,
    EVENT_REGISTER, EVENT_SUBSCRIPTION_REQUEST, EVENT_APPROVE, EVENT_REJECT, EVENT_TIER_GRANT,
)
from app.auth.decorators import admin_required
from app.services import member_telegram

admin_bp = Blueprint('admin', __name__)

_ADMIN_NOTIFY_DEDUPE_LOCK = threading.Lock()
_ADMIN_NOTIFY_DEDUPE_TTL_SECONDS = int(os.getenv('ADMIN_NOTIFY_DEDUPE_TTL_SECONDS', str(24 * 60 * 60)))
_ADMIN_NOTIFY_DEDUPE_MAX_KEYS = int(os.getenv('ADMIN_NOTIFY_DEDUPE_MAX_KEYS', '500'))


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼: 감사 로그 + 텔레그램 알림
# ─────────────────────────────────────────────────────────────────────────────

def _admin_user():
    return getattr(request, 'current_user', None)


def _record_audit(action: str, target_user: User | None, before: dict | None, after: dict | None, note: str = ''):
    """감사 로그 기록 (best-effort — 실패해도 메인 트랜잭션에 영향 X)"""
    try:
        admin = _admin_user()
        log = AdminAuditLog(
            admin_id=admin.id if admin else None,
            admin_email=admin.email if admin else None,
            action=action,
            target_user_id=target_user.id if target_user else None,
            target_email=target_user.email if target_user else None,
            before=json.dumps(before, default=str) if before else None,
            after=json.dumps(after, default=str) if after else None,
            note=note or None,
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"[AuditLog] failed: {type(e).__name__}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass


def _notify_admin(action: str, target_user: User, detail: str = ''):
    """관리자 텔레그램 알림 (fire-and-forget, 요청 스레드 블로킹 금지)

    텔레그램 API 가 느리거나 네트워크가 불안정할 때 승인 버튼이 '몇 분'
    걸려 보이는 현상을 막기 위해 백그라운드 데몬 스레드로 전송한다.
    """
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not bot_token or not chat_id:
        return
    if _is_reserved_admin_notify_target(target_user):
        print(f"[AdminNotify] reserved test target suppressed action={action} user_id={target_user.id}")
        return

    # 요청 컨텍스트 안에서 admin email 미리 스냅샷 (스레드에선 request 접근 불가)
    admin = _admin_user()
    admin_label = admin.email if admin else 'system'
    msg = (
        f"👑 <b>관리자 액션: {action}</b>\n\n"
        f"👤 대상: {target_user.name} ({target_user.email})\n"
        f"🆔 user_id={target_user.id}\n"
        f"🛠 by {admin_label}"
    )
    if detail:
        msg += f"\n\n{detail}"

    if _admin_notify_recently_sent(msg):
        print(f"[AdminNotify] duplicate suppressed action={action} user_id={target_user.id}")
        return

    def _send():
        try:
            import requests as _rq
            _rq.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=5,
            )
        except Exception as e:
            print(f"[AdminNotify] {type(e).__name__}: {e}")

    threading.Thread(target=_send, daemon=True).start()


def _notify_member(user: User | None, text: str) -> bool:
    """회원 본인 텔레그램 알림 (best-effort, 요청 흐름을 절대 깨지 않는다).

    텔레그램 미연결 회원이면 no-op. 운영에선 백그라운드 스레드로 보내 승인 버튼이
    텔레그램 지연에 묶이지 않게 하고, TESTING 앱에서는 동기 호출(테스트 검증용).
    실패는 로그만 — 감사로그(AdminAuditLog) 에 남기지 않는다.
    """
    if user is None:
        return False
    try:
        background = not bool(current_app.config.get('TESTING'))
        return member_telegram.notify_member(user, text, background=background)
    except Exception as e:  # noqa: BLE001
        print(f"[MemberNotify] {type(e).__name__}: {e}")
        return False


def _is_reserved_admin_notify_target(target_user: User | None) -> bool:
    email = (getattr(target_user, 'email', '') or '').strip().lower()
    if not email:
        return False
    return email == 'expired@example.com' or email.startswith('audit_') or email.endswith('@example.com')


def _admin_notify_dedupe_path() -> Path:
    root = Path(os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    return root / 'data' / 'admin_notify_dedupe.json'


def _admin_notify_recently_sent(message: str, now: float | None = None) -> bool:
    """Return True when an identical admin Telegram message was sent recently."""
    if _ADMIN_NOTIFY_DEDUPE_TTL_SECONDS <= 0:
        return False

    now = time.time() if now is None else float(now)
    key = hashlib.sha256(message.encode('utf-8')).hexdigest()
    path = _admin_notify_dedupe_path()

    with _ADMIN_NOTIFY_DEDUPE_LOCK:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding='utf-8'))
            else:
                data = {}
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}

        cutoff = now - _ADMIN_NOTIFY_DEDUPE_TTL_SECONDS
        cleaned = {
            str(k): float(v)
            for k, v in data.items()
            if isinstance(v, (int, float)) and float(v) >= cutoff
        }

        if key in cleaned:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as e:
                print(f"[AdminNotify] dedupe prune failed: {type(e).__name__}: {e}")
            return True

        cleaned[key] = now
        if len(cleaned) > _ADMIN_NOTIFY_DEDUPE_MAX_KEYS:
            cleaned = dict(sorted(cleaned.items(), key=lambda item: item[1])[-_ADMIN_NOTIFY_DEDUPE_MAX_KEYS:])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + '.tmp')
            tmp.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(tmp, path)
        except Exception as e:
            print(f"[AdminNotify] dedupe write failed: {type(e).__name__}: {e}")
        return False


def create_admin_notification(noti_type: str, title: str, message: str, related_id: int | None = None):
    """관리자 인앱 알림 생성 (best-effort — 실패해도 호출자에 영향 X)"""
    try:
        noti = AdminNotification(
            type=noti_type,
            title=title,
            message=message,
            related_id=related_id,
        )
        db.session.add(noti)
        db.session.commit()
    except Exception as e:
        print(f"[AdminNotification] failed: {type(e).__name__}: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# 대시보드 통계
# ─────────────────────────────────────────────────────────────────────────────

def _has_active_same_tier(user: User | None, tier: str | None) -> bool:
    """Return True when a duplicate renewal approval would not change access."""
    if not user or user.status != 'approved' or user.tier != tier:
        return False
    if tier == 'premium':
        return True
    if tier != 'pro' or user.pro_expires_at is None:
        return False
    expires = user.pro_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc)


def _pro_expiry_needs_refresh(user: User) -> bool:
    """'pro' 부여 시 만료일을 새로 잡아야 하는지.

    만료일이 없거나 이미 지난 경우 True. AI Brain pause 중(pro_paused_at 세팅)이면
    저장된 날짜가 과거여도 pause 해제 시 보정되므로 건드리지 않는다.
    """
    if user.pro_paused_at is not None:
        return False
    if user.pro_expires_at is None:
        return True
    expires = user.pro_expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def _extend_aibain_expiry(user: User, days: int = 30) -> None:
    """Enable AI Brain and extend from the later of now or current expiry."""
    user.aibain_enabled = True
    base = datetime.now(timezone.utc)
    if user.aibain_expires_at:
        existing = user.aibain_expires_at
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        if existing > base:
            base = existing
    user.aibain_expires_at = base + timedelta(days=days)
    user.aibain_alert_stage = None


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """관리자 대시보드 통계"""
    users = User.query.all()
    pending_subs = SubscriptionRequest.query.filter_by(status='pending').count()
    # AI Brain 애드온 전용 pending 카운트 (sub_req.request_type 기반)
    pending_aibain_subs = SubscriptionRequest.query.filter(
        SubscriptionRequest.status == 'pending',
        SubscriptionRequest.request_type.in_(('aibain_addon', 'aibain_renewal')),
    ).count()

    # AI Brain 활성 유저 + 만료 임박 (D-3 이내)
    from datetime import datetime, timezone, timedelta
    now_naive = datetime.utcnow()
    soon_threshold = now_naive + timedelta(days=3)
    aibain_active_count = 0
    aibain_expiring_count = 0
    for u in users:
        if not u.aibain_enabled:
            continue
        if u.aibain_expires_at is None:
            # NULL 만료 = 무기한 활성
            aibain_active_count += 1
            continue
        expires = u.aibain_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        if expires > now_naive:
            aibain_active_count += 1
            if expires <= soon_threshold:
                aibain_expiring_count += 1

    # 대시보드 "오늘 처리할 일" 카운트
    # 1) 가입만 하고 구독 신청 없이 이탈한 pending 유저 (관리자 사각지대 제로 원칙)
    pending_req_user_ids = {
        r.user_id
        for r in SubscriptionRequest.query.filter_by(status='pending').all()
    }
    pending_signup_count = sum(
        1 for u in users
        if u.status == 'pending' and u.id not in pending_req_user_ids
    )
    # 2) Pro 베이스 만료 임박 (D-3 이내, AI Brain pause 중 제외)
    pro_expiring_count = 0
    for u in users:
        if u.tier != 'pro' or u.pro_expires_at is None or u.pro_paused_at is not None:
            continue
        expires = u.pro_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        if now_naive < expires <= soon_threshold:
            pro_expiring_count += 1

    # 이탈(churn) 지표 — 만료는 '재구독 유도' 상태이므로 상시 추적한다.
    expired_users_count = sum(1 for u in users if u.status == 'expired')
    month_start = now_naive.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resubscribed_this_month = 0
    for r in SubscriptionRequest.query.filter_by(status='approved').all():
        if r.request_type not in ('renewal', 'upgrade'):
            continue
        processed = r.processed_at
        if processed is None:
            continue
        if processed.tzinfo is not None:
            processed = processed.astimezone(timezone.utc).replace(tzinfo=None)
        if processed >= month_start and r.from_tier in ('pro', 'premium'):
            resubscribed_this_month += 1

    return jsonify({
        'total_users': len(users),
        'pro_users': sum(1 for u in users if u.tier == 'pro'),
        'premium_users': sum(1 for u in users if u.tier == 'premium'),
        'no_tier_users': sum(1 for u in users if not u.tier),
        'admin_users': sum(1 for u in users if u.role == 'admin'),
        'pending_users': sum(1 for u in users if u.status == 'pending'),
        'approved_users': sum(1 for u in users if u.status == 'approved'),
        'suspended_users': sum(1 for u in users if u.status == 'suspended'),
        'expired_users': expired_users_count,      # 만료 · 재구독 대기
        'churn': {
            'expiring_d3': pro_expiring_count,             # 만료 임박 (D-3 이내)
            'expired_unrenewed': expired_users_count,      # 만료 후 미재구독
            'resubscribed_this_month': resubscribed_this_month,
        },
        'pending_subscriptions': pending_subs,
        'pending_signups': pending_signup_count,   # 가입만 완료 · 플랜 미선택
        'pro_expiring_soon': pro_expiring_count,   # Pro D-3 이내 만료
        # AI Brain 알파 스캐너 (애드온)
        'aibain_active_users': aibain_active_count,
        'aibain_expiring_soon': aibain_expiring_count,  # D-3 이내 만료
        'pending_aibain_subs': pending_aibain_subs,
    })


# ─────────────────────────────────────────────────────────────────────────────
# 회원 목록 (필터 + 페이지네이션, backward-compatible)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@admin_required
def list_users():
    """전체 유저 목록 조회 + 필터 + 페이지네이션

    Query params (모두 선택):
        status: pending|approved|rejected|suspended
        tier:   pro|premium|none|aibain|aibain_expired
        q:      회원 ID(정확히) 또는 이름/이메일 부분일치
        page:   1부터 (없으면 페이지네이션 없이 전체 반환 — 기존 동작)
        per_page: 50 기본
    응답: { users: [...], total, page?, per_page?, total_pages? }
    """
    q = User.query

    status = (request.args.get('status') or '').strip().lower()
    if status in ('pending', 'approved', 'rejected', 'suspended', 'expired'):
        q = q.filter(User.status == status)

    tier = (request.args.get('tier') or '').strip().lower()
    now_naive = datetime.utcnow()
    if tier == 'none':
        q = q.filter(User.tier.is_(None))
    elif tier in ('pro', 'premium'):
        q = q.filter(User.tier == tier)
    elif tier == 'aibain':
        q = q.filter(
            User.aibain_enabled.is_(True),
            or_(User.aibain_expires_at.is_(None), User.aibain_expires_at > now_naive),
        )
    elif tier == 'aibain_expired':
        q = q.filter(
            User.aibain_expires_at.isnot(None),
            or_(User.aibain_enabled.is_(False), User.aibain_expires_at <= now_naive),
        )

    search = (request.args.get('q') or '').strip()[:100]
    if search:
        # %/_ 를 검색 와일드카드로 해석하지 않고 사용자가 입력한 문자 그대로 찾는다.
        escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        like = f'%{escaped}%'
        conditions = [
            User.email.ilike(like, escape='\\'),
            User.name.ilike(like, escape='\\'),
        ]
        if search.isdigit():
            conditions.append(User.id == int(search))
        q = q.filter(or_(*conditions))

    q = q.order_by(User.created_at.desc())

    page_arg = request.args.get('page')
    if page_arg is None:
        # backward-compatible: 페이지 미지정 시 전체 반환 (기존 프론트 호환)
        users = q.all()
        return jsonify({'users': [u.to_dict() for u in users], 'total': len(users)})

    try:
        page = max(1, int(page_arg))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = max(1, min(200, int(request.args.get('per_page') or 50)))
    except (TypeError, ValueError):
        per_page = 50

    total = q.count()
    users = q.limit(per_page).offset((page - 1) * per_page).all()
    return jsonify({
        'users': [u.to_dict() for u in users],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page,
    })


@admin_bp.route('/users/<int:user_id>')
@admin_required
def get_user(user_id):
    """유저 상세 조회 + 감사 로그 + 구독 이력"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = user.to_dict()

    # 최근 감사 로그 (해당 유저 관련)
    logs = AdminAuditLog.query.filter_by(target_user_id=user_id) \
        .order_by(AdminAuditLog.created_at.desc()).limit(20).all()
    data['audit_logs'] = [l.to_dict() for l in logs]

    # 구독 요청 이력
    sub_reqs = SubscriptionRequest.query.filter_by(user_id=user_id) \
        .order_by(SubscriptionRequest.created_at.desc()).limit(10).all()
    data['subscription_history'] = [s.to_dict() for s in sub_reqs]

    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
# 단건 mutation
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def set_role(user_id):
    """유저 역할 변경 (user ↔ admin)"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    role = (data.get('role') or '').strip().lower()
    if role not in ('user', 'admin'):
        return jsonify({'error': 'Role must be user or admin'}), 400
    actor = _admin_user()
    if actor and actor.id == user.id and role != 'admin':
        return jsonify({'error': 'Cannot demote your own admin account'}), 400
    if user.is_admin and role != 'admin' and User.query.filter_by(role='admin').count() <= 1:
        return jsonify({'error': 'Cannot demote the last admin account'}), 409

    before = {'role': user.role}
    user.role = role
    db.session.commit()
    _record_audit('set_role', user, before, {'role': role})
    _notify_admin('역할 변경', user, f"{before['role']} → {role}")

    return jsonify({
        'message': f"{user.email}: {before['role']} → {role}",
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/tier', methods=['PUT'])
@admin_required
def set_tier(user_id):
    """유저 구독 tier 변경 (pro ↔ premium) — tier 부여 시 status 자동 승인"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    tier = (data.get('tier') or '').strip().lower()
    if tier not in ('pro', 'premium'):
        return jsonify({'error': 'Tier must be pro or premium'}), 400

    before = {
        'tier': user.tier,
        'status': user.status,
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
    }
    user.tier = tier
    if user.status != 'approved':
        user.status = 'approved'
        admin = _admin_user()
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin.id if admin else None
    if tier == 'pro' and _pro_expiry_needs_refresh(user):
        user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    elif tier == 'premium':
        user.pro_expires_at = None
        # Ultra Pro는 무기한 베이스 이용권이므로 Pro 카운터 정지 marker를 보존하지 않는다.
        user.pro_paused_at = None
    # tier 변경 → 만료 알림 stage 리셋 (재발송 가능)
    user.pro_expiry_alert_stage = None
    db.session.commit()

    after = {
        'tier': user.tier,
        'status': user.status,
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
    }
    _record_audit('set_tier', user, before, after)
    _notify_admin('구독 등급 변경', user, f"{before['tier'] or 'none'} → {tier}")
    record_funnel_event(EVENT_TIER_GRANT, user.id, {
        'from_tier': before['tier'], 'to_tier': tier, 'was_status': before['status'],
    })
    # 회원 본인 알림 — tier 직접 부여도 사실상 '승인'이다
    _notify_member(user, member_telegram.build_approval_message(
        user, summary=f"{before['tier'] or 'none'} → {tier} (관리자 직접 부여)",
    ))

    return jsonify({
        'message': f"{user.email}: {before['tier'] or 'none'} → {tier}",
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def set_status(user_id):
    """유저 계정 상태 변경"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    status = (data.get('status') or '').strip().lower()
    if status not in ('pending', 'approved', 'rejected', 'suspended', 'expired'):
        return jsonify({'error': 'Status must be pending, approved, rejected, suspended, or expired'}), 400
    actor = _admin_user()
    if actor and actor.id == user.id and status in {'rejected', 'suspended'}:
        return jsonify({'error': 'Cannot block your own admin account'}), 400

    before = {'status': user.status}
    user.status = status
    if status == 'approved':
        admin = _admin_user()
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin.id if admin else None
    db.session.commit()

    _record_audit('set_status', user, before, {'status': status})
    _notify_admin('계정 상태 변경', user, f"{before['status']} → {status}")

    return jsonify({
        'message': f"{user.email}: {before['status']} → {status}",
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/extend', methods=['POST'])
@admin_required
def extend_pro(user_id):
    """Pro 만료일 N일 연장 (기본 30일)"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    try:
        days = int(request.args.get('days') or (request.get_json() or {}).get('days') or 30)
    except (TypeError, ValueError):
        days = 30
    if days <= 0 or days > 3650:
        return jsonify({'error': 'days must be between 1 and 3650'}), 400

    before = {
        'tier': user.tier,
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
    }
    base = user.pro_expires_at
    if base is None or (base.tzinfo is None and base < datetime.utcnow()) or \
       (base.tzinfo is not None and base < datetime.now(timezone.utc)):
        base = datetime.now(timezone.utc)
    elif base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    user.pro_expires_at = base + timedelta(days=days)
    if user.tier not in ('pro', 'premium'):
        user.tier = 'pro'
    if user.status != 'approved':
        user.status = 'approved'
        admin = _admin_user()
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin.id if admin else None
    user.pro_expiry_alert_stage = None  # 알림 재발송 가능
    db.session.commit()

    after = {'tier': user.tier, 'pro_expires_at': user.pro_expires_at.isoformat()}
    _record_audit('extend_pro', user, before, after, note=f'+{days}d')
    _notify_admin('Pro 만료 연장', user, f"+{days}일 → {user.pro_expires_at.isoformat()}")

    return jsonify({'message': f'{user.email} +{days}일', 'user': user.to_dict()})


@admin_bp.route('/users/<int:user_id>/expiry', methods=['PUT'])
@admin_required
def set_expiry(user_id):
    """Pro 만료일 직접 지정 (ISO datetime)"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    expires_raw = (data.get('pro_expires_at') or '').strip()
    if not expires_raw:
        return jsonify({'error': 'pro_expires_at required (ISO format)'}), 400
    try:
        # 'YYYY-MM-DD' 또는 ISO datetime 둘 다 허용
        if 'T' not in expires_raw:
            expires = datetime.fromisoformat(expires_raw).replace(tzinfo=timezone.utc)
        else:
            expires = datetime.fromisoformat(expires_raw.replace('Z', '+00:00'))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD or ISO 8601'}), 400

    # 과거 날짜 설정 방지
    if expires < datetime.now(timezone.utc):
        return jsonify({'error': '과거 날짜는 설정할 수 없습니다'}), 400

    before = {'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None}
    user.pro_expires_at = expires
    user.pro_expiry_alert_stage = None
    db.session.commit()

    _record_audit('set_expiry', user, before, {'pro_expires_at': expires.isoformat()})
    _notify_admin('만료일 변경', user, f"→ {expires.isoformat()}")

    return jsonify({'message': f'{user.email} 만료일 변경', 'user': user.to_dict()})


@admin_bp.route('/users/<int:user_id>/revoke', methods=['POST'])
@admin_required
def revoke_subscription(user_id):
    """Pro 구독 즉시 만료 처리.

    자동 만료 메커니즘이 실패했거나 관리자가 중도 해제(환불/정책 위반 등)
    할 필요가 있을 때 사용. pro_expires_at 을 1분 전으로 세팅해서
    ApprovedGuard 의 is_pro_expired=true 분기가 발동되도록 한다.

    - tier 는 유지 (구독 이력은 남김)
    - status 유지 (로그인은 계속 가능 — 환불/재구독 협의 여지)
    - pro_expiry_alert_stage='expired' 로 세팅 (중복 알림 방지)
    - premium 유저는 무기한이라 revoke 대상 아님 (400)
    - 이미 만료된 유저도 idempotent (같은 효과)
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Ultra Pro 는 무기한 — revoke 대상이 아님
    if user.tier == 'premium':
        return jsonify({'error': 'Ultra Pro 는 무기한이라 만료 처리 불가. tier 변경을 사용하세요.'}), 400
    if user.tier != 'pro':
        return jsonify({'error': f'Pro 유저가 아닙니다 (tier={user.tier})'}), 400

    data = request.get_json() or {}
    note = (data.get('note') or '').strip() or 'admin manual revoke'

    before = {
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
        'pro_expiry_alert_stage': user.pro_expiry_alert_stage,
        'pro_paused_at': user.pro_paused_at.isoformat() if user.pro_paused_at else None,
    }

    # 1분 전으로 세팅해서 즉시 만료 상태로 만듦
    user.pro_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    user.pro_expiry_alert_stage = 'expired'   # 중복 알림 방지
    # AI Brain pause marker 가 남아 있으면 is_pro_expired 가 영원히 False 라
    # revoke 가 무효화된다 — 즉시 만료 의도이므로 pause 도 함께 해제한다.
    user.pro_paused_at = None
    db.session.commit()

    after = {
        'pro_expires_at': user.pro_expires_at.isoformat(),
        'pro_expiry_alert_stage': user.pro_expiry_alert_stage,
    }
    _record_audit('revoke_subscription', user, before, after, note=note)
    _notify_admin('구독 즉시 만료 처리', user, f"사유: {note}")

    return jsonify({
        'message': f'{user.email} 구독 즉시 만료 처리됨',
        'user': user.to_dict(),
    })


# ── AI Brain 알파 스캐너 애드온 (별도 30일 갱신 구독) ────────────────────────

@admin_bp.route('/users/<int:user_id>/aibain/enable', methods=['POST'])
@admin_required
def enable_aibain(user_id):
    """AI Brain 알파 스캐너 활성화 (+30일 연장 가능).

    payload:
      - days: int (default 30) — 추가 일수. 0 = 무기한 (NULL 만료일).

    동작:
      - aibain_enabled=True
      - aibain_expires_at = now + days (또는 NULL 시 무기한)
      - 이미 활성이면 expires_at 에 days 추가 (연장)
      - aibain_alert_stage 리셋 (만료 알림 재발송 가능하게)
    """
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    # AI Brain 은 활성 베이스 (Pro/Premium) 회원에게만 의미 있음
    if user.tier not in ('pro', 'premium'):
        return jsonify({'error': f'AI Brain 은 Pro/Ultra Pro 회원에게만 부여 가능 (tier={user.tier})'}), 400
    # 만료된 Pro 베이스에 AI Brain 을 활성화하면 pause marker 가 Pro 만료 판정을
    # 우회해 베이스 구독까지 공짜로 부활한다 — 베이스 갱신(extend)부터 처리해야 한다.
    if user.tier == 'pro' and _pro_expiry_needs_refresh(user) and user.pro_expires_at is not None:
        return jsonify({
            'error': '베이스 Pro 가 만료된 회원입니다. Pro 연장(extend)을 먼저 처리한 뒤 AI Brain 을 활성화하세요.'
        }), 400

    data = request.get_json() or {}
    try:
        days = int(data.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    note = (data.get('note') or '').strip() or None

    before = {
        'aibain_enabled': user.aibain_enabled,
        'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
        'pro_paused_at': user.pro_paused_at.isoformat() if user.pro_paused_at else None,
    }

    user.aibain_enabled = True
    if days <= 0:
        # 0 = 무기한
        user.aibain_expires_at = None
    else:
        base = datetime.now(timezone.utc)
        # 이미 활성 + 만료일 미래 → 연장
        if user.aibain_expires_at:
            existing = user.aibain_expires_at
            if existing.tzinfo is None:
                existing = existing.replace(tzinfo=timezone.utc)
            if existing > base:
                base = existing
        user.aibain_expires_at = base + timedelta(days=days)
    user.aibain_alert_stage = None
    # Pro 일시정지 트리거 (활성 Pro 회원이 처음 AI Brain 활성화될 때만)
    if user.tier == 'pro' and user.pro_expires_at is not None and user.pro_paused_at is None:
        user.pro_paused_at = datetime.now(timezone.utc)
        user.pro_expiry_alert_stage = None
    db.session.commit()

    after = {
        'aibain_enabled': user.aibain_enabled,
        'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
        'pro_paused_at': user.pro_paused_at.isoformat() if user.pro_paused_at else None,
    }
    _record_audit('enable_aibain', user, before, after, note=note)
    _notify_admin('AI Brain 활성화', user,
                  f"{days}일 (만료: {after['aibain_expires_at'] or '무기한'})")

    return jsonify({
        'message': f'{user.email} AI Brain 활성화 ({days}일)',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/aibain/revoke', methods=['POST'])
@admin_required
def revoke_aibain(user_id):
    """AI Brain 알파 스캐너 즉시 해제. 베이스 tier 는 유지."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    note = (data.get('note') or '').strip() or 'admin manual aibain revoke'

    before = {
        'aibain_enabled': user.aibain_enabled,
        'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
        'pro_paused_at': user.pro_paused_at.isoformat() if user.pro_paused_at else None,
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
    }

    user.aibain_enabled = False
    now_utc = datetime.now(timezone.utc)
    user.aibain_expires_at = now_utc - timedelta(minutes=1)
    user.aibain_alert_stage = 'expired'

    # Pro 일시정지 재개 — paused 기간만큼 pro_expires_at 연장 후 NULL 처리
    if user.pro_paused_at is not None and user.tier == 'pro' and user.pro_expires_at is not None:
        paused_at = user.pro_paused_at
        if paused_at.tzinfo is None:
            paused_at = paused_at.replace(tzinfo=timezone.utc)
        elapsed = now_utc - paused_at
        if elapsed.total_seconds() > 0:
            pro_expires = user.pro_expires_at
            if pro_expires.tzinfo is None:
                pro_expires = pro_expires.replace(tzinfo=timezone.utc)
            user.pro_expires_at = pro_expires + elapsed
        user.pro_paused_at = None
        user.pro_expiry_alert_stage = None
    db.session.commit()

    after = {
        'aibain_enabled': user.aibain_enabled,
        'aibain_expires_at': user.aibain_expires_at.isoformat(),
        'pro_paused_at': user.pro_paused_at.isoformat() if user.pro_paused_at else None,
        'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
    }
    _record_audit('revoke_aibain', user, before, after, note=note)
    _notify_admin('AI Brain 해제', user, f"사유: {note}")

    return jsonify({
        'message': f'{user.email} AI Brain 즉시 해제',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/aibain/extend', methods=['POST'])
@admin_required
def extend_aibain(user_id):
    """AI Brain 만료일 연장 (+N일). enable 의 alias — 활성 상태에서만 작동."""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if not user.aibain_enabled:
        return jsonify({'error': 'AI Brain 이 활성화되지 않았습니다. enable 사용.'}), 400

    data = request.get_json() or {}
    try:
        days = int(data.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    note = (data.get('note') or '').strip() or None

    before = {
        'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
    }

    base = datetime.now(timezone.utc)
    if user.aibain_expires_at:
        existing = user.aibain_expires_at
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        if existing > base:
            base = existing
    user.aibain_expires_at = base + timedelta(days=days)
    user.aibain_alert_stage = None
    db.session.commit()

    after = {'aibain_expires_at': user.aibain_expires_at.isoformat()}
    _record_audit('extend_aibain', user, before, after, note=note)
    _notify_admin('AI Brain 연장', user, f"+{days}일 → 만료: {after['aibain_expires_at']}")

    return jsonify({
        'message': f'{user.email} AI Brain +{days}일',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['PUT'])
@admin_required
def reset_password(user_id):
    """유저 비밀번호 리셋"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    new_password = data.get('password', '').strip()
    note = (data.get('note') or '').strip() or 'admin reset'

    if not new_password:
        return jsonify({'error': '새 비밀번호를 입력하세요'}), 400
    # 동일 비밀번호 정책 적용
    from app.routes.auth import _validate_password
    pw_ok, pw_err = _validate_password(new_password)
    if not pw_ok:
        return jsonify({'error': pw_err}), 400

    user.set_password(new_password)
    db.session.commit()

    _record_audit('reset_password', user, None, None, note=note)
    _notify_admin('비밀번호 리셋', user, f"사유: {note}")

    return jsonify({
        'message': f'{user.email} 비밀번호 리셋 완료',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """유저 삭제 — 커뮤니티 게시글/댓글/구매요청까지 연쇄 제거."""
    from app.models.community import Post, PostImage, Comment, PurchaseRequest

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    admin = _admin_user()
    if admin and admin.id == user_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400

    email = user.email
    snapshot = user.to_dict()

    try:
        user_post_ids = [p.id for p in Post.query.filter_by(author_id=user_id).all()]
        if user_post_ids:
            PostImage.query.filter(PostImage.post_id.in_(user_post_ids)).delete(synchronize_session=False)
            Comment.query.filter(Comment.post_id.in_(user_post_ids)).delete(synchronize_session=False)
            PurchaseRequest.query.filter(PurchaseRequest.post_id.in_(user_post_ids)).delete(synchronize_session=False)

        Comment.query.filter_by(author_id=user_id).delete(synchronize_session=False)
        PurchaseRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        if user_post_ids:
            Post.query.filter(Post.id.in_(user_post_ids)).delete(synchronize_session=False)

        SubscriptionRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        db.session.delete(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete user: {e}'}), 500

    # 감사 로그 (user 객체는 삭제됨 → snapshot 사용)
    try:
        log = AdminAuditLog(
            admin_id=admin.id if admin else None,
            admin_email=admin.email if admin else None,
            action='delete_user',
            target_user_id=user_id,
            target_email=email,
            before=json.dumps(snapshot, default=str),
            after=None,
            note='hard delete with cascade',
        )
        db.session.add(log)
        db.session.commit()
    except Exception as e:
        print(f"[AuditLog] delete_user log failed: {e}")

    return jsonify({'message': f'User {email} deleted'})


# ─────────────────────────────────────────────────────────────────────────────
# 중복 계정 탐지
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/users/duplicates', methods=['GET'])
@admin_required
def detect_duplicates():
    """같은 이름 또는 유사 이메일로 중복 가입 의심 계정 그룹 반환."""
    users = User.query.order_by(User.name, User.created_at).all()

    # 1) 이름 기준 그룹핑
    from collections import defaultdict
    name_groups = defaultdict(list)
    for u in users:
        key = (u.name or '').strip().lower()
        if key:
            name_groups[key].append(u)

    # 2) 이메일 prefix 기준 그룹핑 (@ 앞 부분, 숫자 제거 후 3자 이상 일치)
    import re as _re
    prefix_groups = defaultdict(list)
    for u in users:
        prefix = (u.email or '').split('@')[0]
        normalized = _re.sub(r'\d+', '', prefix).lower()
        if len(normalized) >= 3:
            prefix_groups[normalized].append(u)

    # 3) 2명 이상인 그룹만 반환 (중복 제거: 이름그룹+prefix그룹 병합)
    seen_sets = set()
    result = []

    def _user_dict(u):
        return {
            'id': u.id, 'email': u.email, 'name': u.name,
            'tier': u.tier, 'status': u.status,
            'created_at': u.created_at.isoformat() if u.created_at else None,
            'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
        }

    for name_key, group in name_groups.items():
        if len(group) < 2:
            continue
        ids = tuple(sorted(u.id for u in group))
        if ids in seen_sets:
            continue
        seen_sets.add(ids)
        result.append({
            'reason': 'same_name',
            'key': group[0].name,
            'accounts': [_user_dict(u) for u in group],
        })

    for prefix_key, group in prefix_groups.items():
        if len(group) < 2:
            continue
        ids = tuple(sorted(u.id for u in group))
        if ids in seen_sets:
            continue
        seen_sets.add(ids)
        result.append({
            'reason': 'similar_email',
            'key': prefix_key,
            'accounts': [_user_dict(u) for u in group],
        })

    return jsonify({'groups': result, 'total_groups': len(result)})


# ─────────────────────────────────────────────────────────────────────────────
# 일괄 처리
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/users/bulk-tier', methods=['POST'])
@admin_required
def bulk_tier():
    """일괄 tier 부여
    Body: { user_ids: [int], tier: 'pro'|'premium' }
    """
    data = request.get_json() or {}
    user_ids = data.get('user_ids') or []
    tier = (data.get('tier') or '').strip().lower()
    if not isinstance(user_ids, list) or not user_ids:
        return jsonify({'error': 'user_ids required'}), 400
    if tier not in ('pro', 'premium'):
        return jsonify({'error': 'tier must be pro or premium'}), 400

    admin = _admin_user()
    updated = []
    for uid in user_ids:
        try:
            user = db.session.get(User, int(uid))
        except (TypeError, ValueError):
            continue
        if not user:
            continue
        before = {'tier': user.tier, 'status': user.status}
        user.tier = tier
        if user.status != 'approved':
            user.status = 'approved'
            user.approved_at = datetime.now(timezone.utc)
            user.approved_by = admin.id if admin else None
        if tier == 'pro' and _pro_expiry_needs_refresh(user):
            user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        elif tier == 'premium':
            user.pro_expires_at = None
        user.pro_expiry_alert_stage = None
        updated.append((user, before))

    db.session.commit()

    for user, before in updated:
        _record_audit('bulk_tier', user, before, {'tier': tier}, note='bulk')
    if updated:
        _notify_admin('일괄 등급 부여', updated[0][0], f"{len(updated)}명 → {tier}")

    return jsonify({'message': f'{len(updated)}명 처리 완료', 'count': len(updated)})


@admin_bp.route('/users/bulk-approve', methods=['POST'])
@admin_required
def bulk_approve():
    """일괄 승인 (status=approved). tier 부여는 별도."""
    data = request.get_json() or {}
    user_ids = data.get('user_ids') or []
    if not isinstance(user_ids, list) or not user_ids:
        return jsonify({'error': 'user_ids required'}), 400

    admin = _admin_user()
    updated = []
    for uid in user_ids:
        try:
            user = db.session.get(User, int(uid))
        except (TypeError, ValueError):
            continue
        if not user or user.status == 'approved':
            continue
        before = {'status': user.status}
        user.status = 'approved'
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin.id if admin else None
        updated.append((user, before))
    db.session.commit()

    for user, before in updated:
        _record_audit('bulk_approve', user, before, {'status': 'approved'}, note='bulk')
    if updated:
        _notify_admin('일괄 승인', updated[0][0], f"{len(updated)}명 approved")

    return jsonify({'message': f'{len(updated)}명 승인 완료', 'count': len(updated)})


# ─────────────────────────────────────────────────────────────────────────────
# 구독 요청
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/subscriptions')
@admin_required
def list_subscriptions():
    """구독 요청 목록 + 플랜 미선택 pending 가입자.

    관리자 사각지대 제거 — 가입만 하고 /payment-request 단계에서 이탈한 유저도
    목록에 함께 노출해 팔로업(카톡 안내 등) 가능하게 한다.
    """
    reqs = SubscriptionRequest.query.order_by(
        SubscriptionRequest.created_at.desc()
    ).all()
    pending_req_user_ids = {r.user_id for r in reqs if r.status == 'pending'}
    signup_only_q = User.query.filter(User.status == 'pending')
    if pending_req_user_ids:
        signup_only_q = signup_only_q.filter(~User.id.in_(pending_req_user_ids))
    signup_only_users = signup_only_q.order_by(User.created_at.desc()).all()

    # 만료 · 재구독 대기 — 사각지대 제로 원칙의 만료 확장. 재구독 요청을 이미
    # 제출한 유저는 requests 갈래에 있으므로 여기서 제외해 중복 노출을 막는다.
    expired_q = User.query.filter(User.status == 'expired')
    if pending_req_user_ids:
        expired_q = expired_q.filter(~User.id.in_(pending_req_user_ids))
    expired_users = expired_q.order_by(User.pro_expires_at.desc()).all()

    now_naive = datetime.utcnow()

    def _days_since_expiry(u) -> int | None:
        if u.pro_expires_at is None:
            return None
        expires = u.pro_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return max(0, (now_naive - expires).days)

    return jsonify({
        'requests': [r.to_dict() for r in reqs],
        'pending_signups': [
            {
                'id': u.id,
                'email': u.email,
                'name': u.name,
                'created_at': u.created_at.isoformat() if u.created_at else None,
                'requested_tier': u.requested_tier,
            } for u in signup_only_users
        ],
        'expired_members': [
            {
                'id': u.id,
                'email': u.email,
                'name': u.name,
                'tier': u.tier,
                'pro_expires_at': u.pro_expires_at.isoformat() if u.pro_expires_at else None,
                'days_since_expiry': _days_since_expiry(u),
                'last_login_at': u.last_login_at.isoformat() if u.last_login_at else None,
            } for u in expired_users
        ],
    })


@admin_bp.route('/subscriptions/<int:req_id>/approve', methods=['PUT'])
@admin_required
def approve_subscription(req_id):
    """구독 요청 승인.

    request_type 별로 처리 분기:
      - 'aibain_addon': 베이스 tier 유지 + AI Brain 활성화 (+30일). 활성 회원이 AI Brain 만 추가.
      - 'aibain_renewal': 만료된 AI Brain 재활성화 (+30일). 베이스 tier 유지.
      - 'early_renewal': 활성 Pro 의 만료 전 갱신 — 만료일 기준 +30일 연장 (남은 기간 보존).
      - 'upgrade' / 'downgrade': 기존 동작 — tier 변경 + 만료일 재설정 + status 승급.

    AI Brain 애드온은 베이스 구독을 건드리지 않으므로 pro_expires_at / pro_expiry_alert_stage 유지.
    """
    sub_req = db.session.get(SubscriptionRequest, req_id)
    if not sub_req:
        return jsonify({'error': 'Request not found'}), 404

    admin = _admin_user()
    processed_at = datetime.now(timezone.utc)
    claimed = SubscriptionRequest.query.filter(
        SubscriptionRequest.id == req_id,
        SubscriptionRequest.status == 'pending',
    ).update({
        SubscriptionRequest.status: 'approved',
        SubscriptionRequest.processed_at: processed_at,
        SubscriptionRequest.processed_by: admin.id if admin else None,
    }, synchronize_session=False)
    if claimed != 1:
        db.session.rollback()
        current = db.session.get(SubscriptionRequest, req_id)
        if current and current.status == 'approved':
            user = db.session.get(User, current.user_id)
            return jsonify({
                'message': 'Subscription request already approved',
                'already_processed': True,
                'request': current.to_dict(),
                'user': user.to_dict() if user else None,
            }), 200
        return jsonify({'error': f'Request already {current.status if current else "processed"}'}), 400

    db.session.expire_all()
    sub_req = db.session.get(SubscriptionRequest, req_id)
    is_aibain_addon = sub_req.request_type in ('aibain_addon', 'aibain_renewal')

    user = db.session.get(User, sub_req.user_id)
    before = None
    after = None
    audit_action = 'approve_subscription'
    summary_text = f"{sub_req.from_tier} → {sub_req.to_tier}"

    if user:
        before = {
            'tier': user.tier,
            'status': user.status,
            'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
            'aibain_enabled': user.aibain_enabled,
            'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
        }

        if sub_req.request_type == 'renewal' and _has_active_same_tier(user, sub_req.to_tier):
            db.session.commit()
            _record_audit(
                'approve_subscription_duplicate_ignored',
                user,
                before,
                before,
                note=f'request_id={req_id}: duplicate active renewal ignored',
            )
            return jsonify({
                'message': 'Subscription request already satisfied; duplicate approval ignored',
                'already_processed': True,
                'duplicate_ignored': True,
                'request': sub_req.to_dict(),
                'user': user.to_dict(),
            }), 200

        if sub_req.request_type == 'early_renewal':
            # 만료 전 갱신 — 남은 기간을 잃지 않게 '만료일 기준' +30일.
            # (now 리셋이면 D-7 에 갱신한 회원이 7일을 잃는다 — RenewalBanner 약속 위반)
            base_dt = user.pro_expires_at
            if base_dt is not None and base_dt.tzinfo is None:
                base_dt = base_dt.replace(tzinfo=timezone.utc)
            now_dt = datetime.now(timezone.utc)
            anchor = base_dt if (base_dt is not None and base_dt > now_dt) else now_dt
            user.tier = sub_req.to_tier
            user.pro_expires_at = anchor + timedelta(days=30)
            if user.status != 'approved':
                user.status = 'approved'
                user.approved_at = now_dt
                user.approved_by = admin.id if admin else None
            user.pro_expiry_alert_stage = None
            audit_action = 'early_renew_subscription'
            summary_text = f"만료 전 갱신 (+30d from expiry → {user.pro_expires_at.date().isoformat()})"
        elif is_aibain_addon:
            # AI Brain 만 활성화 — 베이스 tier 그대로
            user.aibain_enabled = True
            _extend_aibain_expiry(user, 30)
            # ── Pro 만료 카운터 일시정지 (Pro tier 회원만, premium 은 무기한이라 영향 X) ──
            # Pro 회원이 AI Brain 추가 시 AI Brain 기간 동안 Pro 카운터 freeze.
            # AI Brain 만료/해제 시 흐른 paused 기간만큼 pro_expires_at 연장 후 NULL 처리.
            if user.tier == 'pro' and user.pro_expires_at is not None and user.pro_paused_at is None:
                user.pro_paused_at = datetime.now(timezone.utc)
                user.pro_expiry_alert_stage = None  # paused 동안 알림 보류
            elif user.tier == 'premium':
                # Ultra Pro는 무기한 베이스 이용권이라 Pro pause marker가 필요 없다.
                user.pro_paused_at = None
            audit_action = 'renew_aibain' if sub_req.request_type == 'aibain_renewal' else 'activate_aibain'
            action_label = '재구독' if sub_req.request_type == 'aibain_renewal' else '활성화'
            summary_text = f"AI Brain {action_label} (+30d, base={user.tier} 유지, Pro 카운터 일시정지)"
        else:
            # 기존 동작 — 베이스 tier 변경
            user.tier = sub_req.to_tier
            if sub_req.to_tier == 'pro':
                user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            elif sub_req.to_tier == 'premium':
                user.pro_expires_at = None
                user.pro_paused_at = None
            if user.status != 'approved':
                user.status = 'approved'
                user.approved_at = datetime.now(timezone.utc)
                user.approved_by = admin.id if admin else None
            user.pro_expiry_alert_stage = None

            # 신규 가입자가 AI Brain 포함 신청한 경우 (admin_note 마커로 판단)
            if sub_req.admin_note and 'AI Brain' in sub_req.admin_note and 'aibain_addon' not in (sub_req.request_type or ''):
                _extend_aibain_expiry(user, 30)
                summary_text += " + AI Brain 활성화 (+30d)"

        after = {
            'tier': user.tier,
            'status': user.status,
            'pro_expires_at': user.pro_expires_at.isoformat() if user.pro_expires_at else None,
            'aibain_enabled': user.aibain_enabled,
            'aibain_expires_at': user.aibain_expires_at.isoformat() if user.aibain_expires_at else None,
        }

    db.session.commit()

    if user:
        _record_audit(audit_action, user, before, after)
        _notify_admin('구독 요청 승인', user, summary_text)
        record_funnel_event(EVENT_APPROVE, user.id, {
            'request_id': sub_req.id,
            'request_type': sub_req.request_type,
            'to_tier': sub_req.to_tier,
        })
        # 회원 본인 알림 (텔레그램 연결된 회원만, best-effort)
        _notify_member(user, member_telegram.build_approval_message(user, summary=summary_text))

    return jsonify({
        'message': f'Subscription approved: {summary_text}',
        'request': sub_req.to_dict(),
        'user': user.to_dict() if user else None,
    })


@admin_bp.route('/subscriptions/<int:req_id>/reject', methods=['PUT'])
@admin_required
def reject_subscription(req_id):
    """구독 요청 거부"""
    sub_req = db.session.get(SubscriptionRequest, req_id)
    if not sub_req:
        return jsonify({'error': 'Request not found'}), 404
    if sub_req.status != 'pending':
        return jsonify({'error': f'Request already {sub_req.status}'}), 400

    admin = _admin_user()
    data = request.get_json() or {}

    sub_req.status = 'rejected'
    sub_req.admin_note = data.get('note') or data.get('admin_note') or ''
    sub_req.processed_at = datetime.now(timezone.utc)
    sub_req.processed_by = admin.id if admin else None

    db.session.commit()

    user = db.session.get(User, sub_req.user_id)
    if user:
        _record_audit('reject_subscription', user, None, None, note=sub_req.admin_note or 'rejected')
        record_funnel_event(EVENT_REJECT, user.id, {
            'request_id': sub_req.id,
            'request_type': sub_req.request_type,
            'to_tier': sub_req.to_tier,
        })
        # 회원 본인 알림 (텔레그램 연결된 회원만, best-effort)
        _notify_member(user, member_telegram.build_reject_message(user, note=sub_req.admin_note or ''))

    return jsonify({
        'message': 'Subscription request rejected',
        'request': sub_req.to_dict(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# 전환 퍼널 요약 — 가입 → 구독 신청 → 승인
# ─────────────────────────────────────────────────────────────────────────────

def _to_naive_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


@admin_bp.route('/funnel/summary')
@admin_required
def funnel_summary():
    """최근 N일 퍼널 이벤트 집계 + 전환율 + 신청→승인 소요시간 중앙값.

    - counts: 이벤트별 건수
    - users: 단계별 고유 회원 수 (registered / requested / approved)
      approved 는 approve + tier_grant (관리자 직접 부여도 승인으로 본다)
    - conversion: 고유 회원 기준 비율 (0~1, 분모 0이면 null)
    - median_request_to_approve_hours: 창 안에서 승인 처리된 구독요청의
      (processed_at - created_at) 중앙값 (시간)
    """
    try:
        days = int(request.args.get('days', 30))
    except (TypeError, ValueError):
        days = 30
    days = max(1, min(days, 365))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    since_naive = _to_naive_utc(since)

    rows = FunnelEvent.query.filter(FunnelEvent.created_at >= since_naive).all()
    counts = {name: 0 for name in (
        EVENT_REGISTER, EVENT_SUBSCRIPTION_REQUEST, EVENT_APPROVE, EVENT_REJECT, EVENT_TIER_GRANT,
    )}
    registered: set[int] = set()
    requested: set[int] = set()
    approved: set[int] = set()
    for row in rows:
        counts[row.event] = counts.get(row.event, 0) + 1
        if row.user_id is None:
            continue
        if row.event == EVENT_REGISTER:
            registered.add(row.user_id)
        elif row.event == EVENT_SUBSCRIPTION_REQUEST:
            requested.add(row.user_id)
        elif row.event in (EVENT_APPROVE, EVENT_TIER_GRANT):
            approved.add(row.user_id)

    def _ratio(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    # 신청→승인 소요시간: 구독요청 원장 기준 (이벤트 meta 조인보다 정확)
    durations: list[float] = []
    for req in SubscriptionRequest.query.filter(
        SubscriptionRequest.status == 'approved',
        SubscriptionRequest.processed_at.isnot(None),
        SubscriptionRequest.processed_at >= since_naive,
    ).all():
        created = _to_naive_utc(req.created_at)
        processed = _to_naive_utc(req.processed_at)
        if created is None or processed is None or processed < created:
            continue
        durations.append((processed - created).total_seconds() / 3600)
    median_hours = _median(durations)

    return jsonify({
        'days': days,
        'since': since.isoformat(),
        'counts': counts,
        'users': {
            'registered': len(registered),
            'requested': len(requested),
            'approved': len(approved),
        },
        'conversion': {
            'register_to_request': _ratio(len(requested), len(registered)),
            'request_to_approve': _ratio(len(approved), len(requested)),
            'register_to_approve': _ratio(len(approved), len(registered)),
        },
        'median_request_to_approve_hours': round(median_hours, 2) if median_hours is not None else None,
        'approved_requests_sampled': len(durations),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Orphan File Audit — 2026-04-14 dual-tunnel 업로드 실종 재발 감지
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/community/orphan-files')
@admin_required
def list_orphan_files():
    """DB 에 file_url 기록됐으나 실제 디스크에 없는 posts 감지.

    dual-tunnel 사고(2026-04-14) 같은 업로드 라우팅 실패를 조기 발견하는 감시용.
    """
    from app.models.community import Post
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    upload_dir = os.path.join(base_dir, 'data', 'uploads', 'community')
    if not os.path.isdir(upload_dir):
        return jsonify({'orphans': [], 'total': 0, 'upload_dir': upload_dir, 'scanned': 0})
    existing = set(os.listdir(upload_dir))
    orphans = []
    posts = Post.query.filter(Post.file_url.isnot(None)).order_by(Post.id.desc()).all()
    for p in posts:
        stored = p.file_url.rsplit('/', 1)[-1] if p.file_url else None
        if stored and stored not in existing:
            orphans.append({
                'post_id': p.id,
                'title': p.title,
                'file_name': p.file_name,
                'stored_filename': stored,
                'price': p.price,
                'created_at': p.created_at.isoformat() if p.created_at else None,
                'updated_at': p.updated_at.isoformat() if p.updated_at else None,
            })
    return jsonify({'orphans': orphans, 'total': len(orphans), 'scanned': len(posts)})


# ─────────────────────────────────────────────────────────────────────────────
# 감사 로그 조회
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/audit-log')
@admin_required
def audit_log():
    """관리자 감사 로그 조회 (최근순)
    Query: limit (기본 100, 최대 500), action, target_user_id
    """
    try:
        limit = max(1, min(500, int(request.args.get('limit') or 100)))
    except (TypeError, ValueError):
        limit = 100

    q = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc())
    action = (request.args.get('action') or '').strip()
    if action:
        q = q.filter(AdminAuditLog.action == action)
    target_id = request.args.get('target_user_id')
    if target_id:
        try:
            q = q.filter(AdminAuditLog.target_user_id == int(target_id))
        except (TypeError, ValueError):
            pass

    logs = q.limit(limit).all()
    return jsonify({'logs': [l.to_dict() for l in logs], 'count': len(logs)})


# ─────────────────────────────────────────────────────────────────────────────
# 알림 (인앱)
# ─────────────────────────────────────────────────────────────────────────────

@admin_bp.route('/notifications')
@admin_required
def list_notifications():
    """관리자 알림 목록 (최근순, 페이지네이션)"""
    try:
        page = max(1, int(request.args.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    per_page = 20

    q = AdminNotification.query.order_by(AdminNotification.created_at.desc())
    total = q.count()
    notifications = q.offset((page - 1) * per_page).limit(per_page).all()

    return jsonify({
        'notifications': [n.to_dict() for n in notifications],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
    })


@admin_bp.route('/notifications/unread-count')
@admin_required
def unread_count():
    """읽지 않은 알림 수"""
    count = AdminNotification.query.filter_by(is_read=False).count()
    return jsonify({'unread_count': count})


@admin_bp.route('/notifications/<int:noti_id>/read', methods=['PUT'])
@admin_required
def mark_read(noti_id):
    """알림 읽음 처리"""
    noti = db.session.get(AdminNotification, noti_id)
    if not noti:
        return jsonify({'error': 'Not found'}), 404
    noti.is_read = True
    db.session.commit()
    return jsonify(noti.to_dict())


@admin_bp.route('/notifications/read-all', methods=['PUT'])
@admin_required
def mark_all_read():
    """모든 알림 읽음 처리"""
    AdminNotification.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': 'All notifications marked as read'})
