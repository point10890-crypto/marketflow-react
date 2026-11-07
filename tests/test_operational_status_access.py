import pytest
from app import create_app
from app.auth.decorators import generate_token
from app.models import db
from app.models.user import User


@pytest.mark.parametrize('path', ['/api/system/data-status', '/api/system/last-update'])
def test_operational_file_status_is_admin_only(path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-ops-access',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                      'SQLALCHEMY_ENGINE_OPTIONS': {}})
    with app.app_context():
        identities = [User(email=f'{role}@test.invalid', name=role, password_hash='unused',
                           status='approved', role=role, tier='pro') for role in ('admin', 'user')]
        db.session.add_all(identities)
        db.session.commit()
        admin, member = [generate_token(u.id) for u in identities]
    client = app.test_client()
    assert client.get(path).status_code == 401
    assert client.get(path, headers={'Authorization': f'Bearer {member}'}).status_code == 403
    response = client.get(path, headers={'Authorization': f'Bearer {admin}'})
    assert response.status_code == 200
    assert 'no-store' in response.headers.get('Cache-Control', '')
