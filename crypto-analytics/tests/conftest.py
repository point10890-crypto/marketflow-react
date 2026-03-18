"""Test fixtures for Flask app"""

import os
import pytest

# Set test environment before importing app
os.environ['TESTING'] = '1'


@pytest.fixture
def app():
    from app import create_app
    from app.models import db

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-secret-key',
    })

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers(client):
    """Register a user and return auth headers."""
    client.post('/api/auth/register', json={
        'email': 'test@example.com',
        'password': 'password123',
        'name': 'Test User',
    })
    res = client.post('/api/auth/login', json={
        'email': 'test@example.com',
        'password': 'password123',
    })
    token = res.get_json()['token']
    return {'Authorization': f'Bearer {token}'}
