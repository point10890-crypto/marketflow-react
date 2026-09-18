# -*- coding: utf-8 -*-
"""수식 다이소 (3만원 균일가) 게시판 — 수식마켓과 같은 게시판 기능 + 가격 고정 (2026-09-18).

- 부팅 시드: 수식마켓 게시판이 있는 DB 에만 다이소 게시판을 멱등 생성한다.
- 글 생성/수정: 입력 가격과 무관하게 30,000 으로 고정된다.
- 구매 요청: 수식마켓과 동일하게 동작하고, 알림 문구는 게시판 이름을 쓴다.
- 활성 AI Brain 구독자와 관리자만 접근할 수 있다.
"""
from __future__ import annotations

import pytest

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Post, PurchaseRequest
from app.models.user import User


class _TrapThread:
    spawned = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.__class__.spawned.append(self)

    def start(self):
        return None


def _app():
    return create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-daiso-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })


def test_seed_creates_daiso_only_when_formula_market_exists():
    from app.routes.community import ensure_formula_daiso_board

    app = _app()
    with app.app_context():
        # 빈 DB (테스트/신규) → 아무것도 만들지 않는다
        assert ensure_formula_daiso_board() is False
        assert Board.query.filter_by(slug='formula-daiso').first() is None

        db.session.add(Board(slug='formula-market', name='수식/조건검색식 마켓',
                             min_tier='pro', write_tier='admin', sort_order=6))
        db.session.commit()

        assert ensure_formula_daiso_board() is True
        daiso = Board.query.filter_by(slug='formula-daiso').first()
        assert daiso is not None
        assert daiso.name == '수식 다이소 (3만원 균일가)'
        assert daiso.min_tier == 'pro' and daiso.write_tier == 'admin'
        assert daiso.sort_order == 7
        assert daiso.is_active is True

        # 두 번째 호출은 no-op
        assert ensure_formula_daiso_board() is False
        assert Board.query.filter_by(slug='formula-daiso').count() == 1


def test_create_app_seeds_daiso_on_existing_production_like_db(tmp_path):
    db_path = tmp_path / 'users.db'
    first = create_app({
        'TESTING': True, 'SECRET_KEY': 's',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with first.app_context():
        db.session.add(Board(slug='formula-market', name='수식/조건검색식 마켓', min_tier='pro', write_tier='admin'))
        db.session.commit()
        db.session.remove()

    second = create_app({
        'TESTING': True, 'SECRET_KEY': 's',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with second.app_context():
        assert Board.query.filter_by(slug='formula-daiso').count() == 1
        db.session.remove()


@pytest.fixture()
def daiso_env(monkeypatch):
    import app.routes.community as community_routes

    _TrapThread.spawned = []
    monkeypatch.setattr(community_routes.threading, 'Thread', _TrapThread)
    app = _app()
    with app.app_context():
        member = User(email='m@example.com', password_hash='x', name='회원', status='approved', tier=None, role='user', aibain_enabled=True)
        admin = User(email='a@example.com', password_hash='x', name='관리자', status='approved', tier='premium', role='admin')
        daiso = Board(slug='formula-daiso', name='수식 다이소 (3만원 균일가)', min_tier='pro', write_tier='admin')
        db.session.add_all([member, admin, daiso])
        db.session.commit()
        tokens = {'member': generate_token(member.id), 'admin': generate_token(admin.id)}
    return app, tokens


def test_daiso_post_price_is_forced_to_30000_on_create_and_update(daiso_env):
    app, tokens = daiso_env
    client = app.test_client()
    admin = {'Authorization': f"Bearer {tokens['admin']}"}

    created = client.post('/api/community/boards/formula-daiso/posts', json={
        'title': '거래량 급증 조건식', 'content': '<p>설명</p>', 'price': '99000', 'is_public': True,
    }, headers=admin)
    assert created.status_code == 201, created.get_json()
    post_id = created.get_json()['id']
    assert created.get_json()['price'] == '30000'

    # 가격을 비워도, 다른 값으로 바꿔도 고정가 유지
    updated = client.put(f'/api/community/posts/{post_id}', json={'price': ''}, headers=admin)
    assert updated.status_code == 200
    assert updated.get_json()['price'] == '30000'
    updated = client.put(f'/api/community/posts/{post_id}', json={'title': '제목 변경'}, headers=admin)
    assert updated.get_json()['price'] == '30000'


def test_daiso_board_shares_formula_market_purchase_workflow(daiso_env):
    from app.models.user import AdminNotification

    app, tokens = daiso_env
    client = app.test_client()
    admin = {'Authorization': f"Bearer {tokens['admin']}"}
    member = {'Authorization': f"Bearer {tokens['member']}"}

    created = client.post('/api/community/boards/formula-daiso/posts', json={
        'title': '균일가 수식', 'content': '<p>설명</p>', 'file_url': '/api/community/uploads/' + 'a' * 32 + '.txt',
        'file_name': 'formula.txt',
    }, headers=admin)
    post_id = created.get_json()['id']

    # 활성 AI Brain 회원은 읽을 수 있고, 파일 정보는 구매 승인 전 숨겨진다
    detail = client.get(f'/api/community/posts/{post_id}', headers=member)
    assert detail.status_code == 200
    body = detail.get_json()['post']
    assert body['price'] == '30000'
    assert body['purchase_status'] is None
    assert 'file_url' not in body

    purchase = client.post(f'/api/community/posts/{post_id}/purchase', json={'buyer_name': '홍길동'}, headers=member)
    assert purchase.status_code == 201, purchase.get_json()

    with app.app_context():
        pr = PurchaseRequest.query.filter_by(post_id=post_id).first()
        assert pr is not None and pr.status == 'pending'
        note = AdminNotification.query.order_by(AdminNotification.id.desc()).first()
        assert note is not None
        assert '수식 다이소' in note.title
        assert '30000' in note.message

    mine = client.get('/api/community/purchases/mine', headers=member)
    assert mine.status_code == 200
    assert mine.get_json()['total'] == 1

    listed = client.get('/api/community/boards', headers=member)
    daiso_row = next(b for b in listed.get_json() if b['slug'] == 'formula-daiso')
    assert daiso_row['can_read'] is True
    assert daiso_row['post_count'] == 1


@pytest.mark.parametrize('tier,enabled,expired', [
    (None, False, False), ('pro', False, False), ('premium', False, False),
    ('pro', True, True), ('premium', False, True),
])
def test_daiso_requires_active_aibrain_across_access_paths(daiso_env, tier, enabled, expired):
    from datetime import datetime, timedelta

    app, tokens = daiso_env
    with app.app_context():
        member = User.query.filter_by(email='m@example.com').one()
        member.tier = tier
        member.aibain_enabled = enabled
        member.aibain_expires_at = datetime.utcnow() - timedelta(days=1) if expired else None
        board = Board.query.filter_by(slug='formula-daiso').one()
        board.write_tier = 'none'  # legacy/admin tier settings must not bypass membership
        post = Post(board_id=board.id, author_id=member.id, title='전용 수식', content='비공개 설명',
                    file_url='/api/community/uploads/' + 'a' * 32 + '.txt', file_name='formula.txt')
        db.session.add(post)
        db.session.flush()
        db.session.add(PurchaseRequest(post_id=post.id, user_id=member.id, buyer_name='회원', status='approved'))
        db.session.commit()
        post_id = post.id
    client = app.test_client()
    headers = {'Authorization': f"Bearer {tokens['member']}"}
    row = next(b for b in client.get('/api/community/boards', headers=headers).get_json()
               if b['slug'] == 'formula-daiso')
    assert row['min_tier'] == 'aibain'
    assert row['can_read'] is False
    assert row['post_count'] == 0 and row['latest_post_title'] is None
    for path in [f'/posts/{post_id}', '/boards/formula-daiso/posts',
                 f'/posts/{post_id}/comments', f'/posts/{post_id}/download']:
        response = client.get('/api/community' + path, headers=headers)
        assert response.status_code == 403, (path, response.get_json())
        assert response.get_json()['code'] == 'aibain_required'
    for path, body in [(f'/posts/{post_id}/purchase', {'buyer_name': '회원'}),
                       (f'/posts/{post_id}/comments', {'content': '댓글'}),
                       ('/boards/formula-daiso/posts', {'title': '새 글', 'content': '내용'})]:
        assert client.post('/api/community' + path, json=body, headers=headers).status_code == 403
    assert client.put(f'/api/community/posts/{post_id}', json={'title': '변경'}, headers=headers).status_code == 403
    assert client.delete(f'/api/community/posts/{post_id}', headers=headers).status_code == 403
    assert client.get('/api/community/search?q=전용', headers=headers).get_json()['total'] == 0
    summary = client.get('/api/community/summary', headers=headers).get_json()
    assert summary['total_posts'] == 0 and summary['formula_count'] == 0
    assert client.get('/api/public/community/boards/formula-daiso/posts').status_code == 404


def test_active_aibrain_search_and_approved_download(daiso_env, monkeypatch, tmp_path):
    from datetime import datetime, timedelta
    import app.routes.community as routes

    app, tokens = daiso_env
    filename = 'b' * 32 + '.txt'
    (tmp_path / filename).write_text('formula', encoding='utf-8')
    monkeypatch.setattr(routes, 'UPLOAD_DIR', str(tmp_path))
    with app.app_context():
        member = User.query.filter_by(email='m@example.com').one()
        member.aibain_expires_at = datetime.utcnow() + timedelta(days=1)
        board = Board.query.filter_by(slug='formula-daiso').one()
        post = Post(board_id=board.id, author_id=member.id, title='전용 수식', content='설명',
                    file_url='/api/community/uploads/' + filename, file_name='formula.txt')
        db.session.add(post)
        db.session.flush()
        db.session.add(PurchaseRequest(post_id=post.id, user_id=member.id, buyer_name='회원', status='approved'))
        db.session.commit()
        post_id = post.id
    headers = {'Authorization': f"Bearer {tokens['member']}"}
    client = app.test_client()
    assert client.get('/api/community/search?q=전용', headers=headers).get_json()['total'] == 1
    assert client.get(f'/api/community/posts/{post_id}/download', headers=headers).status_code == 200


def test_daiso_cannot_be_published_by_public_board_configuration(daiso_env, monkeypatch):
    app, tokens = daiso_env
    monkeypatch.setenv('PUBLIC_COMMUNITY_BOARDS', 'notice,formula-daiso')
    client = app.test_client()
    created = client.post('/api/community/boards/formula-daiso/posts', json={
        'title': '전용 수식', 'content': '설명', 'is_public': True,
    }, headers={'Authorization': f"Bearer {tokens['admin']}"})
    assert created.status_code == 201
    assert client.get('/api/public/community/boards').get_json()['boards'] == []
    assert client.get('/api/public/community/boards/formula-daiso/posts').status_code == 404
    assert client.get(f"/api/public/community/posts/{created.get_json()['id']}").status_code == 404


def test_formula_market_price_stays_free_form(monkeypatch):
    """회귀: 수식마켓은 여전히 자유 가격이다."""
    import app.routes.community as community_routes

    monkeypatch.setattr(community_routes.threading, 'Thread', _TrapThread)
    app = _app()
    with app.app_context():
        admin = User(email='a2@example.com', password_hash='x', name='관리자', status='approved', tier='premium', role='admin')
        db.session.add_all([admin, Board(slug='formula-market', name='수식/조건검색식 마켓', min_tier='pro', write_tier='admin')])
        db.session.commit()
        token = generate_token(admin.id)
    client = app.test_client()
    created = client.post('/api/community/boards/formula-market/posts', json={
        'title': 'x', 'content': '<p>y</p>', 'price': '55000',
    }, headers={'Authorization': f'Bearer {token}'})
    assert created.get_json()['price'] == '55000'
