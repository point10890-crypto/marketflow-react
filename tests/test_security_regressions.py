from io import BytesIO

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

from app import create_app
from app.auth.decorators import generate_token, validate_token
from app.routes.common import common_bp
from app.routes.community import (
    MAX_FILE_SIZE,
    _read_upload_limited,
    _validate_video_content,
    community_bp,
)
from app.routes import auth as auth_routes
from app.routes.kr_market import kr_bp
from app.routes.stock_analyzer import stock_analyzer_bp
from app.services import manual_stock_analysis as manual_service
from app.models import db
from app.models.community import Board, Post
from app.models.user import User


def test_system_update_stream_requires_admin_auth():
    app = Flask(__name__)
    app.register_blueprint(common_bp, url_prefix="/api")

    response = app.test_client().get("/api/system/update-data-stream")

    assert response.status_code == 401
    assert response.get_json()["error"] == "Authentication required"


def test_formula_uploads_are_not_served_from_public_upload_route():
    app = Flask(__name__)
    app.register_blueprint(community_bp, url_prefix="/api/community")

    response = app.test_client().get("/api/community/uploads/leaked.zip")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Use the protected download endpoint"


def test_missing_secret_uses_distinct_process_local_signing_keys(monkeypatch):
    monkeypatch.setattr('dotenv.load_dotenv', lambda: False)
    monkeypatch.delenv('SECRET_KEY', raising=False)
    config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    }
    first = create_app(config)
    second = create_app(config)

    with first.app_context():
        token = generate_token(1)
        assert validate_token(token) == 1
    with second.app_context():
        assert validate_token(token) is None


def test_api_cache_headers_do_not_allow_shared_cache(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    client = app.test_client()

    public_response = client.get('/api/health')
    auth_error = client.get('/api/auth/me')
    community_error = client.get('/api/community/summary')

    assert public_response.headers['Cache-Control'].startswith('private,')
    assert 'no-store' in auth_error.headers['Cache-Control']
    assert 'no-store' in community_error.headers['Cache-Control']


def test_oversized_json_is_rejected_before_route_processing():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'json-limit-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
        'MAX_JSON_CONTENT_LENGTH': 128,
    })

    response = app.test_client().post(
        '/api/auth/login',
        data='{"email":"' + ('x' * 200) + '","password":"Password123"}',
        content_type='application/json',
    )

    assert response.status_code == 413


def test_manual_run_id_rejects_windows_path_traversal(monkeypatch, tmp_path):
    monkeypatch.setattr(manual_service, 'RUNS_DIR', tmp_path / 'runs')

    with pytest.raises(ValueError, match='invalid run_id'):
        manual_service._run_path(r'..\..\kis_token_cache')
    with pytest.raises(ValueError, match='invalid run_id'):
        manual_service._run_path('C:\\sensitive')


def test_kr_ai_history_rejects_path_like_date():
    app = Flask(__name__)
    app.register_blueprint(kr_bp, url_prefix='/api/kr')

    response = app.test_client().get('/api/kr/ai-history/..%5C..%5Ckis_token_cache')

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid date format.'


def test_stock_analyzer_rejects_path_like_ticker_before_external_calls():
    app = Flask(__name__)
    app.register_blueprint(stock_analyzer_bp, url_prefix='/api/stock-analyzer')

    response = app.test_client().post(
        '/api/stock-analyzer/analyze',
        json={'ticker': r'C:\\bitman_marketfloww\\data\\target'},
    )

    assert response.status_code == 400
    assert response.get_json()['error'] == 'Invalid ticker format.'


def test_upload_reader_stops_after_size_limit():
    upload = FileStorage(stream=BytesIO(b'x' * (MAX_FILE_SIZE + 10)), filename='x.png')

    assert _read_upload_limited(upload, MAX_FILE_SIZE) is None
    assert upload.stream.tell() == MAX_FILE_SIZE + 1


def test_video_signature_must_match_extension():
    assert _validate_video_content(b'\x00\x00\x00\x18ftypisom', 'mp4') is True
    assert _validate_video_content(b'<script>alert(1)</script>', 'mp4') is False
    assert _validate_video_content(b'\x1aE\xdf\xa3webm', 'webm') is True


def test_untrusted_peer_cannot_spoof_rate_limit_ip():
    app = Flask(__name__)
    with app.test_request_context(
        '/',
        environ_base={'REMOTE_ADDR': '203.0.113.10'},
        headers={'Cf-Connecting-IP': '198.51.100.9'},
    ):
        assert auth_routes._client_ip() == '203.0.113.10'


def test_initial_admin_requires_explicit_bootstrap_secret(monkeypatch):
    monkeypatch.delenv('MARKETFLOW_BOOTSTRAP_ADMIN_SECRET', raising=False)
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })

    response = app.test_client().post('/api/auth/register', json={
        'email': 'first@example.com',
        'name': 'First User',
        'password': 'Password123',
    })

    assert response.status_code == 503
    assert response.get_json()['error'] == 'Initial admin bootstrap is not configured'


def test_legacy_static_secret_admin_route_is_retired(monkeypatch):
    monkeypatch.setenv('ADMIN_SECRET', 'legacy-secret')
    app = Flask(__name__)
    app.register_blueprint(auth_routes.auth_bp, url_prefix='/api/auth')

    response = app.test_client().post(
        '/api/auth/admin/set-tier',
        headers={'X-Admin-Secret': 'legacy-secret'},
        json={'email': 'victim@example.com', 'tier': 'premium'},
    )

    assert response.status_code == 410


def test_community_hides_inaccessible_latest_post_metadata():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'community-security-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        member = User(
            email='pro@example.com', password_hash='unused', name='Pro',
            status='approved', tier='pro', role='user',
        )
        premium_board = Board(
            slug='premium-secret', name='Premium', min_tier='premium',
            write_tier='premium', sort_order=1,
        )
        db.session.add_all([member, premium_board])
        db.session.flush()
        db.session.add(Post(
            board_id=premium_board.id,
            author_id=member.id,
            title='Confidential premium title',
            content='Confidential body',
        ))
        db.session.commit()
        token = generate_token(member.id)

    client = app.test_client()
    boards = client.get(
        '/api/community/boards',
        headers={'Authorization': f'Bearer {token}'},
    )
    summary = client.get(
        '/api/community/summary',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert boards.status_code == 200
    assert boards.get_json()[0]['can_read'] is False
    assert boards.get_json()[0]['latest_post_title'] is None
    assert boards.get_json()[0]['latest_post_id'] is None
    assert summary.status_code == 200
    assert summary.get_json()['recent_posts'] == []


def test_suspended_author_cannot_mutate_existing_post():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'community-state-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        author = User(
            email='suspended@example.com', password_hash='unused', name='Suspended',
            status='suspended', tier='pro', role='user',
        )
        board = Board(
            slug='general', name='General', min_tier='pro',
            write_tier='pro', sort_order=1,
        )
        db.session.add_all([author, board])
        db.session.flush()
        post = Post(
            board_id=board.id, author_id=author.id,
            title='Original', content='Original body',
        )
        db.session.add(post)
        db.session.commit()
        token = generate_token(author.id)
        post_id = post.id

    response = app.test_client().put(
        f'/api/community/posts/{post_id}',
        json={'title': 'Unauthorized update'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403


def test_suspended_admin_token_cannot_use_admin_bypass():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'suspended-admin-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        admin = User(
            email='blocked-admin@example.com', password_hash='unused', name='Blocked Admin',
            status='suspended', tier='premium', role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        token = generate_token(admin.id)

    response = app.test_client().get(
        '/api/admin/dashboard',
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 403
    assert response.get_json()['status'] == 'suspended'


def test_admin_cannot_demote_self_or_last_admin():
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'last-admin-secret',
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {},
    })
    with app.app_context():
        admin = User(
            email='only-admin@example.com', password_hash='unused', name='Only Admin',
            status='approved', tier='premium', role='admin',
        )
        db.session.add(admin)
        db.session.commit()
        admin_id = admin.id
        token = generate_token(admin.id)

    response = app.test_client().put(
        f'/api/admin/users/{admin_id}/role',
        json={'role': 'user'},
        headers={'Authorization': f'Bearer {token}'},
    )

    assert response.status_code == 400
    assert 'Cannot demote' in response.get_json()['error']
