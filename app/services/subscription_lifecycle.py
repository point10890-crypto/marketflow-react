"""Deterministic membership clock and admin lifecycle presentation."""
from datetime import datetime, timedelta, timezone


def ensure_archive_column(engine):
    """Additive, repeatable migration; preserve approval status and financial totals."""
    from sqlalchemy import inspect, text
    if 'archived_at' not in {column['name'] for column in inspect(engine).get_columns('subscription_requests')}:
        with engine.begin() as connection:
            connection.execute(text('ALTER TABLE subscription_requests ADD COLUMN archived_at DATETIME'))


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def paused_duration(user, now=None):
    now = utc(now or datetime.now(timezone.utc))
    start = utc(user.pro_paused_at)
    if user.tier != 'pro' or start is None:
        return timedelta(0)
    end = utc(user.aibain_expires_at)
    if end is None:
        end = now if user.aibain_enabled else start
    return max(timedelta(0), min(now, end) - start)


def effective_pro_expiry(user, now=None):
    expiry = utc(user.pro_expires_at)
    return expiry + paused_duration(user, now) if expiry else None


def resume_pro_clock(user, now=None):
    elapsed = paused_duration(user, now)
    if user.tier == 'pro' and user.pro_expires_at is not None:
        user.pro_expires_at = utc(user.pro_expires_at) + elapsed
    user.pro_paused_at = None
    user.pro_expiry_alert_stage = None
    return elapsed


def lifecycle_summary(user, now=None):
    now = utc(now or datetime.now(timezone.utc))
    base_expiry = effective_pro_expiry(user, now)
    base_expired = user.status == 'expired' or user.is_pro_expired
    ai_active = user.is_aibain_active or user.is_kongming_active
    ai_dates = [utc(value) for value in (user.aibain_expires_at, user.kongming_expires_at) if value]
    ai_expired = bool(ai_dates) and not ai_active
    dates = []
    if user.tier == 'pro' and not user.is_pro_paused and base_expiry:
        dates.append(base_expiry)
    if ai_active:
        dates.extend(value for value in ai_dates if value > now)
    next_expiry = min(dates) if dates else None
    if user.is_admin:
        state, label = 'admin', '관리자 · 전체 이용'
    elif user.status in ('suspended', 'rejected'):
        state, label = 'blocked', '이용 정지 · 가입 거절'
    elif base_expired or ai_expired:
        state = 'expired'
        label = '전체 구독 만료' if base_expired and ai_expired else '기본 구독 만료' if base_expired else 'AI·제갈공명 재구독 필요'
    elif next_expiry and next_expiry <= now + timedelta(days=3):
        state, label = 'expiring', '3일 이내 만료 예정'
    elif (user.status == 'approved' and user.tier in ('pro', 'premium')) or ai_active:
        state, label = 'active', '이용 중'
    else:
        state, label = 'none', '구독 미신청'
    return {'state': state, 'label': label, 'base_expired': base_expired,
            'ai_expired': ai_expired, 'next_expiry': next_expiry.isoformat() if next_expiry else None}
