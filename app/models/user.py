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

    # 가입 시 유저가 선택한 구독 플랜 ('pro'|'premium'|NULL).
    # 관리자가 승인 시 이 값을 기본으로 tier 를 부여한다.
    # 기존 유저는 NULL 유지 — 마이그레이션에서 채우지 않음.
    requested_tier = db.Column(db.String(20), nullable=True)

    # ── AI Bain 알파 스캐너 애드온 (별도 30일 갱신 구독, 베이스 tier 와 독립) ───
    aibain_enabled = db.Column(db.Boolean, default=False, nullable=False)
    aibain_expires_at = db.Column(db.DateTime, nullable=True)
    # AI Bain 만료 D-3/D-1 알림 stage: 'd3' | 'd1' | 'expired' | NULL
    aibain_alert_stage = db.Column(db.String(10), nullable=True)
    # Pro 만료 카운터 일시정지 시각 (AI Bain 활성 중 Pro 기간 보존용).
    # 활성: AI Bain 활성화 시점부터 만료/해제 시까지 NULL 이 아님.
    # AI Bain 만료/해제 시: now - pro_paused_at 만큼 pro_expires_at 연장 후 NULL 처리.
    # pro_expiry_checker 는 paused 유저 skip (D-3/D-1/expired 알림 보류).
    pro_paused_at = db.Column(db.DateTime, nullable=True)

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
        """Pro 구독 만료 여부 (premium은 만료 없음).

        AI Bain 활성 중 pro_paused_at 이 세팅된 paused 유저는 만료 처리 안 함.
        AI Bain 만료/해제 시 expiry checker 가 paused 기간만큼 pro_expires_at 연장 후 paused 해제.
        """
        if self.tier != 'pro':
            return False
        if self.pro_expires_at is None:
            return False
        # Pro 일시정지 중 (AI Bain 활성) → 만료 처리 안 함
        if self.pro_paused_at is not None:
            return False
        # SQLAlchemy stores naive datetimes; normalize both sides to naive UTC for comparison.
        expires = self.pro_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.utcnow() > expires

    @property
    def is_pro_paused(self) -> bool:
        """Pro 만료 카운터가 AI Bain 활성으로 일시정지 상태인지."""
        return self.pro_paused_at is not None

    @property
    def is_aibain_active(self) -> bool:
        """AI Bain 알파 스캐너 활성 여부 (베이스 tier 와 무관)"""
        if not self.aibain_enabled:
            return False
        if self.aibain_expires_at is None:
            return True  # NULL = 무기한 (운영자가 수동 설정한 경우)
        expires = self.aibain_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.utcnow() < expires

    @property
    def aibain_days_remaining(self) -> int | None:
        """AI Bain 만료까지 남은 일수 (None = 활성 안 됨 또는 만료)"""
        if not self.is_aibain_active or self.aibain_expires_at is None:
            return None
        expires = self.aibain_expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        delta = expires - datetime.utcnow()
        return max(0, delta.days)

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'name': self.name,
            'role': self.role,
            'tier': self.tier,
            'status': self.status,
            'pro_expires_at': self.pro_expires_at.isoformat() if self.pro_expires_at else None,
            'is_pro_expired': self.is_pro_expired,
            'requested_tier': self.requested_tier,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'last_login_at': self.last_login_at.isoformat() if self.last_login_at else None,
            # AI Bain 알파 스캐너 (애드온)
            'aibain_enabled': self.aibain_enabled,
            'aibain_expires_at': self.aibain_expires_at.isoformat() if self.aibain_expires_at else None,
            'is_aibain_active': self.is_aibain_active,
            'aibain_days_remaining': self.aibain_days_remaining,
            # Pro 일시정지 상태 (AI Bain 활성 중 Pro 만료 카운터 보존)
            'pro_paused_at': self.pro_paused_at.isoformat() if self.pro_paused_at else None,
            'is_pro_paused': self.is_pro_paused,
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
