import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Post, PurchaseRequest
from app.models.user import AdminNotification, User


class _TrapThread:
    """Thread double that prevents any outbound Telegram worker from running."""

    spawned = []

    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon
        self.__class__.spawned.append(self)

    def start(self):
        return None


def test_no_tier_purchase_request_admin_approval_and_download(tmp_path, monkeypatch):
    import app.routes.community as community_routes

    monkeypatch.setattr(community_routes, 'UPLOAD_DIR', str(tmp_path))
    _TrapThread.spawned = []
    monkeypatch.setattr(community_routes.threading, 'Thread', _TrapThread)
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-purchase-workflow-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    stored_name = f'{"a" * 32}.txt'
    Path(tmp_path, stored_name).write_text('verified formula', encoding='utf-8')

    with app.app_context():
        member = User(
            email='buyer-no-tier@example.com', password_hash='unused',
            name='No Tier Buyer', status='approved', tier=None, role='user',
        )
        admin = User(
            email='purchase-admin@example.com', password_hash='unused',
            name='Purchase Admin', status='approved', tier='premium', role='admin',
        )
        board = Board(
            slug='formula-market', name='수식/조건검색식 마켓',
            min_tier='pro', write_tier='admin', is_active=True,
        )
        db.session.add_all([member, admin, board])
        db.session.flush()
        post = Post(
            board_id=board.id, author_id=admin.id,
            title='거래량 돌파 조건식', content='조건식 설명', price='30000',
            file_url=f'/api/community/uploads/{stored_name}',
            file_name='volume-breakout.txt',
        )
        db.session.add(post)
        db.session.commit()
        member_token = generate_token(member.id)
        admin_token = generate_token(admin.id)
        post_id = post.id

    client = app.test_client()
    member_headers = {'Authorization': f'Bearer {member_token}'}
    admin_headers = {'Authorization': f'Bearer {admin_token}'}

    created = client.post(
        f'/api/community/posts/{post_id}/purchase',
        json={'buyer_name': '홍길동'}, headers=member_headers,
    )
    assert created.status_code == 201
    purchase_id = created.get_json()['id']
    assert created.get_json()['status'] == 'pending'
    assert _TrapThread.spawned == []

    duplicate = client.post(
        f'/api/community/posts/{post_id}/purchase',
        json={'buyer_name': '홍길동'}, headers=member_headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()['status'] == 'pending'

    mine = client.get('/api/community/purchases/mine', headers=member_headers)
    assert mine.status_code == 200
    assert mine.get_json()['total'] == 1
    assert mine.get_json()['purchases'][0]['id'] == purchase_id

    pending_detail = client.get(f'/api/community/posts/{post_id}', headers=member_headers)
    assert pending_detail.status_code == 200
    assert pending_detail.get_json()['post']['purchase_status'] == 'pending'
    assert 'file_url' not in pending_detail.get_json()['post']
    assert client.get(
        f'/api/community/posts/{post_id}/download', headers=member_headers,
    ).status_code == 403

    admin_queue = client.get('/api/community/purchases?status=pending', headers=admin_headers)
    assert admin_queue.status_code == 200
    assert admin_queue.get_json()['purchases'][0]['id'] == purchase_id

    approved = client.put(
        f'/api/community/purchases/{purchase_id}',
        json={'status': 'approved'}, headers=admin_headers,
    )
    assert approved.status_code == 200
    assert approved.get_json()['status'] == 'approved'
    assert approved.get_json()['approved_at']

    approved_detail = client.get(f'/api/community/posts/{post_id}', headers=member_headers)
    assert approved_detail.status_code == 200
    assert approved_detail.get_json()['post']['purchase_status'] == 'approved'
    assert approved_detail.get_json()['post']['file_name'] == 'volume-breakout.txt'

    download = client.get(
        f'/api/community/posts/{post_id}/download', headers=member_headers,
    )
    assert download.status_code == 200
    assert download.data == b'verified formula'

    approved_mine = client.get(
        '/api/community/purchases/mine?status=approved', headers=member_headers,
    )
    assert approved_mine.status_code == 200
    assert approved_mine.get_json()['purchases'][0]['status'] == 'approved'


def test_purchase_rejects_non_formula_posts():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'non-formula-purchase-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        member = User(
            email='buyer@example.com', password_hash='unused',
            name='Buyer', status='approved', tier=None, role='user',
        )
        board = Board(slug='free-talk', name='자유게시판', min_tier='none')
        db.session.add_all([member, board])
        db.session.flush()
        post = Post(board_id=board.id, author_id=member.id, title='일반 글', content='본문')
        db.session.add(post)
        db.session.commit()
        token = generate_token(member.id)
        post_id = post.id

    response = app.test_client().post(
        f'/api/community/posts/{post_id}/purchase',
        json={'buyer_name': '구매자'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert response.status_code == 400


def test_existing_sqlite_database_gains_pending_purchase_uniqueness(tmp_path):
    db_path = tmp_path / 'legacy-users.db'
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE purchase_requests (
                id INTEGER PRIMARY KEY,
                post_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                buyer_name VARCHAR(100) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                created_at DATETIME,
                approved_at DATETIME
            )
        ''')

    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-purchase-legacy-index-secret',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    with app.app_context():
        member = User(
            email='legacy-buyer@example.com', password_hash='unused',
            name='Legacy Buyer', status='approved', tier=None, role='user',
        )
        admin = User(
            email='legacy-admin@example.com', password_hash='unused',
            name='Legacy Admin', status='approved', tier='premium', role='admin',
        )
        board = Board(
            slug='formula-market', name='수식/조건검색식 마켓',
            min_tier='none', write_tier='admin', is_active=True,
        )
        db.session.add_all([member, admin, board])
        db.session.flush()
        post = Post(
            board_id=board.id, author_id=admin.id,
            title='중복 방지 조건식', content='설명', price='10000',
        )
        db.session.add(post)
        db.session.flush()
        db.session.add(PurchaseRequest(
            post_id=post.id, user_id=member.id, buyer_name='첫 요청', status='pending',
        ))
        db.session.commit()

        db.session.add(PurchaseRequest(
            post_id=post.id, user_id=member.id, buyer_name='동시 요청', status='pending',
        ))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        assert PurchaseRequest.query.filter_by(
            post_id=post.id, user_id=member.id, status='pending',
        ).count() == 1


def test_purchase_race_returns_existing_request_without_duplicate_alerts(tmp_path, monkeypatch):
    import app.routes.community as community_routes

    db_path = tmp_path / 'race-users.db'
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-purchase-race-secret',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path.as_posix()}',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    with app.app_context():
        member = User(
            email='race-buyer@example.com', password_hash='unused',
            name='Race Buyer', status='approved', tier=None, role='user',
        )
        admin = User(
            email='race-admin@example.com', password_hash='unused',
            name='Race Admin', status='approved', tier='premium', role='admin',
        )
        board = Board(
            slug='formula-market', name='수식/조건검색식 마켓',
            min_tier='none', write_tier='admin', is_active=True,
        )
        db.session.add_all([member, admin, board])
        db.session.flush()
        post = Post(
            board_id=board.id, author_id=admin.id,
            title='경쟁 조건식', content='설명', price='20000',
        )
        db.session.add(post)
        db.session.commit()
        member_id = member.id
        post_id = post.id
        token = generate_token(member.id)
        session_class = type(db.session())

    original_add = session_class.add
    competitor_inserted = False

    def add_with_competing_purchase(session, instance, *args, **kwargs):
        nonlocal competitor_inserted
        if isinstance(instance, PurchaseRequest) and not competitor_inserted:
            competitor_inserted = True
            with db.engine.begin() as connection:
                connection.execute(PurchaseRequest.__table__.insert().values(
                    post_id=post_id,
                    user_id=member_id,
                    buyer_name='먼저 커밋된 요청',
                    status='pending',
                ))
        return original_add(session, instance, *args, **kwargs)

    monkeypatch.setattr(session_class, 'add', add_with_competing_purchase)
    telegram_messages = []
    monkeypatch.setattr(
        community_routes,
        '_notify_admin_telegram',
        lambda message: telegram_messages.append(message),
    )

    response = app.test_client().post(
        f'/api/community/posts/{post_id}/purchase',
        json={'buyer_name': '뒤늦은 요청'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 409
    assert response.get_json()['status'] == 'pending'
    assert telegram_messages == []
    with app.app_context():
        assert PurchaseRequest.query.filter_by(
            post_id=post_id, user_id=member_id, status='pending',
        ).count() == 1
        assert AdminNotification.query.filter_by(type='purchase_request').count() == 0
