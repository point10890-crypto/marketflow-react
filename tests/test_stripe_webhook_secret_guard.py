"""Stripe 웹훅은 시크릿이 비어 있으면 어떤 요청도 받지 않는다."""
import hashlib
import hmac
import json
import time

from app import create_app
from app.models import db
from app.models.user import User
import app.routes.stripe_routes as stripe_routes


def _app():
    return create_app({
        'TESTING': True,
        'SECRET_KEY': 'stripe-guard-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })


def _signed(payload: bytes, secret: str) -> str:
    ts = int(time.time())
    digest = hmac.new(secret.encode(), f'{ts}.'.encode() + payload, hashlib.sha256).hexdigest()
    return f't={ts},v1={digest}'


def _checkout_event(user_id: int) -> bytes:
    return json.dumps({
        'id': 'evt_test_1',
        'object': 'event',
        'type': 'checkout.session.completed',
        'data': {'object': {'id': 'cs_test_1', 'object': 'checkout.session',
                            'metadata': {'user_id': str(user_id)}}},
    }).encode()


def _pending_user(app) -> int:
    with app.app_context():
        user = User(email='victim@example.com', name='대기회원', status='pending', tier=None, role='user')
        user.set_password('Pass1234!')
        db.session.add(user)
        db.session.commit()
        return user.id


def test_webhook_rejected_when_secret_empty(monkeypatch):
    monkeypatch.setattr(stripe_routes, 'STRIPE_WEBHOOK_SECRET', '')
    app = _app()
    user_id = _pending_user(app)
    payload = _checkout_event(user_id)

    res = app.test_client().post(
        '/api/stripe/webhook', data=payload,
        headers={'Stripe-Signature': _signed(payload, ''), 'Content-Type': 'application/json'},
    )

    assert res.status_code == 503
    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.tier is None
        assert user.status == 'pending'


def test_webhook_rejects_wrong_signature_when_secret_set(monkeypatch):
    monkeypatch.setattr(stripe_routes, 'STRIPE_WEBHOOK_SECRET', 'whsec_test_value')
    app = _app()
    user_id = _pending_user(app)
    payload = _checkout_event(user_id)

    res = app.test_client().post(
        '/api/stripe/webhook', data=payload,
        headers={'Stripe-Signature': _signed(payload, ''), 'Content-Type': 'application/json'},
    )

    assert res.status_code == 400
    with app.app_context():
        assert db.session.get(User, user_id).tier is None
