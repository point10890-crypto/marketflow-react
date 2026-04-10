"""Authentication routes — 회원가입, 로그인, 프로필, 구독 요청"""

import os
import hmac
import time
import threading
import requests as http_requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.models import db
from app.models.user import User, SubscriptionRequest
from app.auth.decorators import generate_token, login_required


# ═══════════════════════════════════════════════════════
#  Login Rate Limiter (in-memory, per IP)
# ═══════════════════════════════════════════════════════
_login_failures = {}   # {ip: [timestamp, ...]} — 실패한 시도만 기록
_login_lock = threading.Lock()
_LOGIN_MAX_FAILURES = 10
_LOGIN_WINDOW_SEC = 300  # 5 minutes


def _check_login_rate_limit(ip: str) -> bool:
    """Returns True if IP is currently blocked due to too many failures."""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SEC
    with _login_lock:
        failures = [t for t in _login_failures.get(ip, []) if t > cutoff]
        _login_failures[ip] = failures
        return len(failures) >= _LOGIN_MAX_FAILURES


def _record_login_failure(ip: str):
    """Record a failed login attempt."""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SEC
    with _login_lock:
        failures = [t for t in _login_failures.get(ip, []) if t > cutoff]
        failures.append(now)
        _login_failures[ip] = failures
        # 주기적 cleanup
        if len(_login_failures) > 200:
            expired = [k for k, v in _login_failures.items() if not v or max(v) < cutoff]
            for k in expired:
                del _login_failures[k]


def _reset_login_failures(ip: str):
    """Reset failures on successful login."""
    with _login_lock:
        _login_failures.pop(ip, None)


def _notify_admin_telegram(message: str):
    """관리자 텔레그램으로 알림 전송 (비동기, 실패는 경고 로그)."""
    import logging as _logging
    _logger = _logging.getLogger("marketflow.telegram")

    def _send():
        try:
            token = os.getenv('TELEGRAM_BOT_TOKEN')
            chat_id = os.getenv('TELEGRAM_CHAT_ID')
            if not token or not chat_id:
                _logger.info("telegram[auth] skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID unset")
                return
            resp = http_requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
                timeout=10,
            )
            if resp.status_code != 200:
                _logger.warning(
                    f"telegram[auth] HTTP {resp.status_code} body={resp.text[:200]}"
                )
        except Exception as e:
            _logger.warning(f"telegram[auth] exception: {type(e).__name__}: {e}")
    threading.Thread(target=_send, daemon=True).start()

auth_bp = Blueprint('auth', __name__)

# 관리자 비밀키 (레거시 호환) — 환경변수 필수.
# 미설정 시 admin_set_tier_legacy 라우트가 503 을 반환하도록 None 유지.
ADMIN_SECRET = os.getenv('ADMIN_SECRET') or None
if not ADMIN_SECRET:
    import logging as _al
    _al.getLogger(__name__).warning(
        "ADMIN_SECRET not set — /auth/admin/set-tier legacy route will return 503. "
        "Use /api/admin/* endpoints instead."
    )


# ═══════════════════════════════════════════════════════
#  Public Auth API
# ═══════════════════════════════════════════════════════

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()

    if not email or not password or not name:
        return jsonify({'error': 'email, password, name are required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    user = User(email=email, name=name)
    user.set_password(password)

    # 첫 번째 유저는 자동으로 admin + approved + premium (운영자)
    # 그 외 신규 가입자는 pending 상태 — 관리자가 tier(pro/premium) 부여해야
    # 앱에 접근 가능. 'free' 플랜은 더 이상 존재하지 않음.
    if User.query.count() == 0:
        user.role = 'admin'
        user.status = 'approved'
        user.tier = 'premium'
    else:
        user.status = 'pending'
        user.tier = None

    db.session.add(user)
    db.session.commit()

    # 관리자 텔레그램 알림 (신규 가입)
    _notify_admin_telegram(
        f"👤 <b>신규 회원가입</b>\n\n"
        f"📧 이메일: {user.email}\n"
        f"👤 이름: {user.name}\n"
        f"📅 가입일: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}"
    )

    # 인앱 알림
    from app.routes.admin import create_admin_notification
    create_admin_notification(
        'new_signup',
        '신규 회원가입',
        f'{user.name} ({user.email})',
        related_id=user.id,
    )

    token = generate_token(user.id)
    return jsonify({'user': user.to_dict(), 'token': token}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    # Rate limit check (Cloudflare Tunnel: real IP from Cf-Connecting-IP)
    client_ip = request.headers.get('Cf-Connecting-IP') or request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '0.0.0.0'
    if _check_login_rate_limit(client_ip):
        return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        _record_login_failure(client_ip)
        return jsonify({'error': 'Invalid email or password'}), 401

    # 로그인 성공 — 실패 카운터 리셋
    _reset_login_failures(client_ip)

    # 마지막 로그인 시간 업데이트
    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    token = generate_token(user.id)
    return jsonify({'user': user.to_dict(), 'token': token})


@auth_bp.route('/me')
@login_required
def me():
    user = request.current_user
    if user is None:
        return jsonify({'error': 'Authentication required'}), 401
    return jsonify({'user': user.to_dict()})


# ═══════════════════════════════════════════════════════
#  User Self-Service API (로그인 필수)
# ═══════════════════════════════════════════════════════

@auth_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """유저 본인 프로필 수정 (이름 변경)"""
    user = request.current_user
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if name:
        user.name = name
        db.session.commit()

    return jsonify({'user': user.to_dict()})


@auth_bp.route('/subscription/request', methods=['POST'])
@login_required
def request_subscription():
    """구독 변경 요청 (free → pro 등)"""
    user = request.current_user
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json() or {}
    to_tier = (data.get('to_tier') or '').strip().lower()

    # 'free' 플랜은 폐지 — 구독 가능한 tier는 pro / premium 뿐
    if to_tier not in ('pro', 'premium'):
        return jsonify({'error': 'Invalid tier. Use: pro, premium'}), 400

    if to_tier == user.tier:
        return jsonify({'error': f'Already on {to_tier} tier'}), 400

    # premium(Ultra Pro)은 최상위 — 다운그레이드 불가
    if user.tier == 'premium':
        return jsonify({'error': 'Ultra Pro는 최상위 플랜입니다. 다운그레이드할 수 없습니다.'}), 400

    # 이미 pending 요청이 있는지 확인
    existing = SubscriptionRequest.query.filter_by(
        user_id=user.id, status='pending'
    ).first()
    if existing:
        return jsonify({'error': 'You already have a pending subscription request'}), 409

    # tier가 없는(None) 신규 가입자나 pro 유저가 상위 tier 신청 = upgrade
    req_type = 'upgrade' if (
        user.tier is None or
        (user.tier == 'pro' and to_tier == 'premium')
    ) else 'downgrade'

    depositor_name = (data.get('depositor_name') or '').strip() or None
    amount_map = {'pro': '50,000원', 'premium': '1,200,000원'}
    amount = amount_map.get(to_tier)

    sub_request = SubscriptionRequest(
        user_id=user.id,
        request_type=req_type,
        # from_tier NOT NULL — None 유저는 'none' 문자열로 기록
        from_tier=user.tier or 'none',
        to_tier=to_tier,
        depositor_name=depositor_name,
        amount=amount,
    )
    db.session.add(sub_request)
    db.session.commit()

    # 관리자 텔레그램 + 인앱 알림
    tier_label = {'pro': 'Pro', 'premium': 'Ultra Pro'}.get(to_tier, to_tier)
    _notify_admin_telegram(
        f"💳 <b>구독 업그레이드 요청</b>\n\n"
        f"👤 {user.name} ({user.email})\n"
        f"📋 {user.tier or 'none'} → {to_tier}\n"
        f"💰 {amount or '-'}"
    )
    from app.routes.admin import create_admin_notification
    create_admin_notification(
        'subscription_request',
        f'구독 요청: {tier_label}',
        f'{user.name} ({user.email}) — {user.tier or "none"} → {to_tier}',
        related_id=sub_request.id,
    )

    return jsonify({'request': sub_request.to_dict()}), 201


@auth_bp.route('/subscription/status')
@login_required
def subscription_status():
    """본인의 구독 요청 현황 조회"""
    user = request.current_user
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    requests_list = SubscriptionRequest.query.filter_by(
        user_id=user.id
    ).order_by(SubscriptionRequest.created_at.desc()).limit(10).all()

    return jsonify({
        'user': user.to_dict(),
        'requests': [r.to_dict() for r in requests_list],
    })


# ═══════════════════════════════════════════════════════
#  레거시 호환 API (X-Admin-Secret 헤더)
# ═══════════════════════════════════════════════════════

@auth_bp.route('/admin/set-tier', methods=['POST'])
def admin_set_tier_legacy():
    """유저 tier 변경 (레거시 — X-Admin-Secret 헤더)"""
    if not ADMIN_SECRET:
        return jsonify({'error': 'Admin legacy endpoint disabled (ADMIN_SECRET not configured)'}), 503
    secret = request.headers.get('X-Admin-Secret', '')
    if not hmac.compare_digest(secret, ADMIN_SECRET):
        return jsonify({'error': 'Admin access denied'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    tier = (data.get('tier') or '').strip().lower()

    if not email or tier not in ('pro', 'premium'):
        return jsonify({'error': 'email and tier (pro/premium) are required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': f'User not found: {email}'}), 404

    old_tier = user.tier
    user.tier = tier
    db.session.commit()

    return jsonify({
        'message': f'{email}: {old_tier} → {tier}',
        'user': user.to_dict(),
    })
