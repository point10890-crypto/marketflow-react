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
from datetime import datetime, timezone, timedelta
from flask import Blueprint, request, jsonify
from app.models import db
from app.models.user import User, SubscriptionRequest, AdminAuditLog, AdminNotification
from app.auth.decorators import admin_required

admin_bp = Blueprint('admin', __name__)


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

    import threading
    threading.Thread(target=_send, daemon=True).start()


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

@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """관리자 대시보드 통계"""
    users = User.query.all()
    pending_subs = SubscriptionRequest.query.filter_by(status='pending').count()
    # AI Brain 애드온 전용 pending 카운트 (sub_req.request_type 기반)
    pending_aibain_subs = SubscriptionRequest.query.filter_by(
        status='pending', request_type='aibain_addon'
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

    return jsonify({
        'total_users': len(users),
        'pro_users': sum(1 for u in users if u.tier == 'pro'),
        'premium_users': sum(1 for u in users if u.tier == 'premium'),
        'no_tier_users': sum(1 for u in users if not u.tier),
        'admin_users': sum(1 for u in users if u.role == 'admin'),
        'pending_users': sum(1 for u in users if u.status == 'pending'),
        'approved_users': sum(1 for u in users if u.status == 'approved'),
        'suspended_users': sum(1 for u in users if u.status == 'suspended'),
        'pending_subscriptions': pending_subs,
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
        tier:   pro|premium|none
        q:      이름/이메일 부분일치
        page:   1부터 (없으면 페이지네이션 없이 전체 반환 — 기존 동작)
        per_page: 50 기본
    응답: { users: [...], total, page?, per_page?, total_pages? }
    """
    q = User.query

    status = (request.args.get('status') or '').strip().lower()
    if status in ('pending', 'approved', 'rejected', 'suspended'):
        q = q.filter(User.status == status)

    tier = (request.args.get('tier') or '').strip().lower()
    if tier == 'none':
        q = q.filter(User.tier.is_(None))
    elif tier in ('pro', 'premium'):
        q = q.filter(User.tier == tier)

    search = (request.args.get('q') or '').strip()
    if search:
        like = f'%{search}%'
        q = q.filter((User.email.ilike(like)) | (User.name.ilike(like)))

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
    if tier == 'pro' and not user.pro_expires_at:
        user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    elif tier == 'premium':
        user.pro_expires_at = None
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
    if status not in ('pending', 'approved', 'rejected', 'suspended'):
        return jsonify({'error': 'Status must be pending, approved, rejected, or suspended'}), 400

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
    }

    # 1분 전으로 세팅해서 즉시 만료 상태로 만듦
    user.pro_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    user.pro_expiry_alert_stage = 'expired'   # 중복 알림 방지
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
        if tier == 'pro' and not user.pro_expires_at:
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
    })


@admin_bp.route('/subscriptions/<int:req_id>/approve', methods=['PUT'])
@admin_required
def approve_subscription(req_id):
    """구독 요청 승인.

    request_type 별로 처리 분기:
      - 'aibain_addon': 베이스 tier 유지 + AI Brain 활성화 (+30일). 활성 회원이 AI Brain 만 추가.
      - 'upgrade' / 'downgrade': 기존 동작 — tier 변경 + 만료일 재설정 + status 승급.

    AI Brain 애드온은 베이스 구독을 건드리지 않으므로 pro_expires_at / pro_expiry_alert_stage 유지.
    """
    sub_req = db.session.get(SubscriptionRequest, req_id)
    if not sub_req:
        return jsonify({'error': 'Request not found'}), 404
    if sub_req.status != 'pending':
        return jsonify({'error': f'Request already {sub_req.status}'}), 400

    admin = _admin_user()
    is_aibain_addon = sub_req.request_type == 'aibain_addon'

    sub_req.status = 'approved'
    sub_req.processed_at = datetime.now(timezone.utc)
    sub_req.processed_by = admin.id if admin else None

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

        if is_aibain_addon:
            # AI Brain 만 활성화 — 베이스 tier 그대로
            user.aibain_enabled = True
            user.aibain_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            user.aibain_alert_stage = None
            # ── Pro 만료 카운터 일시정지 (Pro tier 회원만, premium 은 무기한이라 영향 X) ──
            # Pro 회원이 AI Brain 추가 시 AI Brain 기간 동안 Pro 카운터 freeze.
            # AI Brain 만료/해제 시 흐른 paused 기간만큼 pro_expires_at 연장 후 NULL 처리.
            if user.tier == 'pro' and user.pro_expires_at is not None and user.pro_paused_at is None:
                user.pro_paused_at = datetime.now(timezone.utc)
                user.pro_expiry_alert_stage = None  # paused 동안 알림 보류
            audit_action = 'activate_aibain'
            summary_text = f"AI Brain 활성화 (+30d, base={user.tier} 유지, Pro 카운터 일시정지)"
        else:
            # 기존 동작 — 베이스 tier 변경
            user.tier = sub_req.to_tier
            if sub_req.to_tier == 'pro':
                user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
            elif sub_req.to_tier == 'premium':
                user.pro_expires_at = None
            if user.status != 'approved':
                user.status = 'approved'
                user.approved_at = datetime.now(timezone.utc)
                user.approved_by = admin.id if admin else None
            user.pro_expiry_alert_stage = None

            # 신규 가입자가 AI Brain 포함 신청한 경우 (admin_note 마커로 판단)
            if sub_req.admin_note and 'AI Brain' in sub_req.admin_note and 'aibain_addon' not in (sub_req.request_type or ''):
                user.aibain_enabled = True
                user.aibain_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
                user.aibain_alert_stage = None
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

    return jsonify({
        'message': 'Subscription request rejected',
        'request': sub_req.to_dict(),
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
