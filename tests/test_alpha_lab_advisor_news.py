"""Saved multi-publisher news must remain time-bound unverified evidence."""
import json
import sqlite3
from datetime import datetime, timezone

from app.services.mirofish.alpha_lab import advisor_news

NOW = datetime(2026, 11, 10, 10, tzinfo=timezone.utc)
TARGET = {'symbol': '028050', 'name': '삼성E&A', 'market': 'KR'}


def database(tmp_path, rows):
    path = tmp_path/'omni.db'
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE news_events(title,link,source,published_ts,collected_at,symbols)')
    base = dict(title='삼성E&A 신규 계약 발표', link='https://www.yna.co.kr/view/AKR202611100001',
                source='yonhap_economy', published_ts='2026-11-10T15:00:00+09:00',
                collected_at='2026-11-10T15:05:00+09:00', symbols=json.dumps(['028050']))
    for change in rows:
        row = dict(base, **change)
        con.execute('INSERT INTO news_events VALUES (?,?,?,?,?,?)', tuple(row.values()))
    con.commit(); con.close()
    return path


def test_saved_news_preserves_clocks_and_issuer_without_claiming_verification(tmp_path):
    path = database(tmp_path, [{}]); before = path.read_bytes(); warnings = []
    rows = advisor_news.read_news(path, [TARGET], NOW, warnings)
    assert len(rows) == 1
    assert rows[0]['targets'] == [TARGET]
    source = rows[0]['sources'][0]
    assert source['source'] == 'MarketFlow_Omni_saved_news'
    assert source['published_at'] == '2026-11-10T06:00:00Z'
    assert source['fetched_at'] == '2026-11-10T06:05:00Z'
    assert source['verification_status'] == 'reported_unverified'
    assert source['url'] == 'https://www.yna.co.kr/view/AKR202611100001'
    from app.services.mirofish.alpha_lab import advisor
    assert advisor.public_projection({'sources': [source]})['sources'][0]['url'] == source['url']
    assert 'omni_archive_freshness_unknown' in warnings
    assert path.read_bytes() == before
    assert advisor_news.read_news(path, [TARGET], NOW, []) == rows


def test_excludes_wrong_issuer_sports_unsafe_and_invalid_clocks(tmp_path):
    path = database(tmp_path, [
        {'symbols': '["005930"]'}, {'title': '삼성전자 신규 계약'},
        {'title': '삼성E&A 야구 승리'}, {'link': 'http://127.0.0.1/private'},
        {'published_ts': '2026-11-05T15:00:00+09:00'},
        {'published_ts': '2026-11-10T15:06:00+09:00'},
        {'collected_at': '2026-11-11T15:00:00+09:00'},
        {'published_ts': '2026-11-10T15:00:00'}, {'symbols': '{}'},
        {'published_ts': None}, {'collected_at': None},
    ])
    assert advisor_news.read_news(path, [TARGET], NOW, []) == []


def test_deduplicates_title_and_url_and_bounds_evidence_per_target(tmp_path):
    rows = [{'link': f'https://www.yna.co.kr/view/{i}'} for i in range(4)]
    rows += [{'title': f'삼성E&A 계약 변경 {i}', 'link': f'https://www.hankyung.com/article/{i}'} for i in range(8)]
    result = advisor_news.read_news(database(tmp_path, rows), [TARGET], NOW, [])
    assert len(result) == 2
    assert len({r['sources'][0]['text'] for r in result}) == 2


def test_missing_corrupt_and_locked_source_never_creates_or_writes_database(tmp_path):
    path = tmp_path/'missing.db'; warnings = []
    assert advisor_news.read_news(path, [TARGET], NOW, warnings) == []
    assert not path.exists()
    path.write_bytes(b'corrupt'); before = path.read_bytes()
    assert advisor_news.read_news(path, [TARGET], NOW, warnings) == []
    assert path.read_bytes() == before
    assert 'omni_news_source_unavailable' in warnings


def test_multi_issuer_article_only_binds_named_targets(tmp_path):
    path = database(tmp_path, [{'symbols': '["028050","005930"]'}])
    second = {'symbol': '005930', 'name': '삼성전자', 'market': 'KR'}
    result = advisor_news.read_news(path, [TARGET, second], NOW, [])
    assert len(result) == 1 and result[0]['targets'] == [TARGET]
