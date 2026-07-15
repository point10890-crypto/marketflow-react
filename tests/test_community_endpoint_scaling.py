from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.community import Board, Post
from app.models.user import User


def _app():
    return create_app({
        'TESTING': True,
        'SECRET_KEY': 'community-endpoint-test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })


def _seed(app, post_count=20):
    with app.app_context():
        user = User(
            email='community@example.com',
            password_hash='not-used',
            name='Community User',
            status='approved',
            tier='premium',
        )
        board = Board(
            slug='general',
            name='General',
            min_tier='pro',
            write_tier='pro',
            sort_order=1,
        )
        db.session.add_all([user, board])
        db.session.flush()

        base = datetime.now(timezone.utc) - timedelta(days=2)
        for index in range(post_count):
            created = base + timedelta(minutes=index)
            db.session.add(Post(
                board_id=board.id,
                author_id=user.id,
                title=f'post-{index}',
                content='body',
                created_at=created,
                updated_at=created,
            ))
        db.session.add(Post(
            board_id=board.id,
            author_id=user.id,
            title='hidden-newest',
            content='body',
            is_hidden=True,
            created_at=base + timedelta(days=3),
            updated_at=base + timedelta(days=3),
        ))
        db.session.commit()
        token = generate_token(user.id)
        return token


def test_boards_uses_aggregate_queries_and_ignores_hidden_posts():
    app = _app()
    token = _seed(app, post_count=500)
    statements = []

    with app.app_context():
        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            statements.append(' '.join(statement.lower().split()))

        event.listen(db.engine, 'before_cursor_execute', record_statement)
        try:
            response = app.test_client().get(
                '/api/community/boards',
                headers={'Authorization': f'Bearer {token}'},
            )
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_statement)

    assert response.status_code == 200
    body = response.get_json()
    assert len(body) == 1
    assert body[0]['post_count'] == 500
    assert body[0]['latest_post_title'] == 'post-499'

    post_queries = [sql for sql in statements if ' from posts' in sql]
    assert any('count(posts.id)' in sql for sql in post_queries)
    assert any('max(coalesce(posts.updated_at, posts.created_at))' in sql for sql in post_queries)
    assert not any('hidden-newest' in sql for sql in post_queries)


def test_post_list_normalizes_invalid_pagination_values():
    app = _app()
    token = _seed(app, post_count=3)

    response = app.test_client().get(
        '/api/community/boards/general/posts?page=-9&per_page=-4',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['page'] == 1
    assert body['per_page'] == 1
    assert len(body['posts']) == 1


def test_post_and_comment_payload_limits_reject_oversized_text():
    app = _app()
    token = _seed(app, post_count=1)
    client = app.test_client()
    headers = {'Authorization': f'Bearer {token}'}

    post_response = client.post(
        '/api/community/boards/general/posts',
        json={'title': 'x' * 201, 'content': 'body'},
        headers=headers,
    )
    assert post_response.status_code == 400
    assert 'Title too long' in post_response.get_json()['error']

    with app.app_context():
        post_id = Post.query.filter_by(is_hidden=False).first().id

    comment_response = client.post(
        f'/api/community/posts/{post_id}/comments',
        json={'content': 'x' * 10_001},
        headers=headers,
    )
    assert comment_response.status_code == 400
    assert 'Content too long' in comment_response.get_json()['error']
