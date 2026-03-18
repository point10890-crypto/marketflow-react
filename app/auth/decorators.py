"""Auth decorators for Flask routes"""

import hashlib
import hmac
import os
import time
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


def _auth_disabled():
    """인증 비활성화 여부 — 개발 단계에서 모든 인증/구독 제한 해제.

    활성화 조건 (OR):
      1. Flask debug 모드
      2. AUTH_DISABLED=true 환경변수
      3. DEV_MODE=true 환경변수
      4. RENDER 환경변수 존재 (Render 배포 자동 감지)

    프로덕션 전환 시:
      - Render: DEV_MODE 환경변수 제거 + 아래 RENDER 체크 라인 삭제
      - 로컬: .env에서 DEV_MODE 제거
    """
    if current_app.debug:
        return True
    if os.getenv('AUTH_DISABLED', '').lower() in ('true', '1', 'yes'):
        return True
    if os.getenv('DEV_MODE', '').lower() in ('true', '1', 'yes'):
        return True
    # 개발 단계: Render 배포 시 자동으로 인증 해제 (프로덕션 전환 시 이 줄 삭제)
    if os.getenv('RENDER'):
        return True
    return False


def login_required(f):
    """인증 필수 — 로그인한 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if _auth_disabled():
            request.current_user = None
            return f(*args, **kwargs)
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
        if _auth_disabled():
            request.current_user = None
            return f(*args, **kwargs)
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
        if _auth_disabled():
            request.current_user = None
            return f(*args, **kwargs)
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if not user.is_approved and not user.is_admin:
            return jsonify({'error': 'Account not approved'}), 403
        if user.tier not in ('pro', 'premium') and not user.is_admin:
            return jsonify({'error': 'Pro subscription required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """관리자 전용 — role='admin' 유저만 접근 가능"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if _auth_disabled():
            request.current_user = None
            return f(*args, **kwargs)
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if not user.is_admin:
            return jsonify({'error': 'Admin access denied'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated
