"""Surge traces preserve price and evidence clocks without making causal claims."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.services.surge_trace import service, sources

NOW = datetime(2026, 11, 10, 10, 0, tzinfo=timezone(timedelta(hours=9)))


def setup_source(tmp_path, rows=None, **overrides):
    data = tmp_path / 'data'
    data.mkdir(exist_ok=True)
    (data / 'ticker_to_yahoo_map.csv').write_text(
        'ticker,market,yahoo_ticker,name\n005930,KOSPI,005930.KS,삼성전자\n000660,KOSPI,000660.KS,SK하이닉스\n', encoding='utf-8')
    row = {'code': '005930', 'name': '삼성전자', 'market': 'KOSPI', 'price': 75000,
           'change_pct': 7.1, 'trading_value': 3_000_000_000, 'score_complete': False,
           'eligible': False, 'grade': 'C'}
    source = {'timestamp': NOW.replace(tzinfo=None).isoformat(), 'quote_mode': 'real', 'market_status': 'open',
              'data_quality': {'critical_complete': True, 'safe_to_replace_latest': True},
              'candidate_pool': [row] if rows is None else rows, 'results': []}
    source.update(overrides)
    (data / 'screener_leading_latest.json').write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
    return source


@pytest.fixture
def empty_providers(monkeypatch):
    calls = []
    def collect(self, source, observation, now, deadline):
        calls.append(source)
        return []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    return calls


def test_read_is_empty_and_does_not_create_or_collect(tmp_path, empty_providers):
    root = tmp_path / 'absent'
    view = service.read_view(root, now=NOW)
    assert view['items'] == [] and view['status'] == 'waiting'
    assert view['source_as_of'] is None
    assert not root.exists() and empty_providers == []


def test_detects_low_grade_surges_and_seals_first_observation(tmp_path, empty_providers):
    source = setup_source(tmp_path)
    root = tmp_path / 'traces'
    first = service.run_once(root, project_root=tmp_path, now=NOW)['items'][0]
    assert first['symbol'] == '005930' and first['status'] == 'unresolved'
    assert first['price_observed_at'] == '2026-11-10T10:00:00+09:00'
    assert first['first_detected_at'] == NOW.isoformat()
    assert first['price'] == 75000 and first['evidence'] == []
    source['timestamp'] = '2026-11-10T10:01:00'
    source['candidate_pool'][0]['price'] = 76000
    setup_source(tmp_path, **source)
    second = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=1))['items'][0]
    assert {k: second[k] for k in ('id', 'price', 'first_detected_at', 'price_observed_at')} == {
        k: first[k] for k in ('id', 'price', 'first_detected_at', 'price_observed_at')}
    assert len(list((root / 'observations').glob('*.json'))) == 1
    assert len(empty_providers) == 4


@pytest.mark.parametrize('overrides,status', [
    ({'quote_mode': 'paper'}, 'paper'),
    ({'timestamp': '2026-11-10T10:01:00'}, 'future'),
    ({'timestamp': '2026-11-10T09:54:59'}, 'stale'),
    ({'data_quality': {'critical_complete': False, 'safe_to_replace_latest': False}}, 'incomplete'),
    ({'timestamp': '2026-11-06T10:00:00'}, 'stale'),
])
def test_rejects_unusable_market_sources(tmp_path, empty_providers, overrides, status):
    setup_source(tmp_path, **overrides)
    view = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)
    assert view['items'] == [] and view['operation']['source_status'] == status
    assert empty_providers == []


def test_historical_price_is_labelled_and_discovery_time_is_not_backdated(tmp_path, empty_providers):
    setup_source(tmp_path, timestamp='2026-11-09T15:30:00')
    view = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)
    assert view['operation']['source_status'] == 'historical'
    row = view['items'][0]
    assert row['session'] == '2026-11-09'
    assert row['first_detected_at'] == NOW.isoformat()
    assert 'historical_observation' in row['limitations']


def test_closed_session_stored_prices_remain_historical_with_partial_coverage(tmp_path, empty_providers):
    setup_source(tmp_path, market_status='closed', status='partial',
                 data_quality={'critical_complete': True, 'safe_to_replace_latest': True, 'universe_complete': False})
    view = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW + timedelta(hours=8))
    assert view['operation']['source_status'] == 'historical'
    assert 'source_universe_partial' in view['items'][0]['limitations']


@pytest.mark.parametrize('change', [
    {'name': '삼성전자우'}, {'market': 'KONEX'}, {'price': 0}, {'price': float('nan')},
    {'change_pct': 4.99}, {'trading_value': 1_999_999_999}, {'code': '999999'},
])
def test_requires_exact_identity_real_price_and_liquidity(tmp_path, empty_providers, change):
    source = setup_source(tmp_path)
    source['candidate_pool'][0].update(change)
    setup_source(tmp_path, **source)
    assert service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'] == []


def test_source_regression_cannot_create_a_backdated_observation(tmp_path, empty_providers):
    setup_source(tmp_path)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    setup_source(tmp_path, timestamp='2026-11-09T15:30:00')
    view = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=1))
    assert view['operation']['source_status'] == 'regressed'
    assert len(view['items']) == 1 and view['items'][0]['session'] == '2026-11-10'


def news(title, **extra):
    return {'kind': 'news', 'title': title, 'url': 'https://news.example.com/a',
            'source': 'omni', 'publisher': '경제신문', 'published_at': '2026-11-10T09:00:00+09:00',
            'published_precision': 'timestamp', 'first_received_at': NOW.isoformat(),
            'verification': 'issuer_title_match', **extra}


def test_timing_duplicates_negative_material_and_retrospective_receipt(tmp_path, monkeypatch):
    setup_source(tmp_path)
    rows = [news('삼성전자 공급계약 체결'), news('삼성전자 공급계약 체결', source='google_news', url='https://other.example.org/b'),
            news('삼성전자 공급계약 취소', url='https://news.example.com/c'),
            news('삼성전자 주가 급등', url='https://news.example.com/d'),
            news('삼성전자 시설투자', kind='disclosure', url='https://dart.fss.or.kr/a', published_at='2026-11-10', published_precision='date'),
            news('삼성전자 실적 증가', url='https://news.example.com/future', published_at='2026-11-11T00:00:00+09:00')]
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, src, obs, now, deadline: rows if src == 'omni' else [])
    item = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW + timedelta(minutes=1))['items'][0]
    assert len(item['evidence']) == 4
    contract = next(e for e in item['evidence'] if e['title'] == '삼성전자 공급계약 체결')
    assert contract['duplicate_count'] == 2 and contract['timing'] == 'before_observation'
    assert not contract['discovered_after_observation']  # receipt equals quote clock
    assert next(e for e in item['evidence'] if '취소' in e['title'])['direction'] == 'negative'
    assert next(e for e in item['evidence'] if e['kind'] == 'disclosure')['timing'] == 'same_day_unknown'
    assert next(e for e in item['evidence'] if '급등' in e['title'])['category'] == 'price_movement'
    assert item['summary'].endswith('관련 재료 후보')


def test_failed_stage_recovers_without_replaying_completed_sources_or_receipts(tmp_path, monkeypatch):
    setup_source(tmp_path)
    counts = {}
    def collect(self, source, observation, now, deadline):
        counts[source] = counts.get(source, 0) + 1
        if source == 'google_news' and counts[source] == 1:
            raise ValueError('secret=must-never-appear')
        return [news('삼성전자 계약 체결', first_received_at=now.isoformat())] if source == 'omni' else []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    root = tmp_path / 'traces'
    first = service.run_once(root, project_root=tmp_path, now=NOW)
    assert first['status'] == 'partial'
    setup_source(tmp_path, timestamp='2026-11-10T10:05:00')
    second = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=5))
    assert counts == {'omni': 1, 'businesspost': 1, 'google_news': 2, 'dart': 1}
    assert second['items'][0]['evidence'][0]['first_received_at'] == NOW.isoformat()
    assert 'must-never-appear' not in (root / 'snapshot.json').read_text(encoding='utf-8')


def test_read_preserves_artifacts_and_reports_worker_staleness(tmp_path, empty_providers):
    setup_source(tmp_path)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}
    view = service.read_view(root, now=NOW + timedelta(hours=2))
    assert view['status'] == 'stale'
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}


def test_expired_deadline_keeps_pending_work_for_next_tick(tmp_path, empty_providers):
    setup_source(tmp_path)
    view = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW, deadline=0)
    assert view['operation']['pending'] == 1 and view['operation']['processed'] == 0
    assert empty_providers == []


def test_at_most_five_symbols_per_tick_and_pending_symbols_resume(tmp_path, empty_providers):
    source = setup_source(tmp_path)
    rows = [{**source['candidate_pool'][0], 'code': f'{n:06}', 'name': f'회사{n}'} for n in range(1, 7)]
    setup_source(tmp_path, rows=rows)
    (tmp_path / 'data/ticker_to_yahoo_map.csv').write_text(
        'ticker,market,yahoo_ticker,name\n' + ''.join(f'{n:06},KOSPI,{n:06}.KS,회사{n}\n' for n in range(1, 7)), encoding='utf-8')
    root = tmp_path / 'traces'
    first = service.run_once(root, project_root=tmp_path, now=NOW)
    assert first['operation']['processed'] == 5 and first['operation']['pending'] == 1
    second = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=1))
    assert second['operation']['processed'] == 1 and second['operation']['pending'] == 0
    assert len(empty_providers) == 24


def test_successful_stage_refreshes_after_ttl_and_first_receipt_never_changes(tmp_path, monkeypatch):
    setup_source(tmp_path)
    def collect(self, source, observation, now, deadline):
        return [news('삼성전자 계약 체결', first_received_at=now.isoformat())] if source == 'omni' else []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    setup_source(tmp_path, timestamp='2026-11-10T10:15:00')
    second = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=15))
    assert second['operation']['processed'] == 1
    assert second['items'][0]['evidence'][0]['first_received_at'] == NOW.isoformat()
    assert second['items'][0]['evidence'][0]['duplicate_count'] == 1


def test_new_earlier_article_fetched_later_is_explicitly_retrospective(tmp_path, monkeypatch):
    setup_source(tmp_path, timestamp='2026-11-10T09:59:00')
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news('삼성전자 계약 체결')] if source == 'google_news' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['evidence'][0]['timing'] == 'before_observation'
    assert row['evidence'][0]['discovered_after_observation'] is True
    assert 'retrospective_discovery' in row['limitations']


def test_changed_content_cannot_reuse_same_source_timestamp(tmp_path, empty_providers):
    source = setup_source(tmp_path)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    source['candidate_pool'][0]['price'] = 90000
    setup_source(tmp_path, **source)
    view = service.run_once(root, project_root=tmp_path, now=NOW)
    assert view['operation']['source_status'] == 'source_conflict'
    assert view['items'][0]['price'] == 75000


def test_empty_new_scan_clears_display_but_keeps_first_observation(tmp_path, empty_providers):
    setup_source(tmp_path)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    setup_source(tmp_path, rows=[], timestamp='2026-11-10T10:01:00')
    view = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=1))
    assert view['items'] == []
    assert view['status'] == 'no_surge'
    assert len(list((root / 'observations').glob('*.json'))) == 1


def test_new_session_displays_only_current_candidates_and_old_rows_expire(tmp_path, empty_providers):
    source = setup_source(tmp_path)
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    tomorrow = NOW + timedelta(days=1)
    setup_source(tmp_path, rows=[{**source['candidate_pool'][0], 'code': '000660', 'name': 'SK하이닉스'}], timestamp=tomorrow.isoformat())
    view = service.run_once(root, project_root=tmp_path, now=tomorrow)
    assert [row['symbol'] for row in view['items']] == ['000660']
    assert len(list((root / 'observations').glob('*.json'))) == 2
    assert service.read_view(root, now=tomorrow + timedelta(hours=73))['items'] == []


def test_negative_or_speculative_material_is_not_promoted_to_rise_candidate(tmp_path, monkeypatch):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news('삼성전자 공급계약 취소'), news('삼성전자 수주 기대감', url='https://example.com/expectation')]
                        if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['status'] == 'unresolved'
    assert len(row['evidence']) == 2
    assert '취소 관련 재료 후보' not in row['summary']
    assert 'risk_or_opposing_evidence' in row['limitations']


def test_corrupt_saved_snapshot_is_unavailable_without_rewriting(tmp_path):
    root = tmp_path / 'traces'
    root.mkdir()
    path = root / 'snapshot.json'
    path.write_text('{ broken')
    view = service.read_view(root, now=NOW)
    assert view['status'] == 'unavailable'
    assert path.read_text() == '{ broken'


def test_impossible_publication_after_receipt_is_rejected(tmp_path, monkeypatch):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news('삼성전자 계약 체결', first_received_at='2026-11-10T08:00:00+09:00')]
                        if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['evidence'] == [] and row['status'] == 'unresolved'


def test_corrected_headline_replaces_candidate_and_preserves_original_history(tmp_path, monkeypatch):
    setup_source(tmp_path)
    titles = ['삼성전자 공급계약 체결']
    def collect(self, source, obs, now, deadline):
        return [news(title) for title in titles] if source == 'omni' else []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    root = tmp_path / 'traces'
    first = service.run_once(root, project_root=tmp_path, now=NOW)['items'][0]
    titles[:] = ['삼성전자 공급계약 취소']
    setup_source(tmp_path, timestamp='2026-11-10T10:15:00')
    second = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=15))['items'][0]
    assert second['evidence'][0]['title'] == '삼성전자 공급계약 취소'
    assert second['evidence'][0]['id'] != first['evidence'][0]['id']
    assert second['evidence'][0]['timing'] == 'unknown'
    assert second['evidence'][0]['first_received_at'] == '2026-11-10T10:15:00+09:00'
    assert second['status'] == 'unresolved'
    saved = json.loads((root / 'snapshot.json').read_text(encoding='utf-8'))['observations'][first['id']]
    assert saved['_evidence_history'][0]['first_received_at'] == NOW.isoformat()
    titles[:] = ['삼성전자 공급계약 체결']  # stale feed cannot resurrect the original claim
    setup_source(tmp_path, timestamp='2026-11-10T10:30:00')
    third = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=30))['items'][0]
    assert third['evidence'][0]['title'] == '삼성전자 공급계약 취소'


def test_distinct_disclosure_receipts_with_standard_title_are_not_duplicates(tmp_path, monkeypatch):
    setup_source(tmp_path)
    rows = [news('자기주식 취득 결정', kind='disclosure', source='dart', published_precision='date',
                 published_at='2026-11-09', verification='issuer_registry_match',
                 url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261109000001'),
            news('자기주식 취득 결정', kind='disclosure', source='dart', published_precision='date',
                 published_at='2026-11-10', verification='issuer_registry_match',
                 url='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261110000002')]
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline: rows if source == 'dart' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert len(row['evidence']) == 2
    assert {item['timing'] for item in row['evidence']} == {'before_observation', 'same_day_unknown'}


@pytest.mark.parametrize('market_status,expected', [('pre_market', 'historical'), ('unknown', 'unavailable')])
def test_non_open_market_status_never_claims_freshness(tmp_path, empty_providers, market_status, expected):
    setup_source(tmp_path, market_status=market_status)
    view = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)
    assert view['operation']['source_status'] == expected


@pytest.mark.parametrize('title', ['삼성전자 공급계약 해지', '삼성전자 수주 실패', '삼성전자 영업이익 급감'])
def test_unambiguous_adverse_events_never_become_prior_material(tmp_path, monkeypatch, title):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news(title)] if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['evidence'][0]['direction'] == 'negative'
    assert row['status'] == 'unresolved'


def test_correction_from_suppressed_duplicate_origin_retires_original_claim(tmp_path, monkeypatch):
    setup_source(tmp_path)
    corrected = [False]
    def collect(self, source, obs, now, deadline):
        if source == 'omni':
            return [news('삼성전자 공급계약 체결')]
        if source == 'google_news':
            return [news('삼성전자 공급계약 취소' if corrected[0] else '삼성전자 공급계약 체결',
                         source='google_news', url='https://other.example.org/duplicate')]
        return []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    root = tmp_path / 'traces'
    first = service.run_once(root, project_root=tmp_path, now=NOW)['items'][0]
    assert len(first['evidence']) == 1 and first['evidence'][0]['duplicate_count'] == 2
    corrected[0] = True
    setup_source(tmp_path, timestamp='2026-11-10T10:15:00')
    row = service.run_once(root, project_root=tmp_path, now=NOW + timedelta(minutes=15))['items'][0]
    assert len(row['evidence']) == 1 and row['evidence'][0]['title'] == '삼성전자 공급계약 취소'
    assert row['evidence'][0]['timing'] == 'unknown' and row['status'] == 'unresolved'


def test_later_oil_price_stock_report_is_post_report_not_prior_cause(tmp_path, monkeypatch):
    source = setup_source(tmp_path)
    row = {**source['candidate_pool'][0], 'code': '003490', 'name': '대한항공'}
    setup_source(tmp_path, rows=[row], timestamp='2026-11-10T15:48:15.876704', market_status='closed')
    (tmp_path / 'data/ticker_to_yahoo_map.csv').write_text(
        'ticker,market,yahoo_ticker,name\n003490,KOSPI,003490.KS,대한항공\n', encoding='utf-8')
    received = '2026-11-10T18:49:00+09:00'
    reports = [news('국제유가 급락에 항공주 급등, 대한항공 11% 상승', source='google_news',
                    publisher='스페셜타임스', published_at='2026-11-10T16:06:43+09:00', first_received_at=received),
               news('정말 냉철하네 "대한항공 이겼다고 자축하고 있을 수 없다" [대전 현장]', source='google_news',
                    publisher='스포츠조선', url='https://example.com/sports',
                    published_at='2026-11-10T18:28:27+09:00', first_received_at=received)]
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline: reports if source == 'google_news' else [])
    item = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=datetime.fromisoformat(received))['items'][0]
    assert len(item['evidence']) == 1
    assert item['evidence'][0]['category'] == 'reported_driver'
    assert item['evidence'][0]['timing'] == 'after_observation'
    assert item['status'] == 'post_report'
    assert '재료 후보' not in item['summary'] and '사후 보도' in item['summary']


@pytest.mark.parametrize('title', [
    "'젠슨 황 스캔들 파장'에 미국의 중국 반도체 규제 강화되나, 삼성전자·SK하이닉스 메모리 영향 '촉각'",
    '삼성전자 신규 공급계약 체결되나',
    '삼성전자 반도체 허가 받을까?',
    '삼성전자 공급계약 무산 우려',
    '삼성전자 반도체 규제 강화',
    '삼성전자 수출통제 강화 영향 촉각',
    '중국 관영매체 "삼성전자 SK하이닉스 중국 반도체 공장 역할 중요, 미국 규제로 한국 기업 피해"',
    '삼성전자 “반도체 소부장 2027년 실적 성장성 봐야”…주목',
    '삼성전자 내년 실적 성장',
    '삼성전자 내년 영업이익 100조로 증가',
])
def test_uncertainty_and_regulatory_risk_cannot_become_upward_material(tmp_path, monkeypatch, title):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news(title)] if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['status'] == 'unresolved'
    assert '관련 재료 후보' not in row['summary']
    assert row['evidence'][0]['category'] == 'opinion' or row['evidence'][0]['direction'] in {'negative', 'mixed'}


@pytest.mark.parametrize('title', ['삼성전자 공급계약 체결', '삼성전자 영업이익 426%↑', '삼성전자 반도체 규제 완화 확정',
                                  '삼성전자 내년 시설투자 승인'])
def test_factual_positive_events_survive_conservative_filter(tmp_path, monkeypatch, title):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news(title)] if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['status'] == 'prior_material'
    assert row['evidence'][0]['direction'] not in {'negative', 'mixed'}


def test_neutral_material_remains_evidence_but_not_an_upward_driver(tmp_path, monkeypatch):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news('삼성전자 반도체 공장 규제 논의')] if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert len(row['evidence']) == 1 and row['evidence'][0]['direction'] == 'neutral'
    assert row['status'] == 'unresolved'


@pytest.mark.parametrize('title,expected', [
    ('삼성전자, 국제유가 급락에 주가 상승세', 'reported_driver'),
    ('삼성전자 주가 급등...환율 하락 영향', 'price_movement'),
    ('삼성전자, 금리 인하에 주가 강세', 'reported_driver'),
    ('삼성전자 주가 11% 급등', 'price_movement'),
    ('삼성전자, 유가 하락에도 주가 급등', 'price_movement'),
    ('삼성전자, 유가 하락과 주가 급등', 'price_movement'),
    ('금리 인하에 채권 상승, 삼성전자 투자자 관심', 'other'),
    ('삼성전자 투자자 관심, 유가 하락에 금값 급등', 'price_movement'),
    ('유가 하락, 삼성전자 주가 급등...주주 영향', 'price_movement'),
    ('금리 인하에 은행주 상승, 삼성전자 보합', 'other'),
    ('삼성전자 실적 발표, 금리 인하에 은행주 강세', 'earnings'),
    ('삼성전자 등 반도체주, 금리 인하에 급등', 'reported_driver'),
    ('삼성전자 실적 발표…국제유가 급락에 대한항공 급등', 'earnings'),
    ('삼성전자 실적 발표, 국제유가 급락에 대한항공 급등', 'earnings'),
    ('삼성전자 실적 발표 국제유가 급락에 대한항공 급등', 'earnings'),
    ('삼성전자, 국제유가 급락에 대한항공 급등', 'price_movement'),
    ('삼성전자 공급망 점검 금리 인하에 현대차 상승', 'other'),
    ('삼성전자 급등…국제유가 급락에 대한항공 급등', 'price_movement'),
    ('국제유가 급락에 대한항공 급등, 삼성전자 급등', 'price_movement'),
])
def test_reported_driver_requires_explicit_reported_link_not_sector_inference(tmp_path, monkeypatch, title, expected):
    setup_source(tmp_path)
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news(title)] if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['evidence'][0]['category'] == expected
    if expected == 'reported_driver':
        assert row['status'] == 'prior_material'
        assert row['evidence'][0]['direction'] == 'neutral'
        assert '보도된 상승 배경' in row['summary']
    else:
        assert row['status'] == 'unresolved'


def test_same_day_reported_driver_is_preferred_to_other_event_title(tmp_path, monkeypatch):
    setup_source(tmp_path)
    reports = [news('삼성전자 시설투자', url='https://example.com/capacity'),
               news('삼성전자 공급계약 체결', url='https://example.com/contract'),
               news('삼성전자, 국제유가 급락에 주가 상승세', url='https://example.com/oil')]
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        reports if source == 'omni' else [])
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert '국제유가' in row['summary'] and '보도된 상승 배경' in row['summary']


def test_read_reclassifies_saved_risk_without_calls_writes_or_clock_changes(tmp_path, monkeypatch):
    source = setup_source(tmp_path)
    setup_source(tmp_path, rows=[{**source['candidate_pool'][0], 'code': '000660', 'name': 'SK하이닉스'}])
    title = "'젠슨 황 스캔들 파장'에 미국의 중국 반도체 규제 강화되나, 삼성전자·SK하이닉스 메모리 영향 '촉각'"
    monkeypatch.setattr(sources.EvidenceSources, 'collect', lambda self, source, obs, now, deadline:
                        [news(title)] if source == 'omni' else [])
    root = tmp_path / 'traces'
    service.run_once(root, project_root=tmp_path, now=NOW)
    path = root / 'snapshot.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    original = next(iter(saved['observations'].values()))
    original['evidence'][0].update(category='regulatory', direction='neutral')
    original.update(status='prior_material', summary=title + ' 관련 재료 후보')
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}
    def forbidden(*args, **kwargs):
        raise AssertionError('read_view must not fetch')
    monkeypatch.setattr(sources.EvidenceSources, 'collect', forbidden)
    row = service.read_view(root, now=NOW + timedelta(minutes=1))['items'][0]
    assert row['status'] == 'unresolved'
    assert row['evidence'][0]['category'] == 'opinion' and row['evidence'][0]['direction'] == 'negative'
    assert (row['id'], row['first_detected_at'], row['price_observed_at']) == (
        original['id'], original['first_detected_at'], original['price_observed_at'])
    for key in ('id', 'published_at', 'first_received_at', 'timing', 'discovered_after_observation'):
        assert row['evidence'][0][key] == original['evidence'][0][key]
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}


def test_missing_disclosure_issuer_mapping_is_an_explicit_coverage_limitation(tmp_path, monkeypatch):
    setup_source(tmp_path)
    def collect(self, source, obs, now, deadline):
        if source == 'dart':
            raise sources.SourceUnavailable('issuer_mapping_unavailable')
        return []
    monkeypatch.setattr(sources.EvidenceSources, 'collect', collect)
    row = service.run_once(tmp_path / 'traces', project_root=tmp_path, now=NOW)['items'][0]
    assert row['status'] == 'source_incomplete'
    assert 'issuer_mapping_unavailable' in row['limitations']


@pytest.mark.parametrize('title', [
    '국제유가 급락에 대한항공 등 항공주 급등',
    '[ET특징주]대한항공, 국제유가 급락에 상승세',
    '[특징주] 국제유가 급락에 항공주 급등…대한항공 9%대↑',
])
def test_actual_oil_headline_formats_link_the_named_issuer_to_the_upward_reaction(title):
    item = service._evidence(news(title), {'name': '대한항공', 'price_observed_at': NOW.isoformat()}, NOW)
    assert item['category'] == 'reported_driver' and item['direction'] == 'neutral'
