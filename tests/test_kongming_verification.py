from datetime import datetime, timedelta

from app.services import kongming_verification as service


NOW = datetime.fromisoformat('2026-11-07T20:00:00+09:00')
PUBLISHED = '2026-11-06T13:00:00+09:00'
RECEIVED = '2026-11-06T13:15:00+09:00'


def _article(identifier, title):
    return {
        'id': identifier, 'title': title, 'published_at': PUBLISHED, 'first_seen_at': RECEIVED,
        'url': f'https://www.businesspost.co.kr/BP?command=article_view&num={identifier}',
        'entities': [{'symbol': '005930', 'name': '삼성전자'}],
    }


class Provider:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def verify(self, article, entity, now):
        self.calls.append((article['id'], entity))
        return self.result


def _snapshot(monkeypatch, rows):
    monkeypatch.setattr(service.candidates, 'read_view', lambda data_dir, *, now: {'items': rows})


def test_article_identity_and_revision_keep_distinct_evidence(tmp_path, monkeypatch):
    first = _article('11', '삼성전자 실적')
    second = _article('12', '삼성전자 수주')
    rows = [first, second]
    _snapshot(monkeypatch, rows)
    dart = Provider({'status': 'no_matching_filing'})
    kis = Provider({'status': 'verified', 'observed_at': '2026-11-06T13:16:00+09:00', 'close': 71000})

    service.run_once(tmp_path, now=NOW, disclosure=dart, price=kis)
    original = service.read_dashboard(tmp_path, now=NOW)
    assert len(original['items']) == 2
    assert {row['article_id'] for row in original['items']} == {'11', '12'}
    assert original['operation']['price_checked'] == 2
    assert [row['article_id'] for row in service.read_dashboard(tmp_path, article_id='11', now=NOW)['items']] == ['11']
    assert len(service.read_history(tmp_path, article_id='11')['items']) == 2
    assert all(call[1] == '005930' for call in kis.calls)

    service.run_once(tmp_path, now=NOW + timedelta(minutes=1), disclosure=dart, price=kis)
    assert len(dart.calls) == len(kis.calls) == 2
    assert len(service.read_history(tmp_path)['items']) == 4

    rows[0] = _article('11', '삼성전자 실적 정정')
    service.run_once(tmp_path, now=NOW + timedelta(minutes=2), disclosure=dart, price=kis)
    updated = service.read_dashboard(tmp_path, article_id='11', now=NOW + timedelta(minutes=2))
    assert [row['article_title'] for row in updated['items']] == ['삼성전자 실적 정정']
    assert len(kis.calls) == 3
    assert {row['article_title'] for row in service.read_history(tmp_path, article_id='11')['items']} == {
        '삼성전자 실적', '삼성전자 실적 정정',
    }


def test_one_source_error_does_not_block_or_replay_completed_other_stage(tmp_path, monkeypatch):
    _snapshot(monkeypatch, [_article('11', '삼성전자 실적')])
    dart = Provider({'status': 'source_unavailable', 'error_code': 'dart_transport'})
    kis = Provider({'status': 'verified', 'observed_at': '2026-11-06T13:16:00+09:00', 'close': 71000})
    service.run_once(tmp_path, now=NOW, disclosure=dart, price=kis)
    assert service.read_dashboard(tmp_path, now=NOW)['operation']['state'] == 'partial'

    dart.result = {'status': 'related_filing_found', 'checks': [{'status': 'related_filing_found'}]}
    service.run_once(tmp_path, now=NOW + timedelta(minutes=15), disclosure=dart, price=kis)
    row = service.read_dashboard(tmp_path, now=NOW + timedelta(minutes=15))['items'][0]
    assert row['primary']['status'] == 'related_filing_found'
    assert row['price']['close'] == 71000
    assert len(kis.calls) == 1

    dart.result = {'status': 'source_unavailable', 'error_code': 'dart_transport'}
    service.run_once(tmp_path, now=NOW + timedelta(hours=7), disclosure=dart, price=kis)
    dashboard = service.read_dashboard(tmp_path, now=NOW + timedelta(hours=7))
    assert dashboard['items'][0]['primary']['status'] == 'related_filing_found'
    assert dashboard['items'][0]['primary']['refresh_status'] == 'source_unavailable'
    assert dashboard['operation']['state'] == 'partial'


def test_revised_issuer_set_retires_prior_numeric_evidence(tmp_path, monkeypatch):
    row = _article('11', '삼성전자 실적')
    _snapshot(monkeypatch, [row])
    dart = Provider({'status': 'verified_numeric_claims', 'checks': [{'status': 'verified_numeric_claims'}]})
    kis = Provider({'status': 'verified', 'close': 71000})
    service.run_once(tmp_path, now=NOW, disclosure=dart, price=kis)
    before = service.read_dashboard(tmp_path, now=NOW)['items'][0]

    row['entities'].append({'symbol': '000660', 'name': 'SK하이닉스'})
    dart.result = {'status': 'related_filing_found'}
    current = NOW + timedelta(minutes=1)
    service.run_once(tmp_path, now=current, disclosure=dart, price=kis)
    after = service.read_dashboard(tmp_path, now=current)['items']
    assert len(after) == 2 and all(item['primary']['status'] == 'related_filing_found' for item in after)
    assert before['task_id'] not in {item['task_id'] for item in after}
    assert any(item['primary']['status'] == 'verified_numeric_claims'
               for item in service.read_history(tmp_path, article_id='11')['items'])


def test_pending_refresh_retains_same_filing_but_does_not_verify_new_correction(tmp_path, monkeypatch):
    _snapshot(monkeypatch, [_article('11', '삼성전자 실적')])

    def finding(status, receipt):
        return {'status': status, 'checks': [{'status': status, 'filing': {'rcept_no': receipt}}]}

    dart = Provider(finding('verified_numeric_claims', '20261106800151'))
    kis = Provider({'status': 'verified', 'close': 71000})
    service.run_once(tmp_path, now=NOW, disclosure=dart, price=kis)

    dart.result = finding('pending', '20261106800151')
    current = NOW + timedelta(hours=6)
    service.run_once(tmp_path, now=current, disclosure=dart, price=kis)
    saved = service.read_dashboard(tmp_path, now=current)['items'][0]['primary']
    assert saved['status'] == 'verified_numeric_claims' and saved['refresh_status'] == 'pending'

    dart.result = finding('document_unavailable', '20261107800152')
    current += timedelta(minutes=1)
    service.run_once(tmp_path, now=current, disclosure=dart, price=kis)
    saved = service.read_dashboard(tmp_path, now=current)['items'][0]['primary']
    assert saved['status'] == 'document_unavailable'
    assert saved['checks'][0]['filing']['rcept_no'] == '20261107800152'
    assert len(kis.calls) == 1


def test_read_before_first_worker_does_not_create_store(tmp_path):
    assert service.read_dashboard(tmp_path)['operation']['state'] == 'waiting'
    assert service.read_history(tmp_path)['items'] == []
    assert not (tmp_path / service.DATABASE).exists()
