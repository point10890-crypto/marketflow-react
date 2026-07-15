"""Authentication routes — 회원가입, 로그인, 프로필, 구독 요청"""

import os
import re
import hmac
import ipaddress
import time
import threading
import requests as http_requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, current_app, has_app_context
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
_LOGIN_MAX_KEYS = 5000


def _login_rate_key(ip: str, email: str = '') -> str:
    """Scope login throttling to an account on a client IP.

    Cloudflare Tunnel and local reverse proxies can collapse many users onto
    one remote_addr. IP-only throttling can lock out unrelated members after
    another user mistypes a password several times.
    """
    clean_ip = (ip or '0.0.0.0').strip() or '0.0.0.0'
    clean_email = (email or '').strip().lower()
    return f'{clean_ip}|{clean_email}' if clean_email else clean_ip


def _check_login_rate_limit(key: str) -> bool:
    """Returns True if IP is currently blocked due to too many failures."""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SEC
    with _login_lock:
        failures = [t for t in _login_failures.get(key, []) if t > cutoff]
        _login_failures[key] = failures
        return len(failures) >= _LOGIN_MAX_FAILURES


def _record_login_failure(key: str):
    """Record a failed login attempt."""
    now = time.time()
    cutoff = now - _LOGIN_WINDOW_SEC
    with _login_lock:
        failures = [t for t in _login_failures.get(key, []) if t > cutoff]
        failures.append(now)
        _login_failures[key] = failures
        # 주기적 cleanup
        if len(_login_failures) > 200:
            expired = [k for k, v in _login_failures.items() if not v or max(v) < cutoff]
            for k in expired:
                del _login_failures[k]
        if len(_login_failures) > _LOGIN_MAX_KEYS:
            oldest = sorted(
                _login_failures,
                key=lambda item: max(_login_failures[item]) if _login_failures[item] else 0,
            )[:500]
            for old_key in oldest:
                _login_failures.pop(old_key, None)


def _reset_login_failures(key: str):
    """Reset failures on successful login."""
    with _login_lock:
        _login_failures.pop(key, None)


# ═══════════════════════════════════════════════════════
#  Registration Rate Limiter (in-memory, per IP)
# ═══════════════════════════════════════════════════════
_reg_attempts = {}   # {ip: [timestamp, ...]}
_reg_lock = threading.Lock()
_REG_MAX_ATTEMPTS = 5
_REG_WINDOW_SEC = 600  # 10 minutes
_REG_MAX_KEYS = 5000


def _client_ip() -> str:
    """Return a validated client IP without trusting spoofable proxy headers.

    Cloudflare Tunnel connects to the Flask service from loopback.  Additional
    reverse proxies can be explicitly listed in ``TRUSTED_PROXY_IPS``.  Direct
    clients cannot rotate ``Cf-Connecting-IP``/``X-Forwarded-For`` to bypass
    login and registration throttles.
    """
    peer = (request.remote_addr or '').strip()
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        peer_ip = None

    configured = {
        value.strip()
        for value in os.getenv('TRUSTED_PROXY_IPS', '').split(',')
        if value.strip()
    }
    trusted_proxy = bool(peer_ip and peer_ip.is_loopback) or peer in configured
    if trusted_proxy:
        forwarded = (
            request.headers.get('Cf-Connecting-IP')
            or request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
        )
        try:
            return str(ipaddress.ip_address((forwarded or '').strip()))
        except ValueError:
            pass
    return str(peer_ip) if peer_ip else '0.0.0.0'


def _check_reg_rate_limit(ip: str) -> bool:
    """Returns True if IP is blocked from registering."""
    now = time.time()
    cutoff = now - _REG_WINDOW_SEC
    with _reg_lock:
        attempts = [t for t in _reg_attempts.get(ip, []) if t > cutoff]
        _reg_attempts[ip] = attempts
        return len(attempts) >= _REG_MAX_ATTEMPTS


def _record_reg_attempt(ip: str):
    """Record a registration attempt."""
    now = time.time()
    cutoff = now - _REG_WINDOW_SEC
    with _reg_lock:
        attempts = [t for t in _reg_attempts.get(ip, []) if t > cutoff]
        attempts.append(now)
        _reg_attempts[ip] = attempts
        if len(_reg_attempts) > 200:
            expired = [k for k, v in _reg_attempts.items() if not v or max(v) < cutoff]
            for k in expired:
                del _reg_attempts[k]
        if len(_reg_attempts) > _REG_MAX_KEYS:
            oldest = sorted(
                _reg_attempts,
                key=lambda item: max(_reg_attempts[item]) if _reg_attempts[item] else 0,
            )[:500]
            for old_key in oldest:
                _reg_attempts.pop(old_key, None)


# ═══════════════════════════════════════════════════════
#  Password Policy
# ═══════════════════════════════════════════════════════
def _validate_password(pw: str) -> tuple[bool, str]:
    """비밀번호 정책 검증. Returns (ok, error_msg)."""
    if len(pw) > 128:
        return False, '비밀번호는 128자 이하여야 합니다.'
    if len(pw) < 8:
        return False, '비밀번호는 8자 이상이어야 합니다'
    if not re.search(r'[A-Za-z]', pw):
        return False, '비밀번호에 영문자를 포함해야 합니다'
    if not re.search(r'\d', pw):
        return False, '비밀번호에 숫자를 포함해야 합니다'
    return True, ''


def _is_reserved_notify_email(email: str | None) -> bool:
    """테스트/감사용 예약 계정 여부 (admin.py `_is_reserved_admin_notify_target` 와 동일 규칙)."""
    email = (email or '').strip().lower()
    if not email:
        return False
    return email.endswith('@example.com') or email.startswith('audit_')


def _notify_admin_telegram(message: str, target_email: str | None = None):
    """관리자 텔레그램으로 알림 전송 (비동기, 실패는 경고 로그).

    pytest(TESTING 앱) 실행과 @example.com 예약 계정(테스트/감사 시나리오)은
    실제 전송하지 않는다 — 테스트 스위트가 돌 때마다 관리자에게
    '💳 구독 요청' 스팸이 반복 발송되던 문제 차단.
    """
    import logging as _logging
    _logger = _logging.getLogger("marketflow.telegram")

    if _is_reserved_notify_email(target_email):
        _logger.info(f"telegram[auth] suppressed reserved target: {target_email}")
        return
    if has_app_context() and current_app.config.get('TESTING'):
        _logger.info("telegram[auth] skipped: TESTING app")
        return

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


# ═══════════════════════════════════════════════════════
#  Public Auth API
# ═══════════════════════════════════════════════════════

@auth_bp.route('/register', methods=['POST'])
def register():
    # Rate limit check
    client_ip = _client_ip()
    if _check_reg_rate_limit(client_ip):
        return jsonify({'error': '가입 요청이 너무 많습니다. 잠시 후 다시 시도하세요.'}), 429
    _record_reg_attempt(client_ip)

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    # 가입 시 선택한 플랜 ('pro'|'premium'|None). 첫 유저(admin)는 무시.
    requested_tier_raw = (data.get('requested_tier') or '').strip().lower()
    requested_tier = requested_tier_raw if requested_tier_raw in ('pro', 'premium') else None

    if not email or not password or not name:
        return jsonify({'error': 'email, password, name are required'}), 400
    if len(email) > 254 or len(name) > 100 or len(password) > 128:
        return jsonify({'error': 'Registration field exceeds maximum length'}), 400

    pw_ok, pw_err = _validate_password(password)
    if not pw_ok:
        return jsonify({'error': pw_err}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 409

    # 가입은 기본 정보만 받는다. 플랜 선택은 /plan-select 페이지에서 별도 진행.
    # requested_tier 는 하위호환 — 폼에서 보내면 그대로 저장(NULL 허용).
    is_first_user = User.query.count() == 0
    if is_first_user:
        bootstrap_secret = os.getenv('MARKETFLOW_BOOTSTRAP_ADMIN_SECRET', '').strip()
        supplied_secret = request.headers.get('X-Bootstrap-Admin-Secret', '')
        if not bootstrap_secret:
            return jsonify({
                'error': 'Initial admin bootstrap is not configured',
            }), 503
        if not hmac.compare_digest(supplied_secret, bootstrap_secret):
            return jsonify({'error': 'Initial admin bootstrap denied'}), 403

    # 동일 이름 중복 가입 경고 (차단은 하지 않음 — 동명이인 가능)
    same_name_users = User.query.filter(db.func.lower(User.name) == name.lower()).all()
    if same_name_users:
        existing_emails = ', '.join(u.email for u in same_name_users[:3])
        _notify_admin_telegram(
            f"⚠️ <b>중복 의심 가입</b>\n\n"
            f"👤 이름: {name}\n"
            f"📧 신규: {email}\n"
            f"📧 기존: {existing_emails}\n"
            f"⚡ 동명이인일 수 있으니 확인 바랍니다.",
            target_email=email,
        )

    user = User(email=email, name=name)
    user.set_password(password)

    # 첫 번째 유저는 자동으로 admin + approved + premium (운영자)
    # 그 외 신규 가입자는 pending 상태 — 관리자가 tier(pro/premium) 부여해야
    # 앱에 접근 가능. 'free' 플랜은 더 이상 존재하지 않음.
    if is_first_user:
        user.role = 'admin'
        user.status = 'approved'
        user.tier = 'premium'
    else:
        user.status = 'pending'
        user.tier = None
        user.requested_tier = requested_tier

    db.session.add(user)
    db.session.commit()

    # 관리자 텔레그램 알림 (신규 가입 + 요청 플랜)
    tier_label = {'pro': 'Pro (5만원/30일)', 'premium': 'Ultra Pro (120만원/무기한)'}.get(
        requested_tier or '', '미선택'
    )
    _notify_admin_telegram(
        f"👤 <b>신규 회원가입</b>\n\n"
        f"📧 이메일: {user.email}\n"
        f"👤 이름: {user.name}\n"
        f"📋 요청 플랜: {tier_label}\n"
        f"📅 가입일: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        target_email=user.email,
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
    client_ip = _client_ip()

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400
    if len(email) > 254 or len(password) > 128:
        return jsonify({'error': 'Invalid email or password'}), 401

    rate_key = _login_rate_key(client_ip, email)
    if _check_login_rate_limit(rate_key):
        return jsonify({'error': 'Too many login attempts. Please try again later.'}), 429

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        _record_login_failure(rate_key)
        return jsonify({'error': 'Invalid email or password'}), 401

    # 계정 상태 검증 (admin은 상태 무관 허용)
    #
    # pending 사용자는 로그인 자체를 막지 않는다.
    # 가입 직후 브라우저를 닫았거나 승인 대기 중 다시 방문한 사용자가
    # /pending-approval 또는 /plan-select 에서 결제/승인 흐름을 계속 이어갈 수
    # 있어야 한다. 실제 서비스 접근은 프론트 가드와 pro_required 에서 막는다.
    if user.status == 'suspended':
        return jsonify({'error': '계정이 정지되었습니다. 관리자에게 문의하세요.', 'status': 'suspended'}), 403
    if user.status == 'rejected':
        return jsonify({'error': '가입이 거절되었습니다.', 'status': 'rejected'}), 403

    # 로그인 성공 — 실패 카운터 리셋
    _reset_login_failures(rate_key)

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


@auth_bp.route('/change-password', methods=['PUT'])
@login_required
def change_password():
    """유저 본인 비밀번호 변경 (현재 비밀번호 확인 필수)"""
    user = request.current_user
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json() or {}
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    if not current_password or not new_password:
        return jsonify({'error': '현재 비밀번호와 새 비밀번호를 입력하세요'}), 400
    pw_ok, pw_err = _validate_password(new_password)
    if not pw_ok:
        return jsonify({'error': pw_err}), 400
    if not user.check_password(current_password):
        return jsonify({'error': '현재 비밀번호가 일치하지 않습니다'}), 401

    user.set_password(new_password)
    db.session.commit()

    return jsonify({'message': '비밀번호가 변경되었습니다'})


@auth_bp.route('/subscription/request', methods=['POST'])
@login_required
def request_subscription():
    """구독 변경 요청 (free → pro 등)"""
    user = request.current_user
    if not user:
        return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json() or {}
    to_tier = (data.get('to_tier') or '').strip().lower()
    # AI Brain 알파 스캐너 애드온 포함 여부 (별도 30일 갱신 구독 +40,000원/30일)
    includes_aibain = bool(data.get('includes_aibain'))

    # 'free' 플랜은 폐지 — 구독 가능한 tier는 pro / premium 뿐
    if to_tier not in ('pro', 'premium'):
        return jsonify({'error': 'Invalid tier. Use: pro, premium'}), 400

    is_expired_resubscribe = bool(user.status == 'expired' or user.is_pro_expired)

    # 같은 tier 요청은 AI Brain 애드온 또는 만료 재구독일 때만 허용.
    # 만료 Pro 회원은 tier 값이 여전히 'pro' 이므로 이 예외가 없으면
    # "Already on pro tier" 로 재구독 신청이 막힌다.
    if to_tier == user.tier and not includes_aibain and not is_expired_resubscribe:
        return jsonify({'error': f'Already on {to_tier} tier'}), 400

    # premium(Ultra Pro)은 최상위 — 베이스 다운그레이드 불가 (AI Brain 추가는 같은 tier 라 위 체크에서 통과)
    if user.tier == 'premium' and to_tier == 'pro' and not is_expired_resubscribe:
        return jsonify({'error': 'Ultra Pro는 최상위 플랜입니다. 다운그레이드할 수 없습니다.'}), 400

    # 이미 pending 요청이 있는지 확인
    existing = SubscriptionRequest.query.filter_by(
        user_id=user.id, status='pending'
    ).first()
    if existing:
        return jsonify({'error': 'You already have a pending subscription request'}), 409

    # 요청 종류 판정
    # - aibain_addon: 같은 tier + AI Brain 만 추가 (활성 회원의 업그레이드 시나리오)
    # - upgrade:      신규 가입자 + tier 상승
    # - downgrade:    하향 (현재 비활성)
    is_aibain_addon = (to_tier == user.tier and includes_aibain)
    if is_aibain_addon:
        req_type = 'aibain_addon'
    elif is_expired_resubscribe:
        req_type = 'renewal'
    elif user.tier is None or (user.tier == 'pro' and to_tier == 'premium'):
        req_type = 'upgrade'
    else:
        req_type = 'downgrade'

    if user.status == 'pending':
        user.requested_tier = to_tier

    depositor_name = (data.get('depositor_name') or '').strip() or None

    # 입금 금액 계산
    # - aibain_addon: 40,000원 (AI Brain 만)
    # - else + aibain: 베이스 + 40,000 (전체)
    # - else:         베이스 (50k 또는 1.2M)
    base_amount_map = {'pro': 50_000, 'premium': 1_200_000}
    if is_aibain_addon:
        total_amount = 40_000
    else:
        base_amount = base_amount_map.get(to_tier, 0)
        aibain_amount = 40_000 if includes_aibain else 0
        total_amount = base_amount + aibain_amount
    amount = f"{total_amount:,}원" if total_amount else None

    # admin 패널 비고 (DB 신규 column 없이 admin_note 활용)
    if is_aibain_addon:
        admin_note = 'AI Brain 알파 스캐너 애드온 신청 (+40,000원/30일, 베이스 tier 유지)'
    elif is_expired_resubscribe and includes_aibain:
        admin_note = '만료 회원 재구독 신청 + AI Brain 알파 스캐너 포함 요청 (+40,000원/30일)'
    elif is_expired_resubscribe:
        admin_note = '만료 회원 재구독 신청'
    elif includes_aibain:
        admin_note = 'AI Brain 알파 스캐너 포함 요청 (+40,000원/30일)'
    else:
        admin_note = None

    sub_request = SubscriptionRequest(
        user_id=user.id,
        request_type=req_type,
        # from_tier NOT NULL — None 유저는 'none' 문자열로 기록
        from_tier=user.tier or 'none',
        to_tier=to_tier,
        depositor_name=depositor_name,
        amount=amount,
        admin_note=admin_note,
    )
    db.session.add(sub_request)
    db.session.commit()

    # 관리자 텔레그램 + 인앱 알림
    tier_label = {'pro': 'Pro', 'premium': 'Ultra Pro'}.get(to_tier, to_tier)
    if is_aibain_addon:
        # 같은 tier 에 AI Brain 만 추가 (예: 활성 Pro 회원 → +AI Brain)
        full_label = f"{tier_label} → +AI Brain 애드온"
        header_emoji = "🤖"
    elif includes_aibain:
        full_label = f"{tier_label} + AI Brain"
        header_emoji = "💳"
    else:
        full_label = tier_label
        header_emoji = "💳"
    _notify_admin_telegram(
        f"{header_emoji} <b>구독 요청</b>\n\n"
        f"👤 {user.name} ({user.email})\n"
        f"📋 {user.tier or 'none'} → {full_label}\n"
        f"💰 {amount or '-'}" +
        (f"\n🤖 <b>AI Brain 알파 스캐너 포함</b> (+40,000원/30일)" if includes_aibain else ''),
        target_email=user.email,
    )
    from app.routes.admin import create_admin_notification
    create_admin_notification(
        'subscription_request',
        f'구독 요청: {full_label}',
        f'{user.name} ({user.email}) — {user.tier or "none"} → {to_tier}'
        + (' [AI Brain 포함]' if includes_aibain else ''),
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
    """Retired: tier changes must use the audited Bearer-token admin API."""
    return jsonify({
        'error': 'Legacy admin endpoint retired; use /api/admin/users/<id>/tier',
    }), 410
