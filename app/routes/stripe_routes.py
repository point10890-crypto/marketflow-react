"""Stripe payment routes"""

import os
import stripe
from flask import Blueprint, request, jsonify, current_app
from app.models import db
from app.models.user import User
from app.auth.decorators import login_required

stripe_bp = Blueprint('stripe', __name__)

# Stripe 설정 (키가 없으면 결제 기능 비활성화)
_stripe_key = os.getenv('STRIPE_SECRET_KEY', '')
if _stripe_key and _stripe_key.startswith('sk_'):
    stripe.api_key = _stripe_key
STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')
STRIPE_PRICE_ID = os.getenv('STRIPE_PRICE_ID', '')


@stripe_bp.route('/create-checkout', methods=['POST'])
@login_required
def create_checkout():
    user = request.current_user
    try:
        # Create or reuse Stripe customer
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.name,
                metadata={'user_id': str(user.id)},
            )
            user.stripe_customer_id = customer.id
            db.session.commit()

        session = stripe.checkout.Session.create(
            customer=user.stripe_customer_id,
            line_items=[{'price': STRIPE_PRICE_ID, 'quantity': 1}],
            mode='subscription',
            success_url=os.getenv('NEXTAUTH_URL', os.getenv('SITE_URL', '')) + '/dashboard?upgraded=1',
            cancel_url=os.getenv('NEXTAUTH_URL', os.getenv('SITE_URL', '')) + '/pricing',
            metadata={'user_id': str(user.id)},
        )
        return jsonify({'url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@stripe_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    sig = request.headers.get('Stripe-Signature', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError, Exception) as e:
        # 서버 로그에는 상세 에러, 클라이언트에는 일반 메시지만 (info disclosure 방지)
        current_app.logger.warning(f"[Stripe] Webhook verification failed: {e}")
        return jsonify({'error': 'Webhook verification failed'}), 400

    from datetime import datetime, timezone

    def _set_pro_from_subscription(user, subscription_id=None, period_end_unix=None):
        """Activate / extend pro from a Stripe subscription period_end."""
        user.tier = 'pro'
        if user.status != 'approved':
            user.status = 'approved'
            user.approved_at = datetime.now(timezone.utc)
        if period_end_unix:
            user.pro_expires_at = datetime.fromtimestamp(int(period_end_unix), tz=timezone.utc)
        elif not user.pro_expires_at or user.pro_expires_at < datetime.now(timezone.utc):
            # Fallback: if Stripe didn't send period_end, give 31 days so the
            # user isn't immediately marked expired by the hourly checker.
            from datetime import timedelta
            user.pro_expires_at = datetime.now(timezone.utc) + timedelta(days=31)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        if user_id:
            user = db.session.get(User, int(user_id))
            if user:
                if not user.stripe_customer_id:
                    user.stripe_customer_id = session.get('customer')
                # Try to fetch the subscription to get the real period_end.
                period_end = None
                sub_id = session.get('subscription')
                if sub_id:
                    try:
                        sub = stripe.Subscription.retrieve(sub_id)
                        period_end = sub.get('current_period_end')
                    except Exception as e:
                        current_app.logger.warning(f"[Stripe] sub.retrieve failed: {e}")
                _set_pro_from_subscription(user, sub_id, period_end)
                db.session.commit()

    elif event['type'] in ('invoice.payment_succeeded', 'customer.subscription.updated'):
        # Recurring renewal — extend pro_expires_at to the new period_end.
        obj = event['data']['object']
        customer_id = obj.get('customer')
        if customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()
            if user:
                period_end = obj.get('current_period_end') or (obj.get('lines', {}).get('data', [{}])[0].get('period', {}).get('end'))
                _set_pro_from_subscription(user, obj.get('subscription'), period_end)
                db.session.commit()

    elif event['type'] == 'customer.subscription.deleted':
        sub = event['data']['object']
        customer_id = sub.get('customer')
        if customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()
            if user:
                # 구독 취소 = '만료' (재구독 유도 상태). 'suspended' 는 수동 정지
                # 전용 — expired 는 로그인 후 /plan-select?resubscribe=1 로 안내된다.
                user.status = 'expired'
                user.pro_expiry_alert_stage = 'expired'
                db.session.commit()

    return jsonify({'status': 'ok'})


@stripe_bp.route('/portal', methods=['POST'])
@login_required
def portal():
    user = request.current_user
    if not user.stripe_customer_id:
        return jsonify({'error': 'No subscription found'}), 404
    try:
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=os.getenv('NEXTAUTH_URL', os.getenv('SITE_URL', '')) + '/dashboard',
        )
        return jsonify({'url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
