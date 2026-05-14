from app.routes import auth


def test_login_rate_limit_is_scoped_by_email():
    auth._login_failures.clear()
    ip = '127.0.0.1'
    blocked_key = auth._login_rate_key(ip, 'mistyped@example.com')
    other_key = auth._login_rate_key(ip, 'member@example.com')

    for _ in range(auth._LOGIN_MAX_FAILURES):
        auth._record_login_failure(blocked_key)

    assert auth._check_login_rate_limit(blocked_key) is True
    assert auth._check_login_rate_limit(other_key) is False
