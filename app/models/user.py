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
    # Tier: 'free' | 'pro' | 'premium'
    tier = db.Column(db.String(20), default='free')
    # Subscription status: 'pending' | 'approved' | 'rejected' | 'suspended'
    status = db.Column(db.String(20), default='pending', nullable=False)

    stripe_customer_id = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by = db.Column(db.Integer, nullable=True)  # admin user id
    last_login_at = db.Column(db.DateTime, nullable=True)

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

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'role': self.role,
            'tier': self.tier,
            'status': self.status,
            'subscription_status': self.status,  # 프론트엔드 호환
            'stripe_customer_id': self.stripe_customer_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
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
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
        }
