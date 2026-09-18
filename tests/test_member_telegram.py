# -*- coding: utf-8 -*-
"""회원 본인 텔레그램 알림 — 연결 코드 / 폴러 매칭 / notify_member / 만료 스윕 연동.

네트워크는 전부 monkeypatch (requests.get/post) — 실제 텔레그램 호출 0.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User
from app.services import member_telegram
from app.services.pro_expiry import run_expiry_sweep


class _Resp:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload


@pytest.fixture()
def app(monkeypatch, tmp_path):
    monkeypatch.setenv('TELEGRAM_MEMBER_BOT_TOKEN', 'member-bot-token')
    monkeypatch.setenv('TELEGRAM_MEMBER_BOT_USERNAME', '@marketflow_member_bot')
    monkeypatch.delenv('MEMBER_TELEGRAM_LINK_ENABLED', raising=False)
    monkeypatch.setattr(member_telegram, 'OFFSET_PATH', str(tmp_path / 'telegram_member_offset.json'))
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'member-telegram-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        yield application
        db.session.remove()


def _mk_user(email, **kw):
    u = User(email=email, name=email.split('@')[0], status='approved', tier='pro', role='user')
    u.set_password('Pass1234!')
    for k, v in kw.items():
        setattr(u, k, v)
    db.session.add(u)
    db.session.commit()
    return u


def _auth(user):
    return {'Authorization': f'Bearer {generate_token(user.id)}'}


def _capture_posts(monkeypatch):
    sent = []

    def fake_post(url, json=None, timeout=None, **kw):
        sent.append({'url': url, 'body': json})
        return _Resp(200, {'ok': True})

    monkeypatch.setattr(member_telegram.requests, 'post', fake_post)
    return sent


# ── 연결 코드 발급 / 해제 ──────────────────────────────────────────────────────

def test_link_code_endpoint_issues_code_and_deep_link(app):
    user = _mk_user('member@example.com')
    client = app.test_client()

    res = client.post('/api/auth/telegram/link-code', headers=_auth(user))
    assert res.status_code == 200
    body = res.get_json()
    code = body['code']
    assert len(code) == member_telegram.LINK_CODE_LENGTH
    assert body['deep_link'] == f'https://t.me/marketflow_member_bot?start={code}'
    assert body['bot_username'] == 'marketflow_member_bot'
    assert body['telegram_linked'] is False
    assert body['ttl_minutes'] == 30

    db.session.refresh(user)
    assert user.telegram_link_code == code
    remaining = user.telegram_link_code_expires_at - datetime.utcnow()
    assert timedelta(minutes=28) < remaining <= timedelta(minutes=30)

    # /me 는 연결 여부만 노출 — chat_id 는 절대 내려가지 않는다
    me = client.get('/api/auth/me', headers=_auth(user)).get_json()['user']
    assert me['telegram_linked'] is False
    assert 'telegram_chat_id' not in me
    assert 'telegram_link_code' not in me


def test_link_code_endpoint_reissues_new_code(app):
    user = _mk_user('again@example.com')
    client = app.test_client()
    first = client.post('/api/auth/telegram/link-code', headers=_auth(user)).get_json()['code']
    second = client.post('/api/auth/telegram/link-code', headers=_auth(user)).get_json()['code']
    assert first != second
    db.session.refresh(user)
    assert user.telegram_link_code == second


def test_link_code_endpoint_503_when_bot_unconfigured(app, monkeypatch):
    monkeypatch.delenv('TELEGRAM_MEMBER_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    user = _mk_user('nobot@example.com')
    res = app.test_client().post('/api/auth/telegram/link-code', headers=_auth(user))
    assert res.status_code == 503


def test_link_code_requires_login(app):
    res = app.test_client().post('/api/auth/telegram/link-code')
    assert res.status_code == 401


def test_unlink_endpoint_clears_chat_id(app):
    user = _mk_user('linked@example.com', telegram_chat_id='12345',
                    telegram_linked_at=datetime.now(timezone.utc))
    client = app.test_client()
    res = client.post('/api/auth/telegram/unlink', headers=_auth(user))
    assert res.status_code == 200
    assert res.get_json()['user']['telegram_linked'] is False
    db.session.refresh(user)
    assert user.telegram_chat_id is None
    assert user.telegram_linked_at is None


def test_link_enabled_env_gate(monkeypatch):
    monkeypatch.setenv('TELEGRAM_MEMBER_BOT_TOKEN', 't')
    monkeypatch.delenv('MEMBER_TELEGRAM_LINK_ENABLED', raising=False)
    assert member_telegram.link_enabled() is True
    monkeypatch.setenv('MEMBER_TELEGRAM_LINK_ENABLED', '0')
    assert member_telegram.link_enabled() is False
    monkeypatch.setenv('MEMBER_TELEGRAM_LINK_ENABLED', '1')
    monkeypatch.delenv('TELEGRAM_MEMBER_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    assert member_telegram.link_enabled() is False  # 토큰 없으면 켜도 무의미
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', 'fallback')
    assert member_telegram.bot_token() == 'fallback'


# ── 폴러 (getUpdates) ─────────────────────────────────────────────────────────

def test_poller_matches_start_code_persists_offset_and_replies(app, monkeypatch):
    user = _mk_user('poll@example.com')
    info = member_telegram.issue_link_code(user)
    db.session.commit()
    code = info['code']

    sent = _capture_posts(monkeypatch)
    calls = []
    updates = [
        {'update_id': 100, 'message': {'chat': {'id': 987654}, 'text': f'/start {code.lower()}'}},
        {'update_id': 101, 'message': {'chat': {'id': 555}, 'text': '/start NOPE1234'}},
        {'update_id': 102, 'message': {'chat': {'id': 1}, 'text': 'hello there'}},
        {'update_id': 103, 'message': {'chat': {'id': 2}, 'text': '/start'}},
    ]

    def fake_get(url, params=None, timeout=None, **kw):
        calls.append(params)
        return _Resp(200, {'ok': True, 'result': updates if len(calls) == 1 else []})

    monkeypatch.setattr(member_telegram.requests, 'get', fake_get)

    result = member_telegram.poll_link_updates()
    assert result == {'updates': 4, 'linked': 1, 'offset': 104, 'skipped': False}
    assert calls[0]['offset'] == 0

    db.session.refresh(user)
    assert user.telegram_chat_id == '987654'
    assert user.telegram_link_code is None
    assert user.telegram_link_code_expires_at is None
    assert user.telegram_linked_at is not None

    by_chat = {str(m['body']['chat_id']): m['body']['text'] for m in sent}
    assert '연결 완료' in by_chat['987654']
    assert '유효하지 않거나 만료' in by_chat['555']
    assert '2' in by_chat                       # 코드 없는 /start → 안내
    assert '1' not in by_chat                   # 일반 메시지는 무시

    with open(member_telegram.OFFSET_PATH, encoding='utf-8') as f:
        assert json.load(f)['offset'] == 104

    # 두 번째 폴링은 저장된 offset 부터
    result2 = member_telegram.poll_link_updates()
    assert result2['updates'] == 0 and result2['offset'] == 104
    assert calls[1]['offset'] == 104


def test_poller_rejects_expired_code(app, monkeypatch):
    user = _mk_user('late@example.com')
    info = member_telegram.issue_link_code(
        user, now=datetime.now(timezone.utc) - timedelta(minutes=31),
    )
    db.session.commit()
    sent = _capture_posts(monkeypatch)
    monkeypatch.setattr(member_telegram.requests, 'get', lambda *a, **k: _Resp(200, {
        'ok': True,
        'result': [{'update_id': 7, 'message': {'chat': {'id': 42}, 'text': f"/start {info['code']}"}}],
    }))
    result = member_telegram.poll_link_updates()
    assert result['linked'] == 0
    db.session.refresh(user)
    assert user.telegram_chat_id is None
    assert sent and '만료' in sent[0]['body']['text']


def test_poller_survives_network_errors(app, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError('offline')

    monkeypatch.setattr(member_telegram.requests, 'get', boom)
    result = member_telegram.poll_link_updates()
    assert result == {'updates': 0, 'linked': 0, 'offset': 0, 'skipped': False}

    monkeypatch.setattr(member_telegram.requests, 'get', lambda *a, **k: _Resp(502, {}, 'bad gateway'))
    assert member_telegram.poll_link_updates()['updates'] == 0


def test_poller_skips_when_unconfigured(app, monkeypatch):
    monkeypatch.delenv('TELEGRAM_MEMBER_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    called = []
    monkeypatch.setattr(member_telegram.requests, 'get', lambda *a, **k: called.append(1))
    assert member_telegram.poll_link_updates()['skipped'] is True
    assert called == []


def test_parse_start_code():
    assert member_telegram.parse_start_code('/start abcd2345') == 'ABCD2345'
    assert member_telegram.parse_start_code('/start@marketflow_member_bot XYZ') == 'XYZ'
    assert member_telegram.parse_start_code('/start') == ''
    assert member_telegram.parse_start_code('hello') is None
    assert member_telegram.parse_start_code(None) is None


# ── notify_member ──────────────────────────────────────────────────────────────

def test_notify_member_noop_when_unlinked(app, monkeypatch):
    sent = _capture_posts(monkeypatch)
    user = _mk_user('nolink@example.com')
    assert member_telegram.notify_member(user, '안녕') is False
    assert sent == []
    assert member_telegram.notify_member(None, '안녕') is False


def test_notify_member_sends_to_linked_chat(app, monkeypatch):
    sent = _capture_posts(monkeypatch)
    user = _mk_user('yeslink@example.com', telegram_chat_id='777')
    assert member_telegram.notify_member(user, '<b>승인</b>') is True
    assert len(sent) == 1
    assert sent[0]['url'].endswith('/botmember-bot-token/sendMessage')
    assert sent[0]['body']['chat_id'] == '777'
    assert sent[0]['body']['text'] == '<b>승인</b>'


def test_notify_member_swallows_http_failure(app, monkeypatch):
    monkeypatch.setattr(member_telegram.requests, 'post', lambda *a, **k: _Resp(403, {'ok': False}, 'forbidden'))
    user = _mk_user('blocked@example.com', telegram_chat_id='1')
    assert member_telegram.notify_member(user, 'x') is False

    def boom(*a, **k):
        raise TimeoutError('slow')

    monkeypatch.setattr(member_telegram.requests, 'post', boom)
    assert member_telegram.notify_member(user, 'x') is False


# ── 승인/거절 시 본인 알림 ─────────────────────────────────────────────────────

def test_admin_approve_notifies_linked_member(app, monkeypatch):
    from app.models.user import SubscriptionRequest

    sent = _capture_posts(monkeypatch)
    admin = _mk_user('admin@example.com', role='admin', tier='premium')
    member = _mk_user('buyer@example.com', status='pending', tier=None, telegram_chat_id='4242')
    req = SubscriptionRequest(user_id=member.id, request_type='upgrade', from_tier='none', to_tier='pro')
    db.session.add(req)
    db.session.commit()

    res = app.test_client().put(f'/api/admin/subscriptions/{req.id}/approve', headers=_auth(admin))
    assert res.status_code == 200
    assert len(sent) == 1
    body = sent[0]['body']
    assert body['chat_id'] == '4242'
    assert '승인되었습니다' in body['text']
    assert '만료일' in body['text']


def test_admin_reject_and_tier_grant_notify_linked_member(app, monkeypatch):
    from app.models.user import SubscriptionRequest

    sent = _capture_posts(monkeypatch)
    admin = _mk_user('admin2@example.com', role='admin', tier='premium')
    member = _mk_user('buyer2@example.com', status='pending', tier=None, telegram_chat_id='99')
    req = SubscriptionRequest(user_id=member.id, request_type='upgrade', from_tier='none', to_tier='pro')
    db.session.add(req)
    db.session.commit()
    client = app.test_client()

    res = client.put(f'/api/admin/subscriptions/{req.id}/reject', json={'note': '입금 미확인'}, headers=_auth(admin))
    assert res.status_code == 200
    assert '반려' in sent[-1]['body']['text'] and '입금 미확인' in sent[-1]['body']['text']

    res = client.put(f'/api/admin/users/{member.id}/tier', json={'tier': 'pro'}, headers=_auth(admin))
    assert res.status_code == 200
    assert '승인되었습니다' in sent[-1]['body']['text']
    assert len(sent) == 2


def test_admin_approve_unlinked_member_sends_nothing(app, monkeypatch):
    from app.models.user import SubscriptionRequest

    sent = _capture_posts(monkeypatch)
    admin = _mk_user('admin3@example.com', role='admin', tier='premium')
    member = _mk_user('quiet@example.com', status='pending', tier=None)
    req = SubscriptionRequest(user_id=member.id, request_type='upgrade', from_tier='none', to_tier='pro')
    db.session.add(req)
    db.session.commit()
    res = app.test_client().put(f'/api/admin/subscriptions/{req.id}/approve', headers=_auth(admin))
    assert res.status_code == 200
    assert sent == []


# ── 만료 스윕 연동 ─────────────────────────────────────────────────────────────

def test_expiry_sweep_notifies_linked_members_only(app, monkeypatch):
    sent = _capture_posts(monkeypatch)
    now = datetime.now(timezone.utc)
    linked_d3 = _mk_user('d3@example.com', pro_expires_at=now + timedelta(days=2), telegram_chat_id='300')
    linked_d1 = _mk_user('d1@example.com', pro_expires_at=now + timedelta(hours=12), telegram_chat_id='100')
    linked_gone = _mk_user('gone@example.com', pro_expires_at=now - timedelta(days=1), telegram_chat_id='0')
    _mk_user('silent@example.com', pro_expires_at=now + timedelta(days=2))  # 미연결

    admin_calls = []
    result = run_expiry_sweep(notify=lambda user, stage, when: admin_calls.append((user.email, stage)))
    assert result == {'expired': 1, 'd1': 1, 'd3': 2}
    assert len(admin_calls) == 4          # 관리자 알림은 기존대로 전원

    by_chat = {m['body']['chat_id']: m['body']['text'] for m in sent}
    assert set(by_chat) == {'300', '100', '0'}
    assert '3일 뒤' in by_chat['300']
    assert '내일' in by_chat['100']
    assert '만료되었습니다' in by_chat['0']

    # stage 가 기록됐으니 재실행 시 중복 발송 없음
    sent.clear()
    run_expiry_sweep(notify=lambda *a: None)
    assert sent == []
    for u in (linked_d3, linked_d1, linked_gone):
        db.session.refresh(u)
    assert linked_gone.status == 'expired'


def test_expiry_sweep_survives_member_notify_failure(app, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('telegram down')

    monkeypatch.setattr(member_telegram, 'notify_member', boom)
    u = _mk_user('robust@example.com', pro_expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                 telegram_chat_id='5')
    result = run_expiry_sweep(notify=lambda *a: None)
    assert result['expired'] == 1
    db.session.refresh(u)
    assert u.status == 'expired'


def test_startup_migration_adds_telegram_columns_and_funnel_table(tmp_path, monkeypatch):
    """기존 users.db (텔레그램 컬럼 없음) 가 부팅 시 데이터 손실 없이 컬럼을 얻는다."""
    import sqlite3

    monkeypatch.delenv('TELEGRAM_MEMBER_BOT_TOKEN', raising=False)
    db_path = tmp_path / 'legacy-users.db'
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(100) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'user',
            tier VARCHAR(20),
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            pro_expires_at DATETIME,
            stripe_customer_id VARCHAR(255),
            created_at DATETIME,
            approved_at DATETIME,
            approved_by INTEGER,
            last_login_at DATETIME,
            pro_expiry_alert_stage VARCHAR(10),
            requested_tier VARCHAR(20),
            aibain_enabled BOOLEAN NOT NULL DEFAULT 0,
            aibain_expires_at DATETIME,
            aibain_alert_stage VARCHAR(10),
            pro_paused_at DATETIME,
            password_changed_at DATETIME
        )
    """)
    conn.execute("""
        CREATE TABLE subscription_requests (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            request_type VARCHAR(50) NOT NULL,
            from_tier VARCHAR(20) NOT NULL,
            to_tier VARCHAR(20) NOT NULL,
            status VARCHAR(20),
            payment_id VARCHAR(255),
            admin_note TEXT,
            depositor_name VARCHAR(100),
            amount VARCHAR(50),
            created_at DATETIME,
            processed_at DATETIME,
            processed_by INTEGER
        )
    """)
    conn.execute(
        "INSERT INTO users (email, password_hash, name, role, tier, status) "
        "VALUES ('old@example.com', 'x', '기존회원', 'user', 'pro', 'approved')"
    )
    conn.commit()
    conn.close()

    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'migration-test-secret',
        'SQLALCHEMY_DATABASE_URI': f"sqlite:///{db_path.as_posix()}",
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    conn = sqlite3.connect(db_path)
    user_cols = {row[1] for row in conn.execute('PRAGMA table_info(users)').fetchall()}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    row = conn.execute("SELECT email, telegram_chat_id FROM users WHERE email='old@example.com'").fetchone()
    conn.close()

    assert {'telegram_chat_id', 'telegram_link_code', 'telegram_link_code_expires_at', 'telegram_linked_at'} <= user_cols
    assert 'funnel_events' in tables
    assert row == ('old@example.com', None)

    with application.app_context():
        legacy = User.query.filter_by(email='old@example.com').first()
        assert legacy.to_dict()['telegram_linked'] is False
        db.session.remove()


def test_build_messages_are_korean_and_contain_links():
    class _U:
        name = '홍길동'
        tier = 'pro'
        pro_expires_at = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)
        is_aibain_active = False
        aibain_expires_at = None

    approval = member_telegram.build_approval_message(_U(), summary='none → pro')
    assert '홍길동' in approval and 'Pro' in approval and '2026-10-03 09:00 (KST)' in approval
    reject = member_telegram.build_reject_message(_U(), note='입금 확인 불가')
    assert '반려' in reject and '입금 확인 불가' in reject
    for stage in ('d3', 'd1', 'expired'):
        msg = member_telegram.build_member_expiry_message(stage, '2026-10-03T00:00:00+00:00')
        assert 'plan-select' in msg and '(KST)' in msg
