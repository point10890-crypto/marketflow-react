"""Auth decorators for Flask routes"""

import hashlib
import hmac
import os
import time
import threading
from functools import wraps
from flask import request, jsonify, current_app
from app.models import db
from app.models.user import User

# Simple token: sha256(user_id + secret + expiry)
TOKEN_EXPIRY = 86400 * 30  # 30 days


def _get_secret():
    return current_app.config.get('SECRET_KEY', 'marketflow-default-secret')


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


def _get_current_user():
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return None
    token = auth[7:]
    user_id = validate_token(token)
    if user_id is None:
        return None
    return db.session.get(User, user_id)


def login_required(f):
    """인증 필수 — 로그인한 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
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


# ═══════════════════════════════════════════════════════
#  Admin Rate Limiter (consecutive failures → 15min block)
# ═══════════════════════════════════════════════════════
_admin_failures = {}   # {ip: {'count': int, 'blocked_until': float}}
_admin_lock = threading.Lock()
_ADMIN_MAX_FAILURES = 3
_ADMIN_BLOCK_SEC = 900  # 15 minutes


def _check_admin_rate_limit(ip: str) -> bool:
    """Returns True if IP is blocked due to consecutive admin auth failures."""
    now = time.time()
    with _admin_lock:
        entry = _admin_failures.get(ip)
        if not entry:
            return False
        if entry.get('blocked_until', 0) > now:
            return True  # still blocked
        # Block expired, reset
        if entry.get('blocked_until', 0) <= now and entry.get('blocked_until', 0) > 0:
            del _admin_failures[ip]
        return False


def _record_admin_failure(ip: str):
    """Record a failed admin auth attempt. Block after 3 consecutive failures."""
    now = time.time()
    with _admin_lock:
        entry = _admin_failures.get(ip, {'count': 0, 'blocked_until': 0})
        entry['count'] = entry.get('count', 0) + 1
        if entry['count'] >= _ADMIN_MAX_FAILURES:
            entry['blocked_until'] = now + _ADMIN_BLOCK_SEC
        _admin_failures[ip] = entry


def _reset_admin_failures(ip: str):
    """Reset failure count on successful admin auth."""
    with _admin_lock:
        _admin_failures.pop(ip, None)


def admin_required(f):
    """관리자 전용 — role='admin' 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
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
