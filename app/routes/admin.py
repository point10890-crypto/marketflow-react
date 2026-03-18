"""Admin API routes — 관리자 전용 엔드포인트"""

import os
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from app.models import db
from app.models.user import User, SubscriptionRequest
from app.auth.decorators import admin_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/dashboard')
@admin_required
def dashboard():
    """관리자 대시보드 통계"""
    users = User.query.all()
    pending_subs = SubscriptionRequest.query.filter_by(status='pending').count()

    return jsonify({
        'total_users': len(users),
        'pro_users': sum(1 for u in users if u.tier == 'pro'),
        'free_users': sum(1 for u in users if u.tier == 'free'),
        'premium_users': sum(1 for u in users if u.tier == 'premium'),
        'admin_users': sum(1 for u in users if u.role == 'admin'),
        'pending_users': sum(1 for u in users if u.status == 'pending'),
        'approved_users': sum(1 for u in users if u.status == 'approved'),
        'pending_subscriptions': pending_subs,
    })


@admin_bp.route('/users')
@admin_required
def list_users():
    """전체 유저 목록 조회"""
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({'users': [u.to_dict() for u in users]})


@admin_bp.route('/users/<int:user_id>')
@admin_required
def get_user(user_id):
    """유저 상세 조회"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user.to_dict())


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

    old_role = user.role
    user.role = role
    db.session.commit()

    return jsonify({
        'message': f'{user.email}: {old_role} → {role}',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/tier', methods=['PUT'])
@admin_required
def set_tier(user_id):
    """유저 구독 tier 변경 (free ↔ pro ↔ premium)"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    tier = (data.get('tier') or '').strip().lower()
    if tier not in ('free', 'pro', 'premium'):
        return jsonify({'error': 'Tier must be free, pro, or premium'}), 400

    old_tier = user.tier
    user.tier = tier
    db.session.commit()

    return jsonify({
        'message': f'{user.email}: {old_tier} → {tier}',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def set_status(user_id):
    """유저 계정 상태 변경 (pending → approved 등)"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    status = (data.get('status') or '').strip().lower()
    if status not in ('pending', 'approved', 'rejected', 'suspended'):
        return jsonify({'error': 'Status must be pending, approved, rejected, or suspended'}), 400

    old_status = user.status
    user.status = status

    if status == 'approved':
        admin_user = getattr(request, 'current_user', None)
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin_user.id if admin_user else None

    db.session.commit()

    return jsonify({
        'message': f'{user.email}: {old_status} → {status}',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """유저 삭제"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    admin_user = getattr(request, 'current_user', None)
    if admin_user and admin_user.id == user_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400

    # 연관 구독 요청도 삭제
    SubscriptionRequest.query.filter_by(user_id=user_id).delete()
    db.session.delete(user)
    db.session.commit()

    return jsonify({'message': f'User {user.email} deleted'})


@admin_bp.route('/subscriptions')
@admin_required
def list_subscriptions():
    """구독 요청 목록 조회"""
    reqs = SubscriptionRequest.query.order_by(
        SubscriptionRequest.created_at.desc()
    ).all()
    return jsonify({'requests': [r.to_dict() for r in reqs]})


@admin_bp.route('/subscriptions/<int:req_id>/approve', methods=['PUT'])
@admin_required
def approve_subscription(req_id):
    """구독 요청 승인"""
    sub_req = db.session.get(SubscriptionRequest, req_id)
    if not sub_req:
        return jsonify({'error': 'Request not found'}), 404
    if sub_req.status != 'pending':
        return jsonify({'error': f'Request already {sub_req.status}'}), 400

    admin_user = getattr(request, 'current_user', None)

    # 요청 승인
    sub_req.status = 'approved'
    sub_req.processed_at = datetime.now(timezone.utc)
    sub_req.processed_by = admin_user.id if admin_user else None

    # 유저 tier 변경 적용
    user = db.session.get(User, sub_req.user_id)
    if user:
        user.tier = sub_req.to_tier
        if user.status == 'pending':
            user.status = 'approved'

    db.session.commit()

    return jsonify({
        'message': f'Subscription approved: {sub_req.from_tier} → {sub_req.to_tier}',
        'request': sub_req.to_dict(),
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

    admin_user = getattr(request, 'current_user', None)
    data = request.get_json() or {}

    sub_req.status = 'rejected'
    sub_req.admin_note = data.get('note') or data.get('admin_note') or ''
    sub_req.processed_at = datetime.now(timezone.utc)
    sub_req.processed_by = admin_user.id if admin_user else None

    db.session.commit()

    return jsonify({
        'message': 'Subscription request rejected',
        'request': sub_req.to_dict(),
    })
