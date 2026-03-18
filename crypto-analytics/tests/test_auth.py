"""Auth route tests"""


def test_register_success(client):
    res = client.post('/api/auth/register', json={
        'email': 'new@example.com',
        'password': 'password123',
        'name': 'New User',
    })
    assert res.status_code == 201
    data = res.get_json()
    assert data['user']['email'] == 'new@example.com'
    assert data['user']['name'] == 'New User'
    assert data['user']['tier'] == 'free'
    assert 'token' in data


def test_register_duplicate(client):
    client.post('/api/auth/register', json={
        'email': 'dup@example.com',
        'password': 'password123',
        'name': 'User',
    })
    res = client.post('/api/auth/register', json={
        'email': 'dup@example.com',
        'password': 'password456',
        'name': 'User 2',
    })
    assert res.status_code == 409


def test_register_missing_fields(client):
    res = client.post('/api/auth/register', json={
        'email': 'x@x.com',
    })
    assert res.status_code == 400


def test_register_short_password(client):
    res = client.post('/api/auth/register', json={
        'email': 'short@example.com',
        'password': '123',
        'name': 'Short',
    })
    assert res.status_code == 400


def test_login_success(client):
    client.post('/api/auth/register', json={
        'email': 'login@example.com',
        'password': 'password123',
        'name': 'Login User',
    })
    res = client.post('/api/auth/login', json={
        'email': 'login@example.com',
        'password': 'password123',
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['user']['email'] == 'login@example.com'
    assert 'token' in data


def test_login_wrong_password(client):
    client.post('/api/auth/register', json={
        'email': 'wrong@example.com',
        'password': 'password123',
        'name': 'User',
    })
    res = client.post('/api/auth/login', json={
        'email': 'wrong@example.com',
        'password': 'wrongpassword',
    })
    assert res.status_code == 401


def test_login_nonexistent(client):
    res = client.post('/api/auth/login', json={
        'email': 'nonexistent@example.com',
        'password': 'password123',
    })
    assert res.status_code == 401


def test_me_authenticated(client, auth_headers):
    res = client.get('/api/auth/me', headers=auth_headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data['user']['email'] == 'test@example.com'


def test_me_unauthenticated(client):
    res = client.get('/api/auth/me')
    assert res.status_code == 401


def test_me_invalid_token(client):
    res = client.get('/api/auth/me', headers={
        'Authorization': 'Bearer invalid-token',
    })
    assert res.status_code == 401
