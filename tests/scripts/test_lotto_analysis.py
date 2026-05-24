"""lotto_analysis 단위 테스트."""
import logging
import time
from unittest.mock import MagicMock


def test_logger_used_for_errors(caplog, clean_env, monkeypatch):
    """run_lotto_analysis_post 에서 예외 발생 시 traceback 이 logger 로 기록되어야 함.

    회귀 보호: 과거 print() 만 사용해서 traceback 이 사라졌던 결함 ①.
    """
    # load_history 가 raise 하도록 강제
    import lotto_analysis
    # Task 3 의 idempotency guard 가 추가된 후에도 정상 흐름 진입하도록 mock
    # (raising=False — Task 1 시점에는 함수 미정의일 수 있음)
    monkeypatch.setattr(lotto_analysis, '_has_today_lotto_post', lambda: False, raising=False)
    monkeypatch.setattr(lotto_analysis, 'load_history',
                        MagicMock(side_effect=RuntimeError("forced test failure")))

    with caplog.at_level(logging.ERROR, logger='lotto_analysis'):
        result = lotto_analysis.run_lotto_analysis_post(dry_run=False)

    assert result is False, "예외 시 False 반환 유지"

    # traceback 이 logger 로 기록되었는지 검증
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1, "ERROR 레벨 로그가 최소 1건 있어야 함"

    has_traceback = any(
        r.exc_info is not None or 'forced test failure' in r.getMessage()
        for r in error_records
    )
    assert has_traceback, "logger.exception 또는 logger.error(exc_info=True) 사용 필요"


def test_create_post_has_timeout(monkeypatch):
    """create_post 의 requests.post 호출이 timeout 인자를 가져야 함.

    회귀 보호: timeout 없는 requests.post 가 무한 hang 가능했던 결함 ③.
    """
    import lotto_analysis
    captured = {}

    def fake_post(url, **kwargs):
        captured['kwargs'] = kwargs
        resp = MagicMock()
        resp.status_code = 200
        resp.json = lambda: {'id': 999}
        return resp

    monkeypatch.setattr(lotto_analysis.requests, 'post', fake_post)

    lotto_analysis.create_post('fake_token', 'lotto-ai', 'title', '<p>body</p>')

    assert 'timeout' in captured['kwargs'], "create_post 의 requests.post 에 timeout 인자 필수"
    assert captured['kwargs']['timeout'] >= 15, "timeout 은 최소 15초 이상"


def test_pin_notice_has_timeout(monkeypatch):
    """pin_notice 의 requests.put 호출이 timeout 인자를 가져야 함."""
    import lotto_analysis
    captured = {}

    def fake_put(url, **kwargs):
        captured['kwargs'] = kwargs
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr(lotto_analysis.requests, 'put', fake_put)

    lotto_analysis.pin_notice('fake_token', 999)

    assert 'timeout' in captured['kwargs'], "pin_notice 의 requests.put 에 timeout 인자 필수"
    assert captured['kwargs']['timeout'] >= 15


def test_local_admin_token_no_create_app(monkeypatch, clean_env, tmp_db):
    """_local_admin_token() 이 `from app import create_app` 을 호출하지 않아야 함.

    회귀 보호: 결함 ⑤ — 과거에는 매 호출마다 create_app() 으로 Flask 인스턴스를
    만들어 모든 background worker 가 재시작되었음. 경량화 버전은 sqlite3 + HMAC 만 사용.
    """
    import sys
    import sqlite3
    import lotto_analysis

    # tmp_db 에 admin user 1명 삽입
    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, is_admin INTEGER
        )
    """)
    cur.execute(
        "INSERT INTO users (id, email, is_admin) VALUES (3, ?, 1)",
        ('point10890@gmail.com',)
    )
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    monkeypatch.setenv('SECRET_KEY', 'test-secret-key')

    # `from app import create_app` 가 호출되면 즉시 에러
    # (이 라인이 함수 안에 lazy import 가 아니라 module-level import 면 fail)
    if 'app' in sys.modules:
        monkeypatch.setattr(sys.modules['app'], 'create_app',
                            MagicMock(side_effect=AssertionError("create_app called!")))

    token = lotto_analysis._local_admin_token()

    assert token is not None, "admin user 가 있는데 token 반환 안 됨"
    # Token 포맷: "user_id:expiry:sig" (32 hex chars)
    parts = token.split(':')
    assert len(parts) == 3, f"token 포맷 불일치: {token}"
    assert parts[0] == '3', f"user_id 불일치: {parts[0]}"
    assert int(parts[1]) > int(time.time()), "expiry 가 미래여야 함"
    assert len(parts[2]) == 32, "signature 가 32자여야 함 (truncated HMAC-SHA256)"


def test_local_admin_token_returns_none_without_admin(monkeypatch, clean_env, tmp_db):
    """admin user 없으면 None 반환 (raise 하지 않음)."""
    import sqlite3
    import lotto_analysis

    # users 테이블만 있고 admin 없는 상태
    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, is_admin INTEGER
        )
    """)
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))

    assert lotto_analysis._local_admin_token() is None


def test_local_admin_token_signature_matches_flask(monkeypatch, clean_env, tmp_db):
    """경량화된 token 의 signature 가 Flask 의 generate_token 과 비트-동일해야 함.

    같은 (user_id, expiry, SECRET_KEY) 입력에 대해 동일 출력. 그래야 Flask 의
    validate_token() 이 통과함.
    """
    import sqlite3
    import hmac
    import hashlib
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, is_admin INTEGER
        )
    """)
    cur.execute("INSERT INTO users (id, email, is_admin) VALUES (3, 'a@b', 1)")
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    secret = 'unit-test-secret-7891'
    monkeypatch.setenv('SECRET_KEY', secret)

    token = lotto_analysis._local_admin_token()
    assert token is not None

    user_id_str, expiry_str, sig = token.split(':')
    expected_sig = hmac.new(
        secret.encode(),
        f"{user_id_str}:{expiry_str}".encode(),
        hashlib.sha256
    ).hexdigest()[:32]
    assert sig == expected_sig, "Flask generate_token 과 동일 signature 알고리즘이어야 함"


def test_login_falls_back_to_local_token_when_no_env(monkeypatch, clean_env, tmp_db):
    """ADMIN_TOKEN/PASSWORD 미설정 시 _local_admin_token() 으로 fallback."""
    import sqlite3
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY, email TEXT, is_admin INTEGER
        )
    """)
    cur.execute("INSERT INTO users (id, email, is_admin) VALUES (3, 'admin@test', 1)")
    con.commit()
    con.close()

    import importlib
    importlib.reload(lotto_analysis)
    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))
    monkeypatch.setenv('SECRET_KEY', 'test-secret')

    # requests.post 가 호출되면 fail (HTTP path 가지 않아야)
    def fail_post(*args, **kwargs):
        raise AssertionError("HTTP login should not be called when password is unset")
    monkeypatch.setattr(lotto_analysis.requests, 'post', fail_post)

    token = lotto_analysis.login()

    assert token is not None
    assert token.startswith('3:'), f"local token expected, got: {token}"
