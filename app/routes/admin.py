"""Admin API routes — 관리자 전용 엔드포인트"""

import os
from datetime import datetime, timezone, timedelta
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
        'premium_users': sum(1 for u in users if u.tier == 'premium'),
        # tier가 None/빈값인 유저 (신규 가입 · 만료 · 취소 후 대기)
        'no_tier_users': sum(1 for u in users if not u.tier),
        'admin_users': sum(1 for u in users if u.role == 'admin'),
        'pending_users': sum(1 for u in users if u.status == 'pending'),
        'approved_users': sum(1 for u in users if u.status == 'approved'),
        'suspended_users': sum(1 for u in users if u.status == 'suspended'),
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
    """유저 구독 tier 변경 (pro ↔ premium) — 지정 시 status도 approved로 자동 승격"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    tier = (data.get('tier') or '').strip().lower()
    # 'free' 플랜은 폐지. tier 해제(구독 없음)는 /status로 suspend 사용.
    if tier not in ('pro', 'premium'):
        return jsonify({'error': 'Tier must be pro or premium'}), 400

    old_tier = user.tier or 'none'
    user.tier = tier
    # tier 부여 시 자동으로 승인 처리 — 접근 권한이 즉시 활성화되도록
    if user.status != 'approved':
        user.status = 'approved'
        admin_user = getattr(request, 'current_user', None)
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = admin_user.id if admin_user else None
    # Pro 만료일 자동 설정 (premium은 무기한)
    if tier == 'pro' and not user.pro_expires_at:
        user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    elif tier == 'premium':
        user.pro_expires_at = None
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


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['PUT'])
@admin_required
def reset_password(user_id):
    """유저 비밀번호 리셋 → 임시 비밀번호 발급"""
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    data = request.get_json() or {}
    new_password = data.get('password', '').strip()
    if not new_password or len(new_password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    user.set_password(new_password)
    db.session.commit()

    return jsonify({
        'message': f'{user.email} 비밀번호 리셋 완료',
        'user': user.to_dict(),
    })


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    """유저 삭제 — 커뮤니티 게시글/댓글/구매요청까지 연쇄 제거.

    SQLAlchemy 관계에 cascade 가 지정되어 있지 않아 기본 동작은 자식행의 FK 를
    NULL 로 업데이트하는 것인데, posts/comments 의 author_id 와
    purchase_requests.user_id 는 NOT NULL 이므로 IntegrityError 가 발생한다.
    여기서 명시적으로 자식 레코드를 제거한 뒤 유저를 삭제한다.
    """
    from app.models.community import Post, PostImage, Comment, PurchaseRequest

    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    admin_user = getattr(request, 'current_user', None)
    if admin_user and admin_user.id == user_id:
        return jsonify({'error': 'Cannot delete yourself'}), 400

    # 삭제 전 정보 보존 (세션 분리 후 접근 불가)
    email = user.email

    try:
        # 1) 유저가 작성한 게시글에 달린 이미지/댓글/구매요청 제거
        user_post_ids = [p.id for p in Post.query.filter_by(author_id=user_id).all()]
        if user_post_ids:
            PostImage.query.filter(PostImage.post_id.in_(user_post_ids)).delete(synchronize_session=False)
            Comment.query.filter(Comment.post_id.in_(user_post_ids)).delete(synchronize_session=False)
            PurchaseRequest.query.filter(PurchaseRequest.post_id.in_(user_post_ids)).delete(synchronize_session=False)

        # 2) 유저가 다른 게시글에 남긴 댓글/구매요청 제거
        Comment.query.filter_by(author_id=user_id).delete(synchronize_session=False)
        PurchaseRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 3) 유저 게시글 본체 제거
        if user_post_ids:
            Post.query.filter(Post.id.in_(user_post_ids)).delete(synchronize_session=False)

        # 4) 연관 구독 요청 제거
        SubscriptionRequest.query.filter_by(user_id=user_id).delete(synchronize_session=False)

        # 5) 유저 삭제
        db.session.delete(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to delete user: {e}'}), 500

    return jsonify({'message': f'User {email} deleted'})


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

    # 유저 tier 변경 적용 + 만료일 설정
    user = db.session.get(User, sub_req.user_id)
    if user:
        user.tier = sub_req.to_tier
        if sub_req.to_tier == 'pro':
            # Pro: 승인일로부터 30일
            user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=30)
        elif sub_req.to_tier == 'premium':
            # Ultra Pro: 무기한
            user.pro_expires_at = None
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
