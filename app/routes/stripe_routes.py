"""Stripe payment routes"""

import os
import stripe
from flask import Blueprint, request, jsonify
from app.models import db
from app.models.user import User
from app.auth.decorators import login_required

stripe_bp = Blueprint('stripe', __name__)

# Stripe 설정 (키가 없으면 결제 기능 비활성화)
_stripe_key = os.getenv('STRIPE_SECRET_KEY', '')
if _stripe_key and not _stripe_key.startswith('pk_'):
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
            success_url=os.getenv('NEXTAUTH_URL', 'http://localhost:4000') + '/dashboard?upgraded=1',
            cancel_url=os.getenv('NEXTAUTH_URL', 'http://localhost:4000') + '/pricing',
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
        return jsonify({'error': f'Webhook verification failed: {str(e)}'}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        if user_id:
            user = db.session.get(User, int(user_id))
            if user:
                user.tier = 'pro'
                if not user.stripe_customer_id:
                    user.stripe_customer_id = session.get('customer')
                db.session.commit()

    elif event['type'] == 'customer.subscription.deleted':
        sub = event['data']['object']
        customer_id = sub.get('customer')
        if customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()
            if user:
                user.tier = 'free'
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
            return_url=os.getenv('NEXTAUTH_URL', 'http://localhost:4000') + '/dashboard',
        )
        return jsonify({'url': session.url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
