from datetime import datetime, timedelta
from email.utils import format_datetime
from xml.sax.saxutils import escape

import pytest
import requests

from app.services import kongming_article_candidates as service


NOW = datetime.fromisoformat('2026-11-07T19:00:00+09:00')
MASTER = [
    {'symbol': '005930', 'name': '삼성전자'},
    {'symbol': '000660', 'name': 'SK하이닉스'},
    {'symbol': '000111', 'name': '중복이름'},
    {'symbol': '000222', 'name': '중복이름'},
]


def _item(identifier, title, published, description=''):
    return (
        f'<item><title>{escape(title)}</title>'
        f'<link>https://www.businesspost.co.kr/BP?command=article_view&amp;num={identifier}</link>'
        f'<pubDate>{format_datetime(published)}</pubDate>'
        f'<description>{escape(description)}</description></item>'
    )


def _feed(*items):
    return ('<rss><channel>' + ''.join(items) + '</channel></rss>').encode()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(service, '_load_issuers', lambda root, now: (MASTER, '2026-11-06'))
    return tmp_path / 'articles'


def test_classification_retains_per_article_entities_and_72_hour_boundary(data_dir, monkeypatch):
    recent = _item('11', '삼성전자가 SK하이닉스와 공급 계약 검토', NOW - timedelta(hours=72))
    older = _item('12', '삼성전자 실적', NOW - timedelta(hours=73), '<script>수주</script>매출')
    unrelated = _item('13', '삼성전자우 계약, 중복이름 계약', NOW - timedelta(minutes=1))
    monkeypatch.setattr(service, '_fetch', lambda feed, now: _feed(recent, older, unrelated))

    view = service.run_once(data_dir, NOW)

    assert view['operation']['source_count'] == 2
    assert view['issuer_source_as_of'] == '2026-11-06'
    assert view['candidate_article_count'] == 2
    assert view['recent_candidate_article_count'] == 1
    assert view['items'][0]['event'] == {'type': 'contract', 'certainty': 'forecast'}
    assert [entity['symbol'] for entity in view['items'][0]['entities']] == ['000660', '005930']
    assert view['items'][1]['event']['type'] == 'earnings'
    assert all('summary' not in item for item in view['items'])
    assert service.read_view(data_dir, now=NOW + timedelta(seconds=1))['recent_candidate_article_count'] == 0


def test_failure_recovery_uses_due_feed_and_preserves_first_receipt(data_dir, monkeypatch):
    first, second = service.FEEDS
    calls = []

    def fetch(feed, now):
        calls.append(feed)
        if feed == second and now == NOW:
            raise requests.ConnectionError()
        return _feed(_item('11', '삼성전자 실적' if now == NOW else '삼성전자 영업이익', NOW))

    monkeypatch.setattr(service, '_fetch', fetch)
    initial = service.run_once(data_dir, NOW)
    assert initial['operation']['state'] == 'partial'
    assert initial['candidate_article_count'] == 1
    assert service.run_once(data_dir, NOW + timedelta(minutes=1)) is None
    assert calls == [first, second]

    recovered = service.run_once(data_dir, NOW + timedelta(minutes=30))
    assert recovered['operation']['state'] == 'ready'
    assert recovered['items'][0]['title'] == '삼성전자 영업이익'
    assert recovered['items'][0]['first_seen_at'] == NOW.isoformat()


def test_archive_initializes_history_without_network_or_replacing_local_records(data_dir, monkeypatch):
    monkeypatch.setattr(service, '_fetch', lambda *_: pytest.fail('archive and read must not fetch'))
    archive = [{
        'url': 'https://m.businesspost.co.kr/BP?command=article_view&num=12',
        'title': '삼성전자 실적', 'summary': 'publisher content is not exposed',
        'published_at': (NOW - timedelta(days=4)).isoformat(),
        'first_seen_at': (NOW - timedelta(days=4)).isoformat(),
        'entities': [MASTER[0]], 'event': {'type': 'earnings', 'certainty': 'reported_unverified'},
    }]

    service.import_archive(data_dir, archive, now=NOW)
    view = service.read_view(data_dir, now=NOW)

    assert view['operation']['state'] == 'waiting'
    assert view['items'][0]['provenance'] == 'kongming_archive'
    assert view['items'][0]['freshness'] == 'older_context'
    assert 'summary' not in view['items'][0]
    with pytest.raises(ValueError, match='already'):
        service.import_archive(data_dir, archive, now=NOW)


def test_secondary_poll_cannot_revert_an_equal_timestamp_primary_correction(data_dir, monkeypatch):
    first, second = service.FEEDS
    initial = _item('11', '삼성전자 실적', NOW)
    monkeypatch.setattr(service, '_fetch', lambda *_: _feed(initial))
    service.run_once(data_dir, NOW)
    # Simulate a minute of schedule skew after a partial process run.
    state = service._read(data_dir)
    state['feeds'][second]['last_poll_at'] = (NOW + timedelta(minutes=1)).isoformat()
    service.write_json_atomic(data_dir / service.SNAPSHOT, state)
    corrected = _item('11', '삼성전자 영업이익 정정', NOW)
    monkeypatch.setattr(service, '_fetch', lambda feed, _: _feed(corrected if feed == first else initial))

    service.run_once(data_dir, NOW + timedelta(minutes=30))
    view = service.run_once(data_dir, NOW + timedelta(minutes=31))

    assert view['items'][0]['title'] == '삼성전자 영업이익 정정'
    assert view['items'][0]['first_seen_at'] == NOW.isoformat()


def test_malformed_source_cannot_overwrite_the_last_valid_view(data_dir, monkeypatch):
    monkeypatch.setattr(service, '_fetch', lambda *_: _feed(_item('11', '삼성전자 수주', NOW)))
    assert service.run_once(data_dir, NOW)['operation']['state'] == 'ready'
    monkeypatch.setattr(service, '_fetch', lambda *_: b'<!DOCTYPE rss><rss><channel/></rss>')

    view = service.run_once(data_dir, NOW + timedelta(minutes=30))

    assert view['operation']['state'] == 'error'
    assert view['operation']['last_body_received_at'] == NOW.isoformat()
    assert view['items'][0]['id'] == '11'
