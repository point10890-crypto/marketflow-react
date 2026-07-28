from pathlib import Path

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Post
from app.models.user import User


def test_no_tier_purchase_request_admin_approval_and_download(tmp_path, monkeypatch):
    import app.routes.community as community_routes

    monkeypatch.setattr(community_routes, 'UPLOAD_DIR', str(tmp_path))
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
