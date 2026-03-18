"""Auth decorators for Flask routes"""

import hashlib
import hmac
import time
from functools import wraps
from flask import request, jsonify, current_app
from app.models import db
from app.models.user import User

# Simple token: sha256(user_id + secret + expiry)
TOKEN_EXPIRY = 86400 * 7  # 7 days


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
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated


def pro_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = _get_current_user()
        if user is None:
            return jsonify({'error': 'Authentication required'}), 401
        if user.tier != 'pro':
            return jsonify({'error': 'Pro subscription required'}), 403
        request.current_user = user
        return f(*args, **kwargs)
    return decorated
