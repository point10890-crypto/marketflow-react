"""Boundary fixtures exercise retained archives and actual cache persistence."""
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3

import pytest


NOW = datetime.fromisoformat('2026-11-11T15:00:00+09:00')


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def listing(root):
    path = root / 'data/ticker_to_yahoo_map.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('ticker,name,market\n005930,삼성전자,KOSPI\n000660,SK하이닉스,KOSPI\n', encoding='utf-8')


def article(**changes):
    return dict(id='100', title='삼성전자, 반도체 공급 계약 체결',
                url='https://www.businesspost.co.kr/BP?command=article_view&num=100',
                published_at='2026-10-01T09:00:00+09:00', first_seen_at='2026-10-01T10:00:00+09:00',
                provenance='businesspost_rss', entities=[dict(symbol='005930', name='삼성전자')],
                event=dict(type='contract', certainty='reported_unverified'), **changes)


def task(row, **changes):
    value = dict(article_id=row['id'], article_title=row['title'], article_url=row['url'],
                 article_published_at=row['published_at'], first_seen_at=row.get('first_seen_at'),
                 first_seen_source=row.get('provenance'), symbol='005930', name='삼성전자',
                 primary=dict(status='verified_numeric_claims', checked_at='2026-10-02T11:00:00+09:00'),
                 price=dict(status='verified'), checked_at='2026-10-02T11:00:00+09:00')
    return {**value, **changes}


def database(root, tasks=(), omni=()):
    path = root / 'data/kongming_article_candidates/verification.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE tasks (active INTEGER, payload TEXT)')
        con.executemany('INSERT INTO tasks VALUES (?, ?)', [(active, json.dumps(row)) for active, row in tasks])
    path = root / 'data/omni/omni.db'
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute('CREATE TABLE news_events (title TEXT, summary TEXT, link TEXT, source TEXT, published_ts, collected_at TEXT, symbols TEXT)')
        con.executemany('INSERT INTO news_events VALUES (:title,:summary,:link,:source,:published_ts,:collected_at,:symbols)', omni)


def empty_snapshots(root):
    write_json(root / 'data/kongming_article_candidates/snapshot.json', dict(items=[]))
    write_json(root / 'data/surge_trace/snapshot.json', dict(observations={}))


def test_inactive_tasks_snapshot_syndication_merge_earliest_receipt_and_current_verification(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    row = article()
    old = task(row, first_seen_at='2026-10-01T00:30:00Z')
    newer = task(row, first_seen_at='2026-10-03T10:00:00+09:00',
                 primary=dict(status='pending'), checked_at='2026-10-03T10:00:00+09:00')
    database(tmp_path, tasks=[(0, old), (1, newer)])
    empty_snapshots(tmp_path)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row]))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 1
    event = events[0]
    assert event['symbol'] == '005930'
    assert event['first_seen_at'] == '2026-10-01T09:30:00+09:00'
    assert event['anchor_at'] == event['first_seen_at']
    assert event['analysis_basis'] == 'received'
    assert event['verification'] == 'verified_numeric_claims'
    assert event['verification_at'] == '2026-10-02T11:00:00+09:00'
    assert set(event) == {'id', 'symbol', 'name', 'title', 'url', 'source', 'event_type',
                          'published_at', 'first_seen_at', 'anchor_at', 'analysis_basis',
                          'verification', 'verification_at'}
    assert diag['deduplicated'] == 2
    assert diag['source_counts']['verification'] == 2


def test_omni_numeric_naive_publication_uses_recorded_aware_receipt_and_all_rows(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    base = dict(title='삼성전자, 배당 확대', summary='', link='https://news.example.com/1',
                source='통신사', published_ts=1791000000, collected_at='2026-10-03T02:00:00Z',
                symbols='["005930"]')
    other = {**base, 'title': '삼성전자, 대규모 설비투자', 'link': 'https://news.example.com/2',
             'published_ts': '2026-10-03T09:00:00'}
    database(tmp_path, omni=[base, other])
    empty_snapshots(tmp_path)
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 2
    assert all(row['published_at'] is None and row['analysis_basis'] == 'received' for row in events)
    assert {row['anchor_at'] for row in events} == {'2026-10-03T11:00:00+09:00'}
    assert diag['invalid']['published_at'] == 2


def test_import_and_missing_receipt_remain_retrospective_without_invented_receipt(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    archive = {**article(), 'provenance': 'kongming_archive'}
    missing = {**article(), 'id': '101', 'title': '삼성전자, 영업이익 증가',
               'url': None, 'first_seen_at': None}
    database(tmp_path)
    empty_snapshots(tmp_path)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[archive, missing]))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 2
    assert all(row['analysis_basis'] == 'retrospective' for row in events)
    missing_result = next(row for row in events if row['url'] is None)
    assert missing_result['first_seen_at'] is None
    assert missing_result['anchor_at'] == '2026-10-01T09:00:00+09:00'


def test_rejects_unsafe_url_identity_sports_generic_future_and_withdrawn(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    base = article()
    rows = [
        {**base, 'url': 'http://127.0.0.1/private'},
        {**base, 'entities': [dict(symbol='000660', name='삼성전자')]},
        {**base, 'title': '삼성전자 배구팀 승리', 'event': None},
        {**base, 'title': '삼성전자 직원 취미 이야기', 'event': None},
        {**base, 'first_seen_at': '2026-11-12T09:00:00+09:00'},
        {**base, 'withdrawn': True},
    ]
    database(tmp_path)
    empty_snapshots(tmp_path)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=rows))
    events, diag = load_events(tmp_path, NOW)
    assert events == []
    assert all(diag['invalid'].get(key, 0) > 0 for key in ('unsafe_url', 'identity', 'sports', 'non_material', 'future_timestamp', 'withdrawn'))


def test_alphanumeric_listing_symbol_is_explicitly_excluded_until_downstream_support(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    with (tmp_path / 'data/ticker_to_yahoo_map.csv').open('a', encoding='utf-8') as handle:
        handle.write('12345A,테스트기업,KOSPI\n')
    database(tmp_path)
    empty_snapshots(tmp_path)
    row = {**article(), 'title': '테스트기업, 공급 계약 체결',
           'entities': [{'symbol': '12345A', 'name': '테스트기업'}]}
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row]))
    events, diag = load_events(tmp_path, NOW)
    assert events == []
    assert diag['invalid']['unsupported_symbol'] == 1


def test_surge_retains_history_but_excludes_withdrawn_and_deduplicates_syndication(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    database(tmp_path)
    empty_snapshots(tmp_path)
    common = dict(kind='news', source='google_news', title='삼성전자, 자사주 소각',
                  url='https://news.example.com/3?utm_source=abc', published_at='2026-10-03T09:00:00+09:00',
                  first_received_at='2026-10-03T10:00:00+09:00', verification='issuer_title_match')
    observation = dict(symbol='005930', name='삼성전자', market='KOSPI', evidence=[common],
                       _evidence_history=[{**common, 'title': '삼성전자, 반도체 공장 증설', 'url': 'https://news.example.com/4'}])
    write_json(tmp_path / 'data/surge_trace/snapshot.json', dict(observations={'old': observation}))
    duplicate = {**article(), 'title': common['title'], 'url': 'https://news.example.org/syndicated',
                 'published_at': common['published_at'], 'first_seen_at': '2026-10-03T12:00:00+09:00'}
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[duplicate]))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 2
    assert diag['deduplicated'] == 1
    assert next(row for row in events if '소각' in row['title'])['first_seen_at'] == '2026-10-03T10:00:00+09:00'


def test_missing_source_is_explicit_partial_and_naive_receipt_not_silently_localized(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    row = {**article(), 'first_seen_at': '2026-10-01T10:00:00'}
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row]))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 1
    assert events[0]['analysis_basis'] == 'retrospective'
    assert events[0]['first_seen_at'] is None
    assert diag['status'] == 'partial'
    assert diag['sources']['verification']['status'] == 'unavailable'


def test_withdrawn_publisher_tombstone_excludes_old_inactive_verification(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    row = article()
    database(tmp_path, tasks=[(0, task(row))])
    empty_snapshots(tmp_path)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[{**row, 'withdrawn': True}]))
    events, diag = load_events(tmp_path, NOW)
    assert events == []
    assert diag['invalid']['withdrawn'] >= 1


def test_withdrawn_keys_survive_json_and_match_persisted_url_or_syndicated_title(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events, is_withdrawn
    listing(tmp_path)
    database(tmp_path)
    empty_snapshots(tmp_path)
    row = article()
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row]))
    before, _ = load_events(tmp_path, NOW)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[{**row, 'withdrawn': True}]))
    after, diag = load_events(tmp_path, NOW)
    saved = json.loads(json.dumps({'withdrawn_keys': diag['withdrawn_keys']}))
    assert after == []
    assert is_withdrawn(before[0], saved)
    assert is_withdrawn({**before[0], 'url': 'https://news.example.com/syndicated'}, saved)
    assert is_withdrawn({**before[0], 'title': '삼성전자 수정 제목',
                         'url': 'https://m.businesspost.co.kr/BP?num=100&command=article_view&utm_source=x'}, saved)
    assert not is_withdrawn({**before[0], 'symbol': '000660'}, saved)
    assert not is_withdrawn(before[0], {})
    # The caller persists this diagnostic even after publisher retention drops
    # the tombstone itself; matching must not depend on a new source read.
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[]))
    assert is_withdrawn(before[0], saved)


def test_earlier_receipt_keeps_aliases_for_ledger_id_reconciliation(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events, event_keys
    listing(tmp_path)
    database(tmp_path)
    empty_snapshots(tmp_path)
    row = article()
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row]))
    before, _ = load_events(tmp_path, NOW)
    earlier = {**row, 'url': 'https://news.example.com/earlier', 'first_seen_at': '2026-10-01T09:30:00+09:00'}
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[row, earlier]))
    after, diag = load_events(tmp_path, NOW)
    assert len(after) == 1
    assert after[0]['first_seen_at'] == '2026-10-01T09:30:00+09:00'
    aliases = {tuple(key) for key in diag['identity_aliases'][after[0]['id']]}
    assert set(event_keys(before[0])) <= aliases
    assert ('005930', 'url', 'https://news.example.com/earlier') in aliases


def test_financial_signs_distinguish_syndicated_events_and_verification(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    positive = {**article(), 'title': '삼성전자, 영업이익 +100억', 'url': 'https://news.example.com/positive'}
    negative = {**article(), 'title': '삼성전자, 영업이익 -100억', 'url': 'https://news.example.com/negative'}
    database(tmp_path, tasks=[(1, task(positive))])
    empty_snapshots(tmp_path)
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json', dict(items=[negative]))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 2
    assert diag['deduplicated'] == 0
    assert next(row for row in events if '-100' in row['title'])['verification'] == 'issuer_symbol_and_title_match'


def test_financial_decimals_distinguish_events_fallback_ids_and_withdrawal_keys(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events, is_withdrawn
    listing(tmp_path)
    one = {**article(), 'title': '삼성전자, 매출 1.0조', 'url': None}
    ten = {**article(), 'title': '삼성전자, 매출 10조', 'url': None}
    database(tmp_path)
    empty_snapshots(tmp_path)
    path = tmp_path / 'data/kongming_article_candidates/snapshot.json'
    write_json(path, dict(items=[one, ten]))
    events, _ = load_events(tmp_path, NOW)
    assert len(events) == 2
    assert len({row['id'] for row in events}) == 2
    withdrawn = {**one, 'url': 'https://news.example.com/one', 'withdrawn': True}
    write_json(path, dict(items=[withdrawn, ten]))
    remaining, diag = load_events(tmp_path, NOW)
    assert len(remaining) == 1 and remaining[0]['title'] == '삼성전자, 매출 10조'
    assert is_withdrawn(next(row for row in events if '1.0' in row['title']), diag)
    assert not is_withdrawn(next(row for row in events if '10조' in row['title']), diag)


def test_all_retained_tasks_exceed_display_limit_and_sql_bound_is_explicit(tmp_path, monkeypatch):
    from app.services.catalyst_outcomes import sources
    listing(tmp_path)
    rows = []
    for number in range(751):
        row = {**article(), 'id': str(1000 + number), 'title': f'삼성전자, 제{number} 공급 계약',
               'url': f'https://news.example.com/{number}'}
        rows.append((0, task(row)))
    database(tmp_path, tasks=rows)
    empty_snapshots(tmp_path)
    events, diag = sources.load_events(tmp_path, NOW)
    assert len(events) == 751
    assert diag['truncated'] is False
    monkeypatch.setattr(sources, 'MAX_DATABASE_ROWS', 100)
    events, diag = sources.load_events(tmp_path, NOW)
    assert len(events) == 100
    assert diag['truncated'] is True
    assert diag['sources']['verification']['status'] == 'partial'


def test_bad_rows_and_failed_feed_preserve_other_valid_events_with_partial_diagnostic(tmp_path):
    from app.services.catalyst_outcomes.sources import load_events
    listing(tmp_path)
    database(tmp_path)
    empty_snapshots(tmp_path)
    rows = [article(), {**article(), 'verification': {'unexpected': True}},
            {**article(), 'status': []}, {**article(), 'event': {'type': []}},
            {**article(), 'publisher': ['unexpected']}]
    write_json(tmp_path / 'data/kongming_article_candidates/snapshot.json',
               dict(items=rows, feeds={'feed': {'state': 'error'}}))
    events, diag = load_events(tmp_path, NOW)
    assert len(events) == 1
    assert diag['status'] == 'partial'
    assert diag['sources']['businesspost']['status'] == 'partial'


def write_prices(root, rows):
    path = root / 'data/chart_analogue/closed_prices.csv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['ticker', 'date', 'name', 'current_price', 'update_time', 'price_basis', 'source_id', 'collection_status'])
        writer.writeheader()
        writer.writerows(rows)


def close_row(day='2026-11-09', **changes):
    return {**dict(ticker='005930', date=day, name='삼성전자', current_price='100',
                   update_time='2026-11-10 15:45:00', price_basis='provider_adjusted',
                   source_id='naver_closed_daily', collection_status='fresh'), **changes}


def test_closes_filter_symbols_future_and_intraday_sampling_without_global_timestamp(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes
    write_prices(tmp_path, [close_row(), close_row('20261110', update_time='2026-11-10 15:45:00'),
                           close_row('2026-11-11', update_time='2026-11-11 10:00:00'),
                           close_row('2026-11-12', update_time='2026-11-11 10:00:00'),
                           close_row('2026-11-08', update_time='2026-11-12 10:00:00'),
                           close_row('2026-11-07', update_time='2026-11-10 11:00:00'),
                           close_row(ticker='000660')])
    values, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert list(values) == ['005930']
    assert [row['date'] for row in values['005930']] == ['2026-11-07', '2026-11-09', '2026-11-10']
    assert values['005930'][0]['fetched_at'] == '2026-11-10T11:00:00+09:00'
    assert values['005930'][1]['fetched_at'] == '2026-11-10T15:45:00+09:00'
    assert diag['finality_verified'] is False
    assert diag['historical_vintage_verified'] is False
    assert diag['invalid']['same_day_or_future_session'] == 2
    assert diag['invalid']['future_capture'] == 1


def test_closes_conflicts_drop_day_and_bad_provenance_is_not_used(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes
    write_prices(tmp_path, [close_row(), close_row(current_price='102'), close_row(),
                           close_row('2026-11-08', source_id='unknown'),
                           close_row('2026-11-07', collection_status='failed'),
                           close_row('2026-11-06', current_price='NaN'),
                           close_row('2026-11-05', update_time='2026-11-04T12:00:00+09:00')])
    values, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert values == {}
    assert diag['invalid']['duplicate_conflict'] >= 1
    assert diag['invalid']['provenance'] == 2
    assert diag['status'] == 'unavailable'


def test_full_csv_calendar_exposes_requested_symbol_gap_without_claiming_verified_calendar(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes, calendar_window_verified
    write_prices(tmp_path, [close_row('2026-11-06'), close_row('2026-11-10'),
                           close_row('2026-11-09', ticker='000660')])
    values, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert [row['date'] for row in values['005930']] == ['2026-11-06', '2026-11-10']
    assert diag['calendar_sessions'] == ['2026-11-06', '2026-11-09', '2026-11-10']
    assert diag['calendar_verified'] is False
    assert not calendar_window_verified(diag, '2026-11-06', '2026-11-10')


def test_saved_official_calendar_exposes_entire_csv_gap_and_verifies_only_covered_range(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes, calendar_window_verified
    write_prices(tmp_path, [close_row('2026-11-06'), close_row('2026-11-10')])
    days = {f'2026-11-{number:02d}': dict(is_open=number not in {7, 8},
            captured_at='2026-11-11T09:00:00+09:00', source='KRX:official-holiday-schedule')
            for number in range(6, 11)}
    write_json(tmp_path / 'data/kongming_article_candidates/price_calendar.json',
               dict(source='KIS:CTCA0903R', days=days))
    _, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert diag['calendar_sessions'] == ['2026-11-06', '2026-11-09', '2026-11-10']
    assert diag['calendar_confirmed_days']['2026-11-07'] is False
    assert diag['calendar_verified'] is True
    assert calendar_window_verified(diag, '2026-11-06', '2026-11-10')
    assert not calendar_window_verified(diag, '2026-11-05', '2026-11-10')


def test_calendar_missing_or_future_captures_and_conflicts_cannot_certify_a_window(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes, calendar_window_verified
    write_prices(tmp_path, [close_row('2026-11-09'), close_row('2026-11-10')])
    days = {'2026-11-09': dict(is_open=False, captured_at='2026-11-11T09:00:00+09:00', source='KIS:CTCA0903R'),
            '2026-11-10': dict(is_open=True, captured_at='2026-11-12T09:00:00+09:00', source='KIS:CTCA0903R')}
    write_json(tmp_path / 'data/kongming_article_candidates/price_calendar.json',
               dict(source='KIS:CTCA0903R', days=days))
    _, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert diag['calendar_conflicts'] == ['2026-11-09']
    assert diag['calendar_verified'] is False
    assert not calendar_window_verified(diag, '2026-11-09', '2026-11-10')


def test_sealed_symbol_calendar_is_reused_with_hash_and_source_validation(tmp_path):
    from app.services.catalyst_outcomes.prices import load_closes, calendar_window_verified
    from app.services.mirofish.alpha_lab import store
    write_prices(tmp_path, [close_row('2026-11-09'), close_row('2026-11-10')])
    value = dict(source='KIS:CTCA0903R', captured_at='2026-11-11T09:00:00+09:00',
                 days=[dict(date='2026-11-09', is_open=True), dict(date='2026-11-10', is_open=True)])
    path = tmp_path / 'data/admin_mirofish/symbol_alpha/005930/sources/calendar.json'
    write_json(path, dict(data=value, sha256=store._hash(value)))
    _, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert calendar_window_verified(diag, '2026-11-09', '2026-11-10')
    write_json(path, dict(data={**value, 'captured_at': '2026-11-10T23:00:00+09:00'}, sha256=store._hash(value)))
    _, diag = load_closes(tmp_path, {'005930'}, NOW)
    assert not calendar_window_verified(diag, '2026-11-09', '2026-11-10')


def test_calendar_acquisition_is_bounded_persistent_and_resumes_only_missing_days(tmp_path):
    from app.services.catalyst_outcomes.prices import acquire_calendar, calendar_window_verified
    class Provider:
        def __init__(self):
            self.calls = []
        def fetch_calendar(self, base_date):
            self.calls.append(base_date)
            day = datetime.fromisoformat(base_date)
            rows = [dict(date=(day + timedelta(days=offset)).date().isoformat(),
                         is_open=(day + timedelta(days=offset)).weekday() < 5) for offset in range(2)]
            return dict(source='KIS:CTCA0903R', captured_at='2026-11-11T09:00:00+09:00',
                        days=rows, secret='do_not_persist')
    provider = Provider()
    first = acquire_calendar(tmp_path, '2026-11-04', '2026-11-10', NOW, provider=provider)
    assert first['requests'] == 3
    assert not calendar_window_verified(first, '2026-11-04', '2026-11-10')
    original = json.loads((tmp_path / 'calendar.json').read_text(encoding='utf-8'))['days']['2026-11-04']
    second = acquire_calendar(tmp_path, '2026-11-04', '2026-11-10', NOW, provider=provider)
    assert provider.calls == ['2026-11-04', '2026-11-06', '2026-11-08', '2026-11-10']
    assert calendar_window_verified(second, '2026-11-04', '2026-11-10')
    assert '2026-11-11' not in second['calendar_confirmed_days']
    saved = (tmp_path / 'calendar.json').read_text(encoding='utf-8')
    assert 'do_not_persist' not in saved
    assert json.loads(saved)['days']['2026-11-04'] == original
    third = acquire_calendar(tmp_path, '2026-11-04', '2026-11-10', NOW, provider=provider)
    assert third['requests'] == 0


def test_calendar_acquisition_preserves_success_on_later_failure_and_rejects_future_capture(tmp_path):
    from app.services.catalyst_outcomes.prices import acquire_calendar
    class Provider:
        def fetch_calendar(self, base_date):
            if base_date == '2026-11-09':
                return dict(source='KIS:CTCA0903R', captured_at='2026-11-11T09:00:00+09:00',
                            days=[dict(date=base_date, is_open=True)])
            raise RuntimeError('token=secret')
    result = acquire_calendar(tmp_path, '2026-11-09', '2026-11-10', NOW, provider=Provider())
    assert result['calendar_confirmed_days'] == {'2026-11-09': True}
    assert result['status'] == 'partial'
    assert 'secret' not in json.dumps(result)
    class Future:
        def fetch_calendar(self, base_date):
            return dict(source='KIS:CTCA0903R', captured_at='2026-11-12T09:00:00+09:00',
                        days=[dict(date=base_date, is_open=True)])
    result = acquire_calendar(tmp_path, '2026-11-09', '2026-11-10', NOW, provider=Future())
    assert result['calendar_confirmed_days'] == {'2026-11-09': True}
    assert result['calendar_verified'] is False


def test_calendar_seed_conflicts_remain_unverified_across_cache_reload(tmp_path):
    from app.services.catalyst_outcomes.prices import acquire_calendar, calendar_window_verified
    seed = dict(calendar_day_evidence={'2026-11-10': dict(is_open=True, source='KIS:CTCA0903R',
                captured_at='2026-11-11T09:00:00+09:00')}, calendar_conflicts=['2026-11-10'])
    first = acquire_calendar(tmp_path, '2026-11-10', '2026-11-10', NOW, seed=seed, max_fetch=0)
    assert first['calendar_conflicts'] == ['2026-11-10']
    assert first['calendar_verified'] is False
    assert not calendar_window_verified(first, '2026-11-10', '2026-11-10')
    second = acquire_calendar(tmp_path, '2026-11-10', '2026-11-10', NOW, max_fetch=0)
    assert second['calendar_conflicts'] == ['2026-11-10']
    assert second['pending_calendar_days'] == 1
    assert second['calendar_sessions'] == []


def test_calendar_seed_conflict_without_evidence_is_persisted_and_not_reconfirmed(tmp_path):
    from app.services.catalyst_outcomes.prices import acquire_calendar
    first = acquire_calendar(tmp_path, '2026-11-10', '2026-11-10', NOW,
                             seed=dict(calendar_conflicts=['2026-11-10']), max_fetch=0)
    assert first['calendar_conflicts'] == ['2026-11-10']
    class Provider:
        def fetch_calendar(self, base_date):
            return dict(source='KIS:CTCA0903R', captured_at='2026-11-11T09:00:00+09:00',
                        days=[dict(date=base_date, is_open=True)])
    second = acquire_calendar(tmp_path, '2026-11-10', '2026-11-10', NOW, provider=Provider())
    assert second['calendar_conflicts'] == ['2026-11-10']
    assert second['calendar_verified'] is False


def provider_value(symbol='005930', end='2026-11-10', **changes):
    from app.services.mirofish.alpha_lab.daily_source import SOURCE_CONTRACT
    return {**dict(symbol=symbol, bars=[dict(symbol=symbol, date=end, open=100, high=110, low=90,
                     close=105, volume=1000, traded_value=105000, tradable=True, quality_flags=[], source_flags={})],
                  source=SOURCE_CONTRACT.copy(), captured_at='2026-11-11T09:00:00+09:00',
                  capture=dict(first='2026-11-11T09:00:00+09:00', last='2026-11-11T09:00:00+09:00'),
                  history_status='insufficient_history', pages=[dict(secret='must_not_persist')]), **changes}


def test_current_prices_reuse_success_same_session_and_retry_failures_only(tmp_path):
    from app.services.catalyst_outcomes.prices import load_current_prices
    class Provider:
        def __init__(self):
            self.calls = []
        def fetch_history(self, symbol, end_session, *, count):
            self.calls.append((symbol, end_session, count))
            if symbol == '000660' and self.calls.count((symbol, end_session, count)) == 1:
                raise RuntimeError('contains secret token')
            return provider_value(symbol, end_session)
    provider = Provider()
    root = tmp_path / 'output'
    first, diag = load_current_prices(tmp_path, ['005930', '000660'], '2026-11-10', NOW, root, provider=provider)
    assert set(first) == {'005930'}
    assert diag['pending_symbols'] == ['000660']
    second, diag = load_current_prices(tmp_path, ['005930', '000660'], '2026-11-10', NOW, root, provider=provider)
    assert set(second) == {'005930', '000660'}
    assert provider.calls == [('005930', '2026-11-10', 100), ('000660', '2026-11-10', 100), ('000660', '2026-11-10', 100)]
    saved = (root / 'prices/005930.json').read_text(encoding='utf-8')
    assert 'must_not_persist' not in saved and 'pages' not in json.loads(saved)
    assert second['005930']['source']['provider'] == 'KIS'
    assert second['005930']['finality_verified'] is False


def test_current_prices_bound_fetches_and_reject_mismatched_or_future_provider_data(tmp_path):
    from app.services.catalyst_outcomes.prices import load_current_prices
    class Provider:
        def fetch_history(self, symbol, end_session, *, count):
            return provider_value('000660' if symbol == '005930' else symbol,
                                  end_session, captured_at='2026-11-12T09:00:00+09:00')
    values, diag = load_current_prices(tmp_path, ['005930', '000660'], '2026-11-10', NOW,
                                      tmp_path / 'output', provider=Provider(), max_fetch=1)
    assert values == {}
    assert diag['pending_symbols'] == ['005930', '000660']
    assert diag['fetched'] == 1
    assert not list((tmp_path / 'output').glob('prices/*.json'))


def test_current_prices_same_day_session_is_not_requested_before_cutoff(tmp_path):
    from app.services.catalyst_outcomes.prices import load_current_prices
    class Provider:
        def fetch_history(self, *args, **kwargs):
            pytest.fail('must not request unfinished session')
    values, diag = load_current_prices(tmp_path, ['005930'], '2026-11-11', NOW,
                                      tmp_path / 'output', provider=Provider())
    assert values == {}
    assert diag['status'] == 'unavailable'
    assert diag['errors']['session'] == 'daily_session_incomplete'


def test_live_current_prices_validate_actual_response_time_after_start_clock(tmp_path, monkeypatch):
    from app.services.catalyst_outcomes import prices
    later = NOW + timedelta(seconds=2)
    class Provider:
        def fetch_history(self, symbol, end_session, *, count):
            return provider_value(symbol, end_session, captured_at=later.isoformat(),
                                  capture=dict(first=later.isoformat(), last=later.isoformat()))
    monkeypatch.setattr(prices, 'KISDailyProvider', Provider)
    monkeypatch.setattr(prices, 'clock', lambda value=None: value if value is not None else later)
    values, diag = prices.load_current_prices(tmp_path, ['005930'], '2026-11-10', NOW, tmp_path / 'output')
    assert set(values) == {'005930'}
    assert values['005930']['captured_at'] == '2026-11-11T15:00:02+09:00'
    assert diag['errors'] == {}


def test_current_prices_reuse_sealed_candidate_desk_without_acquisition(tmp_path):
    from app.services.catalyst_outcomes.prices import load_current_prices
    from app.services.mirofish.alpha_lab import candidate_inputs
    from app.services.mirofish.alpha_lab.daily_source import KISDailyProvider
    captured = datetime.fromisoformat('2026-11-11T09:00:00+09:00')
    class Response:
        status_code = 200
        def __init__(self, end):
            self.end = end
        def json(self):
            bar = dict(stck_bsop_date='20261110', stck_oprc='100', stck_hgpr='110', stck_lwpr='90',
                       stck_clpr='105', acml_vol='1000', acml_tr_pbmn='105000')
            return dict(rt_cd='0', output1=dict(stck_shrn_iscd='005930'),
                        output2=[bar] if self.end == '20261110' else [])
    provider = KISDailyProvider(request=lambda path, tr_id, params: Response(params['FID_INPUT_DATE_2']),
                                clock=lambda: captured)
    candidate_inputs.collect_inputs(tmp_path / 'data/alpha_lab/candidate-desk/inputs', ['005930'],
        latest_session='2026-11-10', scope_hash='a' * 64, names={'005930': '삼성전자'}, provider=provider, now=captured)
    class NoFetch:
        def fetch_history(self, *args, **kwargs):
            pytest.fail('sealed same-session input must be reused')
    values, diag = load_current_prices(tmp_path, ['005930'], '2026-11-10', NOW,
                                      tmp_path / 'output', provider=NoFetch())
    assert values['005930']['bars'][0]['close'] == 105
    assert diag['candidate_cache'] == 'ready'
    assert diag['reused'] == 1 and diag['fetched'] == 0


@pytest.mark.parametrize('mutation', [
    lambda value: value['bars'][0].update(close=120),
    lambda value: value['bars'][0].update(volume=float('nan')),
    lambda value: value['bars'][0].update(traded_value=float('inf')),
    lambda value: value['bars'][0].update(quality_flags=[{'code': 'invented'}]),
    lambda value: value['bars'][0].update(date='2026-11-09'),
])
def test_current_prices_reject_invalid_ohlcv_and_missing_end_session(tmp_path, mutation):
    from app.services.catalyst_outcomes.prices import load_current_prices
    class Provider:
        def fetch_history(self, symbol, end_session, *, count):
            value = provider_value(symbol, end_session)
            mutation(value)
            return value
    values, diag = load_current_prices(tmp_path, ['005930'], '2026-11-10', NOW,
                                      tmp_path / 'output', provider=Provider())
    assert values == {}
    assert diag['pending_symbols'] == ['005930']
