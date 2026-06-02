import json
import time

from app.services.mirofish import blacklist


def test_kind_blacklist_refresh_parses_and_caches(tmp_path, monkeypatch):
    payload = '테스트기업 000001 관리종목 투자경고'
    monkeypatch.setattr(blacklist, '_fetch_kind_payload', lambda url: payload)

    snapshot = blacklist.refresh_kind_blacklist(data_root=str(tmp_path))

    assert snapshot['status'] == 'fresh'
    assert snapshot['entry_count'] == 1
    assert snapshot['entries']['000001']['risk_level'] == 'hard_block'
    assert (tmp_path / blacklist.KIND_CACHE_FILENAME).is_file()

    entry = blacklist.is_blacklisted('000001', data_root=str(tmp_path))
    assert entry['listed'] is True
    assert '관리종목' in entry['categories']


def test_kind_blacklist_fails_open_without_cache(tmp_path, monkeypatch):
    def fail(url):
        raise RuntimeError('network down')

    monkeypatch.setattr(blacklist, '_fetch_kind_payload', fail)

    snapshot = blacklist.get_kind_blacklist(data_root=str(tmp_path), allow_fetch=True)

    assert snapshot['status'] == 'error'
    assert snapshot['entries'] == {}
    assert blacklist.is_blacklisted('005930', data_root=str(tmp_path))['listed'] is False


def test_kind_blacklist_returns_stale_cache_on_fetch_error(tmp_path, monkeypatch):
    monkeypatch.setattr(blacklist, '_fetch_kind_payload', lambda url: (_ for _ in ()).throw(RuntimeError('boom')))
    old = {
        'schema_version': 'mirofish.kind_blacklist.v1',
        'source': 'KIND/KRX public disclosure risk cache',
        'status': 'fresh',
        'fetched_at': '2000-01-01T00:00:00+00:00',
        'entry_count': 1,
        'entries': {'000123': {'symbol': '000123', 'categories': ['거래정지'], 'risk_level': 'hard_block'}},
        'lookahead_safe': True,
    }
    path = tmp_path / blacklist.KIND_CACHE_FILENAME
    path.write_text(json.dumps(old), encoding='utf-8')

    snapshot = blacklist.get_kind_blacklist(
        data_root=str(tmp_path),
        allow_fetch=True,
        now=time.time(),
        ttl_seconds=60,
    )

    assert snapshot['status'] == 'stale'
    assert snapshot['entries']['000123']['risk_level'] == 'hard_block'
