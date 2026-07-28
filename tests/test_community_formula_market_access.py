from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Post
from app.models.user import User


def test_approved_no_tier_member_can_read_and_search_formula_market():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-market-access-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        member = User(
            email='no-tier@example.com',
            password_hash='unused',
            name='No Tier',
            status='approved',
            tier=None,
            role='user',
        )
        author = User(
            email='admin@example.com',
            password_hash='unused',
            name='Admin',
            status='approved',
            tier='premium',
            role='admin',
        )
        board = Board(
            slug='formula-market',
            name='수식/조건검색식 마켓',
            min_tier='pro',
            write_tier='admin',
            sort_order=1,
        )
        db.session.add_all([member, author, board])
        db.session.flush()
        post = Post(
            board_id=board.id,
            author_id=author.id,
            title='돌파 조건검색식',
            content='거래량 돌파 조건식 설명',
        )
        db.session.add(post)
        db.session.commit()
        member_token = generate_token(member.id)
        post_id = post.id

    client = app.test_client()
    headers = {'Authorization': f'Bearer {member_token}'}

    boards = client.get('/api/community/boards', headers=headers)
    posts = client.get('/api/community/boards/formula-market/posts', headers=headers)
    detail = client.get(f'/api/community/posts/{post_id}', headers=headers)
    search = client.get(
        '/api/community/search?q=돌파&board=formula-market',
        headers=headers,
    )

    assert boards.status_code == 200
    formula_board = next(row for row in boards.get_json() if row['slug'] == 'formula-market')
    assert formula_board['can_read'] is True
    assert formula_board['min_tier'] == 'none'
    assert formula_board['can_write'] is False
    assert posts.status_code == 200
    assert posts.get_json()['posts'][0]['id'] == post_id
    assert detail.status_code == 200
    assert detail.get_json()['post']['id'] == post_id
    assert search.status_code == 200
    assert search.get_json()['posts'][0]['id'] == post_id


def test_unapproved_no_tier_account_still_cannot_read_formula_market():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'formula-market-pending-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        member = User(
            email='pending@example.com',
            password_hash='unused',
            name='Pending',
            status='pending',
            tier=None,
            role='user',
        )
        board = Board(
            slug='formula-market',
            name='수식/조건검색식 마켓',
            min_tier='pro',
            write_tier='admin',
        )
        db.session.add_all([member, board])
        db.session.commit()
        token = generate_token(member.id)

    response = app.test_client().get(
        '/api/community/boards/formula-market/posts',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403
