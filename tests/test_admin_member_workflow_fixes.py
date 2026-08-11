"""2026-08-11 회원/구독 워크플로우 P0 버그 회귀 테스트.

1. revoke: AI Brain pause 중인 Pro 회원도 revoke 즉시 만료돼야 한다.
2. set_tier/bulk_tier: 만료된 Pro 에게 'pro' 재부여 시 만료일이 갱신돼야 한다.
3. enable_aibain: 만료된 Pro 베이스에 AI Brain 활성화 시 Pro 만료가 우회되면 안 된다.
4. 비밀번호 변경/리셋 후 기존 토큰은 무효화돼야 한다.
"""

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from app import create_app
from app.auth.decorators import TOKEN_EXPIRY, generate_token
from app.models import db
from app.models.user import User


def _backdated_token(user_id: int, secret: str, issued_ago_sec: int = 120) -> str:
    """issued_ago_sec 초 전에 발급된 것과 동일한 토큰 생성 (grace 우회 검증용)."""
    expiry = int(time.time()) - issued_ago_sec + TOKEN_EXPIRY
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}:{sig}"


def _app():
    return create_app({
        'TESTING': True,
        'SECRET_KEY': 'member-workflow-fix-test',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })


def _make_admin():
    admin = User(email='admin@example.com', name='Admin', role='admin',
                 status='approved', tier='premium')
    admin.set_password('AdminPass1')
    db.session.add(admin)
    db.session.commit()
    return admin


def _auth(user_id: int) -> dict:
    return {'Authorization': f'Bearer {generate_token(user_id)}'}


def test_revoke_expires_paused_pro_user():
    """AI Brain 활성(pro_paused_at 세팅) 상태에서 revoke 하면 즉시 만료돼야 한다."""
    app = _app()
    with app.app_context():
        admin = _make_admin()
        user = User(email='paused@example.com', name='Paused', status='approved',
                    tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
                    aibain_enabled=True,
                    aibain_expires_at=datetime.now(timezone.utc) + timedelta(days=10),
                    pro_paused_at=datetime.now(timezone.utc) - timedelta(days=1))
        user.set_password('UserPass1')
        db.session.add(user)
        db.session.commit()
        uid, aid = user.id, admin.id

        client = app.test_client()
        res = client.post(f'/api/admin/users/{uid}/revoke', headers=_auth(aid), json={})
        assert res.status_code == 200

        refreshed = db.session.get(User, uid)
        assert refreshed.pro_paused_at is None
        assert refreshed.is_pro_expired is True


def test_set_tier_pro_refreshes_expired_expiry():
    """만료된 Pro 회원에게 'Pro 부여' 시 만료일이 +30일로 갱신돼야 한다."""
    app = _app()
    with app.app_context():
        admin = _make_admin()
        user = User(email='expired@test.dev', name='Expired', status='approved',
                    tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) - timedelta(days=5))
        user.set_password('UserPass1')
        db.session.add(user)
        db.session.commit()
        uid, aid = user.id, admin.id

        client = app.test_client()
        res = client.put(f'/api/admin/users/{uid}/tier', headers=_auth(aid),
                         json={'tier': 'pro'})
        assert res.status_code == 200

        refreshed = db.session.get(User, uid)
        assert refreshed.is_pro_expired is False
        assert refreshed.pro_expires_at > datetime.utcnow() + timedelta(days=29)


def test_bulk_tier_pro_refreshes_expired_expiry():
    app = _app()
    with app.app_context():
        admin = _make_admin()
        user = User(email='bulk-expired@test.dev', name='BulkExpired', status='approved',
                    tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) - timedelta(days=5))
        user.set_password('UserPass1')
        db.session.add(user)
        db.session.commit()
        uid, aid = user.id, admin.id

        client = app.test_client()
        res = client.post('/api/admin/users/bulk-tier', headers=_auth(aid),
                          json={'user_ids': [uid], 'tier': 'pro'})
        assert res.status_code == 200

        refreshed = db.session.get(User, uid)
        assert refreshed.is_pro_expired is False


def test_enable_aibain_rejects_expired_pro_base():
    """만료된 Pro 베이스에 AI Brain 활성화가 Pro 만료를 우회하면 안 된다."""
    app = _app()
    with app.app_context():
        admin = _make_admin()
        user = User(email='exp-base@test.dev', name='ExpBase', status='approved',
                    tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) - timedelta(days=3))
        user.set_password('UserPass1')
        db.session.add(user)
        db.session.commit()
        uid, aid = user.id, admin.id

        client = app.test_client()
        res = client.post(f'/api/admin/users/{uid}/aibain/enable', headers=_auth(aid),
                          json={'days': 30})
        assert res.status_code == 400

        refreshed = db.session.get(User, uid)
        assert refreshed.pro_paused_at is None
        assert refreshed.is_pro_expired is True


def test_password_change_invalidates_old_tokens():
    """비밀번호 변경 후 이전 토큰으로 API 접근이 거부돼야 한다."""
    app = _app()
    with app.app_context():
        user = User(email='rotate@test.dev', name='Rotate', status='approved', tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
        user.set_password('OldPass12')
        db.session.add(user)
        db.session.commit()
        # 비밀번호 설정 이후 발급됐지만 충분히 과거인 토큰 (grace 5초 밖)
        user.password_changed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.commit()
        uid = user.id
        old_token = _backdated_token(uid, 'member-workflow-fix-test')

        client = app.test_client()
        headers = {'Authorization': f'Bearer {old_token}'}
        assert client.get('/api/auth/me', headers=headers).status_code == 200

        res = client.put('/api/auth/change-password', headers=headers, json={
            'current_password': 'OldPass12',
            'new_password': 'NewPass34',
        })
        assert res.status_code == 200
        new_token = res.get_json().get('token')
        assert new_token, 'change-password must return a fresh token'

        # 이전 토큰 → 401, 새 토큰 → 200
        assert client.get('/api/auth/me', headers=headers).status_code == 401
        assert client.get(
            '/api/auth/me', headers={'Authorization': f'Bearer {new_token}'}
        ).status_code == 200


def test_admin_reset_password_invalidates_user_tokens():
    app = _app()
    with app.app_context():
        admin = _make_admin()
        user = User(email='reset-target@test.dev', name='Target', status='approved',
                    tier='pro',
                    pro_expires_at=datetime.now(timezone.utc) + timedelta(days=10))
        user.set_password('OldPass12')
        db.session.add(user)
        db.session.commit()
        user.password_changed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.commit()
        uid, aid = user.id, admin.id
        user_token = _backdated_token(uid, 'member-workflow-fix-test')

        client = app.test_client()
        user_headers = {'Authorization': f'Bearer {user_token}'}
        assert client.get('/api/auth/me', headers=user_headers).status_code == 200

        res = client.put(f'/api/admin/users/{uid}/reset-password', headers=_auth(aid),
                         json={'password': 'AdminSet99', 'note': 'test reset'})
        assert res.status_code == 200

        assert client.get('/api/auth/me', headers=user_headers).status_code == 401
