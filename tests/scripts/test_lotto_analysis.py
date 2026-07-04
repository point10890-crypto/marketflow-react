"""lotto_analysis 단위 테스트."""
import logging
import time
from datetime import datetime
from unittest.mock import MagicMock


def test_parse_llm_json_allows_raw_newlines_in_content():
    import lotto_analysis

    raw = '{"title":"t","content":"<p>a\nb</p>","image_prompt":"balls"}'

    parsed = lotto_analysis._parse_llm_json(raw)

    assert parsed["title"] == "t"
    assert parsed["content"] == "<p>a\nb</p>"


def test_expected_latest_draw_date_uses_previous_draw_before_saturday_cutoff():
    import lotto_analysis

    expected = lotto_analysis._expected_latest_draw_date(datetime(2026, 7, 4, 11, 0))

    assert expected.strftime("%Y-%m-%d") == "2026-06-27"


def test_expected_latest_draw_date_uses_current_saturday_after_draw_cutoff():
    import lotto_analysis

    expected = lotto_analysis._expected_latest_draw_date(datetime(2026, 7, 4, 21, 1))

    assert expected.strftime("%Y-%m-%d") == "2026-07-04"


def test_generate_lotto_post_fallback_contains_draw_and_candidates():
    import lotto_analysis

    stats = {
        "last_draw": {
            "drwNo": 1230,
            "date": "2026-06-27",
            "numbers": [1, 2, 3, 4, 5, 6],
            "bonus": 7,
        },
        "hot_10": [13, 18, 28, 41, 9, 44],
        "cold_10": [3, 2, 5, 7, 10, 15],
        "odd_even": {"odd_pct": 50.0, "even_pct": 50.0},
        "sum_stats": {"mean": 135.0, "stddev": 20.0},
        "gap": {1: 3, 2: 7, 3: 1, 4: 9},
    }
    candidates = {
        "안정형": {
            "desc": "분산형",
            "sets": [{"numbers": [1, 10, 14, 20, 38, 39], "score": 100.0}],
        }
    }

    post = lotto_analysis.generate_lotto_post_fallback(stats, candidates, reason="unit test")

    assert "제1231회" in post["title"]
    assert "1, 10, 14, 20, 38, 39" in post["content"]
    assert "LLM 문장 생성기" in post["content"]


def test_existing_lotto_post_for_draw_detects_visible_duplicate(monkeypatch, tmp_db):
    import sqlite3
    import lotto_analysis

    con = sqlite3.connect(str(tmp_db))
    cur = con.cursor()
    cur.execute(
        "INSERT INTO posts (id, board_id, title, content, is_notice, created_at) VALUES (133, 7, '제1229회 AI 로또 분석', '', 1, '2026-06-19')"
    )
    con.commit()
    con.close()

    monkeypatch.setattr(lotto_analysis, 'DB_FILE', str(tmp_db))

    existing = lotto_analysis._existing_lotto_post_for_draw(1229)

    assert existing == {'post_id': 133, 'title': '제1229회 AI 로또 분석'}


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
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute(
        "INSERT INTO users (id, email, role) VALUES (3, ?, 'admin')",
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
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
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
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute("INSERT INTO users (id, email, role) VALUES (3, 'a@b', 'admin')")
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
            id INTEGER PRIMARY KEY, email TEXT, role TEXT
        )
    """)
    cur.execute("INSERT INTO users (id, email, role) VALUES (3, 'admin@test', 'admin')")
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
