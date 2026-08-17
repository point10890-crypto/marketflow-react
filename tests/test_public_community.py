# -*- coding: utf-8 -*-
"""공개 커뮤니티 읽기 API 회귀 테스트 (AdSense 심사용 비로그인 콘텐츠).

경계:
- 화이트리스트 보드만 노출 (수식마켓·Pro 라운지 제외)
- 읽기 전용 (POST/PUT/DELETE 없음)
- 작성자는 표시 이름만 — 이메일/author_id 비노출
- per_page 상한
"""
import pytest

from app import create_app
from app.models import db
from app.models.community import Board, Comment, Post
from app.models.user import User


@pytest.fixture()
def app():
    application = create_app({
        'TESTING': True,
        'SECRET_KEY': 'public-community-test',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with application.app_context():
        author = User(email='writer@example.com', name='분석봇', status='approved',
                      tier='pro', role='user')
        author.set_password('pw12345678')
        db.session.add(author)
        db.session.flush()

        notice = Board(slug='notice', name='공지사항', is_active=True, sort_order=1)
        lounge = Board(slug='pro-lounge', name='Pro 라운지', is_active=True, sort_order=2)
        db.session.add_all([notice, lounge])
        db.session.flush()

        post = Post(board_id=notice.id, author_id=author.id,
                    title='오늘의 시장 분석', content='<p>본문 내용</p>')
        secret = Post(board_id=lounge.id, author_id=author.id,
                      title='라운지 비공개 글', content='<p>비공개</p>')
        db.session.add_all([post, secret])
        db.session.flush()
        db.session.add(Comment(post_id=post.id, author_id=author.id, content='댓글입니다'))
        db.session.commit()

        application.config['_test_ids'] = {'post': post.id, 'secret': secret.id}
        yield application
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_boards_lists_only_whitelisted(client):
    r = client.get('/api/public/community/boards')
    assert r.status_code == 200
    slugs = [b['slug'] for b in r.get_json()['boards']]
    assert 'notice' in slugs
    assert 'pro-lounge' not in slugs
    assert 'formula-market' not in slugs


def test_posts_list_public_without_auth(client):
    r = client.get('/api/public/community/boards/notice/posts')
    assert r.status_code == 200
    body = r.get_json()
    titles = [p['title'] for p in body['posts'] + body.get('notices', [])]
    assert '오늘의 시장 분석' in titles


def test_non_whitelisted_board_hidden(client):
    r = client.get('/api/public/community/boards/pro-lounge/posts')
    assert r.status_code == 404


def test_post_detail_masks_author_identity(app, client):
    pid = app.config['_test_ids']['post']
    r = client.get(f'/api/public/community/posts/{pid}')
    assert r.status_code == 200
    text = r.get_data(as_text=True)
    assert 'writer@example.com' not in text, '작성자 이메일이 노출된다'
    body = r.get_json()
    assert body['post']['author_name'] == '분석봇'
    assert 'author_id' not in body['post']
    assert body['comments'][0]['author_name'] == '분석봇'
    assert 'author_id' not in body['comments'][0]


def test_secret_board_post_detail_404(app, client):
    sid = app.config['_test_ids']['secret']
    assert client.get(f'/api/public/community/posts/{sid}').status_code == 404


def test_write_methods_not_exposed(app, client):
    pid = app.config['_test_ids']['post']
    assert client.post('/api/public/community/boards/notice/posts',
                       json={'title': 'x', 'content': 'y'}).status_code == 405
    assert client.post(f'/api/public/community/posts/{pid}/comments',
                       json={'content': 'x'}).status_code in (404, 405)
    assert client.delete(f'/api/public/community/posts/{pid}').status_code == 405


def test_per_page_capped(client):
    r = client.get('/api/public/community/boards/notice/posts?per_page=500')
    assert r.status_code == 200
    assert r.get_json()['per_page'] <= 30
