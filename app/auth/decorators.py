"""Auth decorators for Flask routes"""

import hashlib
import hmac
import os
import time
import threading
from datetime import timezone
from functools import wraps
from flask import request, jsonify, current_app
from app.models import db
from app.models.user import User

# Simple token: sha256(user_id + secret + expiry)
TOKEN_EXPIRY = 86400 * 30  # 30 days


def _get_secret():
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        raise RuntimeError('SECRET_KEY is not configured')
    return str(secret)


def generate_token(user_id: int) -> str:
    expiry = int(time.time()) + TOKEN_EXPIRY
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(
        _get_secret().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{payload}:{sig}"


def validate_token(token: str):
    """Returns user_id if valid, None otherwise."""
    try:
        parts = token.split(':')
        if len(parts) != 3:
            return None
        user_id, expiry, sig = int(parts[0]), int(parts[1]), parts[2]
        if time.time() > expiry:
            return None
        expected = hmac.new(
            _get_secret().encode(), f"{user_id}:{expiry}".encode(), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return user_id
    except (ValueError, IndexError):
        return None


# 토큰 발급시각 비교 여유 (초). expiry 가 초 단위 절삭이라 발급 직후 토큰이
# password_changed_at 보다 미세하게 과거로 보일 수 있다 (가입 직후 토큰 등).
_PW_CHANGE_GRACE_SEC = 5


def _get_current_user():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    user_id = validate_token(token)
    if user_id is None:
        return None
    user = db.session.get(User, user_id)
    if user is None:
        return None
    # 비밀번호 변경 이전에 발급된 토큰은 무효 — 유출 토큰/구 세션 강제 로그아웃.
    changed = getattr(user, 'password_changed_at', None)
    if changed is not None:
        try:
            expiry = int(token.split(':')[1])
            issued_at = expiry - TOKEN_EXPIRY
            if changed.tzinfo is None:
                changed_ts = changed.replace(tzinfo=timezone.utc).timestamp()
            else:
                changed_ts = changed.timestamp()
            if issued_at + _PW_CHANGE_GRACE_SEC < changed_ts:
                return None
        except (ValueError, IndexError):
            return None
    return user


def _is_account_blocked(user: User) -> bool:
    """Explicit suspension/rejection overrides role and subscription bypasses."""
    return user.status in {'suspended', 'rejected'}


def login_required(f):
    """인증 필수 — 로그인한 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if _is_account_blocked(user):
            return jsonify({'error': 'Account access denied', 'status': user.status}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def approved_required(f):
    """승인된 유저 전용 — 관리자가 승인한 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if _is_account_blocked(user):
            return jsonify({'error': 'Account access denied', 'status': user.status}), 403
        if not user.is_approved and not user.is_admin:
            return jsonify({'error': 'Account not approved. Please wait for admin approval.'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def pro_required(f):
    """Pro 구독 유저 전용 — 승인 + Pro tier"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if _is_account_blocked(user):
            return jsonify({'error': 'Account access denied', 'status': user.status}), 403
        if not user.is_approved and not user.is_admin:
            return jsonify({'error': 'Account not approved'}), 403
        if user.tier not in ('pro', 'premium') and not user.is_admin:
            return jsonify({'error': 'Pro subscription required'}), 403
        # Pro 만료 체크 (premium은 무기한)
        if user.is_pro_expired:
            return jsonify({'error': 'Pro subscription expired', 'expired': True}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """관리자 전용 — role='admin' 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if _is_account_blocked(user):
            return jsonify({'error': 'Account access denied', 'status': user.status}), 403
        if not user.is_admin:
            return jsonify({'error': 'Admin access denied'}), 403

        request.current_user = user
        if (request.path or '').startswith('/api/admin/mirofish'):
            request.current_user_id = user.id
            request.current_user_email = user.email
            try:
                db.session.expunge(user)
            except Exception:
                pass
            db.session.remove()
        return f(*args, **kwargs)
    return decorated


def admin_or_aibain_required(f):
    """관리자 OR AI Brain 활성 구독자 허용 — read-only 분석 데이터 전용.

    토큰 검증 후 다음 둘 중 하나여야 통과:
      1) user.is_admin == True
      2) user.is_aibain_active == True (aibain_enabled + 미만료)
    그 외 403. mutation/제어 엔드포인트에는 사용 금지.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if _is_account_blocked(user):
            return jsonify({'error': 'Account access denied', 'status': user.status}), 403
        if not (user.is_admin or user.is_aibain_active):
            return jsonify({
                'error': 'AI Brain 구독자 또는 관리자만 접근 가능합니다.'
            }), 403

        request.current_user = user
        # admin_required 와 동일한 세션 정리 (mirofish 경로용)
        if (request.path or '').startswith('/api/admin/mirofish'):
            request.current_user_id = user.id
            request.current_user_email = user.email
            try:
                db.session.expunge(user)
            except Exception:
                pass
            db.session.remove()
        return f(*args, **kwargs)
    return decorated
