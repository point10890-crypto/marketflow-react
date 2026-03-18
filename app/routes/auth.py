"""Authentication routes — 회원가입, 로그인, 프로필, 구독 요청"""

import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.models import db
from app.models.user import User, SubscriptionRequest
from app.auth.decorators import generate_token, login_required

auth_bp = Blueprint('auth', __name__)

# 관리자 비밀키 (레거시 호환)
ADMIN_SECRET = os.getenv('ADMIN_SECRET', 'marketflow-admin-2024')


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

    # 첫 번째 유저는 자동으로 admin + approved + pro
    if User.query.count() == 0:
        user.role = 'admin'
        user.status = 'approved'
        user.tier = 'pro'
    else:
        user.status = 'pending'

    db.session.add(user)
    db.session.commit()

    token = generate_token(user.id)
    return jsonify({'user': user.to_dict(), 'token': token}), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'email and password are required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({'error': 'Invalid email or password'}), 401

    # 마지막 로그인 시간 업데이트
    user.last_login_at = datetime.now(timezone.utc)
    db.session.commit()

    token = generate_token(user.id)
    return jsonify({'user': user.to_dict(), 'token': token})


@auth_bp.route('/me')
@login_required
def me():
    return jsonify({'user': request.current_user.to_dict()})


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

    if to_tier not in ('free', 'pro', 'premium'):
        return jsonify({'error': 'Invalid tier. Use: free, pro, premium'}), 400

    if to_tier == user.tier:
        return jsonify({'error': f'Already on {to_tier} tier'}), 400

    # 이미 pending 요청이 있는지 확인
    existing = SubscriptionRequest.query.filter_by(
        user_id=user.id, status='pending'
    ).first()
    if existing:
        return jsonify({'error': 'You already have a pending subscription request'}), 409

    req_type = 'upgrade' if (
        (user.tier == 'free' and to_tier in ('pro', 'premium')) or
        (user.tier == 'pro' and to_tier == 'premium')
    ) else 'downgrade'

    sub_request = SubscriptionRequest(
        user_id=user.id,
        request_type=req_type,
        from_tier=user.tier,
        to_tier=to_tier,
    )
    db.session.add(sub_request)
    db.session.commit()

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
    secret = request.headers.get('X-Admin-Secret', '')
    if secret != ADMIN_SECRET:
        return jsonify({'error': 'Admin access denied'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body required'}), 400

    email = (data.get('email') or '').strip().lower()
    tier = (data.get('tier') or '').strip().lower()

    if not email or tier not in ('free', 'pro'):
        return jsonify({'error': 'email and tier (free/pro) are required'}), 400

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
