import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.services.surge_trace import service, sources
from app.services.surge_trace.common import safe_url

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=timezone(timedelta(hours=9)))
OBS = {'symbol': '005930', 'name': '삼성전자', 'price_observed_at': NOW.isoformat()}


def test_omni_reads_exact_symbol_and_title_without_mutating_database(tmp_path):
    path = tmp_path / 'data/omni/omni.db'
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE news_events(title,link,source,published_ts,collected_at,symbols)')
        db.executemany('INSERT INTO news_events VALUES(?,?,?,?,?,?)', [
            ('삼성전자 공급계약 체결', 'https://example.com/a', '경제신문', NOW.isoformat(), NOW.isoformat(), '["005930"]'),
            ('삼성전자우 상한가', 'https://example.com/b', '경제신문', NOW.isoformat(), NOW.isoformat(), '["005930"]'),
            ('삼성전자 실적 증가', 'https://example.com/c', '경제신문', NOW.isoformat(), NOW.isoformat(), '["000660"]'),
        ])
    before = path.read_bytes()
    rows = sources.EvidenceSources(tmp_path).omni(OBS, NOW, time.monotonic() + 8)
    assert len(rows) == 1 and rows[0]['publisher'] == '경제신문'
    assert rows[0]['first_received_at'] == NOW.isoformat()
    assert 'omni_archive_freshness_unknown' in rows.limitations
    assert path.read_bytes() == before
    assert {p.name for p in path.parent.iterdir()} == {'omni.db'}


def test_missing_local_sources_remain_unavailable_without_creating_files(tmp_path):
    adapter = sources.EvidenceSources(tmp_path)
    for name in ('omni', 'businesspost'):
        with pytest.raises(sources.SourceUnavailable):
            adapter.collect(name, OBS, NOW, time.monotonic() + 8)
    assert list(tmp_path.iterdir()) == []


def rss_entry(title='삼성전자 공급계약 체결', url='https://news.example.com/1', pub='Tue, 10 Nov 2026 00:00:00 GMT'):
    return f'<item><title>{title} - 경제신문</title><link>{url}</link><pubDate>{pub}</pubDate><source>경제신문</source></item>'


def test_google_query_is_neutral_exact_issuer_and_uses_real_feed_clocks(tmp_path, monkeypatch):
    captured = []
    xml = ('<rss><channel>' + rss_entry() + rss_entry(title='삼성전자우 상승') +
           rss_entry(url='http://127.0.0.1/a') + rss_entry(pub='Wed, 11 Nov 2026 00:00:00 GMT') + '</channel></rss>').encode()
    def get(url, params, *, deadline):
        captured.append((url, params))
        return xml
    monkeypatch.setattr(sources, '_http_get', get)
    rows = sources.EvidenceSources(tmp_path, now=NOW).google_news(OBS, NOW, time.monotonic() + 8)
    assert captured == [('https://news.google.com/rss/search',
                         {'q': '"삼성전자" when:7d', 'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko'})]
    assert len(rows) == 1
    assert rows[0]['published_at'] == '2026-11-10T09:00:00+09:00'
    assert rows[0]['first_received_at'] == NOW.isoformat()
    assert rows[0]['publisher'] == '경제신문' and rows[0]['title'] == '삼성전자 공급계약 체결'


def test_google_caps_matches_and_rejects_xml_entities(tmp_path, monkeypatch):
    xml = ('<rss><channel>' + ''.join(rss_entry(url=f'https://example.com/{n}') for n in range(12)) + '</channel></rss>').encode()
    monkeypatch.setattr(sources, '_http_get', lambda *a, **k: xml)
    adapter = sources.EvidenceSources(tmp_path, now=NOW)
    assert len(adapter.google_news(OBS, NOW, time.monotonic() + 8)) == 10
    monkeypatch.setattr(sources, '_http_get', lambda *a, **k: b'<!DOCTYPE rss [<!ENTITY x "xx">]><rss><channel/></rss>')
    with pytest.raises(sources.SourceUnavailable):
        adapter.google_news(OBS, NOW, time.monotonic() + 8)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'https://user:pass@news.example.com/a',
    'http://localhost/a', 'http://127.0.0.1/a', 'https://192.168.1.2/a', 'http://2130706433/a',
    'http://0x7f000001/a', 'http://0177.0.0.1/a', 'https://host.internal/a',
    'https://example.com/?api_key=private', 'https://example.com\\@127.0.0.1/a',
    'http://%31%32%37.0.0.1/a', 'http://router.lan/a'])
def test_public_evidence_cannot_contain_private_or_credentialed_links(url):
    assert safe_url(url) is None


def test_dart_matches_all_issuer_fields_and_keeps_date_precision(tmp_path, monkeypatch):
    from app.services import kongming_disclosure
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'dart_corp_codes.json').write_text(json.dumps({'005930': '00126380'}))
    row = {'corp_code': '00126380', 'stock_code': '005930', 'corp_name': '삼성전자',
           'report_nm': '단일판매ㆍ공급계약체결', 'rcept_no': '20261110000001', 'rcept_dt': '20261110'}
    rows = [row, {**row, 'corp_code': '00000001'}, {**row, 'stock_code': '000660'},
            {**row, 'corp_name': '삼성전자우'}, {**row, 'rcept_dt': '20261111'}]
    calls = []
    def transport(url, params, *, limit, deadline):
        calls.append((url, {key: value for key, value in params.items() if key != 'crtfc_key'}))
        return json.dumps({'status': '000', 'total_page': 1, 'list': rows}).encode()
    monkeypatch.setattr(kongming_disclosure, '_credentials', lambda root: 'test-secret')
    monkeypatch.setattr(kongming_disclosure, '_http_get', transport)
    result = sources.EvidenceSources(tmp_path, now=NOW).collect('dart', OBS, NOW, time.monotonic() + 8)
    assert len(calls) == 1 and calls[0][1]['corp_code'] == '00126380'
    assert calls[0][1]['bgn_de'] == '20261103' and calls[0][1]['end_de'] == '20261110'
    assert len(result) == 1 and result[0]['published_at'] == '2026-11-10'
    assert result[0]['published_precision'] == 'date'
    assert result[0]['verification'] == 'issuer_registry_match'


def test_google_short_ambiguous_issuer_does_not_match_generic_words(tmp_path, monkeypatch):
    body = ('<rss><channel>' + rss_entry('동양 문화와 공급계약') + rss_entry('동양(001520) 공급계약 체결') + '</channel></rss>').encode()
    monkeypatch.setattr(sources, '_http_get', lambda *a, **k: body)
    obs = {**OBS, 'symbol': '001520', 'name': '동양'}
    rows = sources.EvidenceSources(tmp_path, now=NOW).google_news(obs, NOW, time.monotonic() + 8)
    assert len(rows) == 1 and rows[0]['title'] == '동양(001520) 공급계약 체결'


def test_businesspost_retains_rows_but_does_not_hide_partial_source_failure(tmp_path, monkeypatch):
    from app.services import kongming_article_candidates
    root = tmp_path / 'data/kongming_article_candidates'
    root.mkdir(parents=True)
    (root / 'snapshot.json').write_text('{}')
    monkeypatch.setattr(kongming_article_candidates, 'read_view', lambda *a, **k: {
        'operation': {'state': 'partial'}, 'items': [
            {'title': '삼성전자 공급계약 체결', 'url': 'https://www.businesspost.co.kr/BP?command=article_view&num=123',
             'entities': [{'symbol': '005930', 'name': '삼성전자'}], 'published_at': NOW.isoformat(), 'first_seen_at': NOW.isoformat()}]})
    rows = sources.EvidenceSources(tmp_path).businesspost(OBS, NOW, time.monotonic() + 8)
    assert len(rows) == 1 and rows.error_code == 'upstream_partial'


def test_google_excludes_sports_namesake_and_selects_newest_matches(tmp_path, monkeypatch):
    entries = [rss_entry('석진욱 감독 복귀 승 한국전력, 대한항공 격파')]
    entries += [rss_entry('대한항공 공급계약 체결', url=f'https://example.com/{n}',
                          pub=f'Tue, 10 Nov 2026 00:{n:02}:00 GMT') for n in range(11)]
    monkeypatch.setattr(sources, '_http_get', lambda *a, **k: ('<rss><channel>' + ''.join(entries) + '</channel></rss>').encode())
    obs = {**OBS, 'symbol': '003490', 'name': '대한항공'}
    rows = sources.EvidenceSources(tmp_path, now=NOW).google_news(obs, NOW, time.monotonic() + 8)
    assert len(rows) == 10 and rows[0]['published_at'] == '2026-11-10T09:10:00+09:00'
    assert all('감독' not in row['title'] for row in rows)


def test_google_sports_publisher_result_is_excluded_but_business_contract_is_retained(tmp_path, monkeypatch):
    sports = rss_entry('정말 냉철하네 "대한항공 이겼다고 자축하고 있을 수 없다" [대전 현장]').replace('경제신문', '스포츠조선')
    contract = rss_entry('대한항공, 프로배구 후원 계약 체결', url='https://example.com/sponsorship').replace('경제신문', '스포츠조선')
    body = ('<rss><channel>' + sports + contract + '</channel></rss>').encode()
    monkeypatch.setattr(sources, '_http_get', lambda *a, **k: body)
    obs = {**OBS, 'symbol': '003490', 'name': '대한항공'}
    rows = sources.EvidenceSources(tmp_path, now=NOW).google_news(obs, NOW, time.monotonic() + 8)
    assert [row['title'] for row in rows] == ['대한항공, 프로배구 후원 계약 체결']
