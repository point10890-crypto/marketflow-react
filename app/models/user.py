"""User model + SubscriptionRequest model"""

from datetime import datetime, timezone
import bcrypt
from app.models import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)

    # Role: 'user' | 'admin'
    role = db.Column(db.String(20), default='user', nullable=False)
    # Tier: 'pro' | 'premium' | NULL
    # NULL means no active subscription — user cannot access the app.
    # Access is gated by (status=='approved' AND tier IN ('pro','premium')).
    tier = db.Column(db.String(20), nullable=True)
    # Subscription status: 'pending' | 'approved' | 'rejected' | 'suspended'
    status = db.Column(db.String(20), default='pending', nullable=False)

    # Pro 구독 만료일 (premium은 NULL = 무기한)
    pro_expires_at = db.Column(db.DateTime, nullable=True)

    stripe_customer_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, nullable=True)  # admin user id
    last_login_at = db.Column(db.DateTime, nullable=True)

    # 만료 D-3/D-1 알림 중복 방지: 'd3' | 'd1' | 'expired' | NULL
    # 만료일이 갱신되면(extend/tier 변경) NULL 로 리셋해 알림이 다시 발송된다.
    pro_expiry_alert_stage = db.Column(db.String(10), nullable=True)

    def set_password(self, password: str):
        self.password_hash = bcrypt.hashpw(
            password.encode('utf-8'), bcrypt.gensalt()
        ).decode('utf-8')

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode('utf-8'),
            self.password_hash.encode('utf-8')
        )

    @property
    def is_admin(self) -> bool:
        return self.role == 'admin'

    @property
    def is_approved(self) -> bool:
        return self.status == 'approved'

    @property
    def is_pro_expired(self) -> bool:
        """Pro 구독 만료 여부 (premium은 만료 없음)"""
        if self.tier != 'pro':
            return False
        if self.pro_expires_at is None:
            return False
        # SQLAlchemy stores naive datetimes; normalize both sides to naive UTC for comparison.
        expires = self.pro_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.utcnow() > expires

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'role': self.role,
            'tier': self.tier,
            'status': self.status,
            'pro_expires_at': self.pro_expires_at.isoformat() if self.pro_expires_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
        }


class AdminAuditLog(db.Model):
    """관리자 행위 감사 로그 — 모든 mutation 기록 (회원 관리 추적용)."""
    __tablename__ = 'admin_audit_log'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, nullable=True)  # 액션 수행한 관리자 id
    admin_email = db.Column(db.String(255), nullable=True)
    action = db.Column(db.String(50), nullable=False, index=True)  # set_tier, set_status, ...
    target_user_id = db.Column(db.Integer, nullable=True, index=True)
    target_email = db.Column(db.String(255), nullable=True)
    before = db.Column(db.Text, nullable=True)  # JSON
    after = db.Column(db.Text, nullable=True)   # JSON
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'admin_id': self.admin_id,
            'admin_email': self.admin_email,
            'action': self.action,
            'target_user_id': self.target_user_id,
            'target_email': self.target_email,
            'before': json.loads(self.before) if self.before else None,
            'after': json.loads(self.after) if self.after else None,
            'note': self.note,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class AdminNotification(db.Model):
    """관리자 인앱 알림 — 구매신청, 구독요청, 신규가입 등 이벤트 발생 시 자동 생성"""
    __tablename__ = 'admin_notifications'

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False, index=True)  # purchase_request, subscription_request, new_signup
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    related_id = db.Column(db.Integer, nullable=True)  # 관련 엔티티 ID (purchase_id, subscription_id, user_id)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'title': self.title,
            'message': self.message,
            'is_read': self.is_read,
            'related_id': self.related_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class SubscriptionRequest(db.Model):
    """구독 변경 요청 (free→pro, pro→premium 등)"""
    __tablename__ = 'subscription_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    request_type = db.Column(db.String(50), nullable=False)  # 'upgrade', 'downgrade'
    from_tier = db.Column(db.String(20), nullable=False)
    to_tier = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='pending')  # 'pending', 'approved', 'rejected'
    payment_id = db.Column(db.String(255), nullable=True)
    admin_note = db.Column(db.Text, nullable=True)
    depositor_name = db.Column(db.String(100), nullable=True)
    amount = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime, nullable=True)
    processed_by = db.Column(db.Integer, nullable=True)  # admin user id

    # Relationship
    user = db.relationship('User', backref=db.backref('subscription_requests', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_email': self.user.email if self.user else None,
            'user_name': self.user.name if self.user else None,
            'request_type': self.request_type,
            'from_tier': self.from_tier,
            'to_tier': self.to_tier,
            'status': self.status,
            'payment_id': self.payment_id,
            'admin_note': self.admin_note,
            'depositor_name': self.depositor_name,
            'amount': self.amount,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }
