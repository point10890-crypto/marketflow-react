from app.services.forecast_league import capsules


def test_same_content_is_stored_once(league_conn):
    first = capsules.put_capsule(league_conn, {'b': 2, 'a': '가'})
    second = capsules.put_capsule(league_conn, {'a': '가', 'b': 2})
    assert first == second and len(first) == 64
    assert league_conn.execute('SELECT COUNT(*) FROM capsules').fetchone()[0] == 1
    assert capsules.get_capsule(league_conn, first) == {'a': '가', 'b': 2}


def test_different_content_gets_a_different_hash(league_conn):
    assert capsules.put_capsule(league_conn, {'a': 1}) != capsules.put_capsule(league_conn, {'a': 2})


def test_missing_capsule_returns_none(league_conn):
    assert capsules.get_capsule(league_conn, '0' * 64) is None
