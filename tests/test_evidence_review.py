"""Saved reviews must not invent provenance, replay billing, or rewrite decisions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.ai_routing import AnalysisStatus, ProviderAttempt, RoutingResult, TokenUsage
from app.services.mirofish.alpha_lab import opportunity_store, store
from app.services import kongming_verification
from app.utils.atomic_json import write_json_atomic


NOW = datetime(2026, 11, 8, 1, tzinfo=timezone.utc)


@pytest.fixture
def service():
    assert importlib.util.find_spec('app.services.evidence_review'), 'saved review pipeline is missing'
    return importlib.import_module('app.services.evidence_review')


@pytest.fixture
def paths(tmp_path):
    return dict(root=tmp_path/'reviews', article_root=tmp_path/'articles', alpha_root=tmp_path/'alpha')


def article(identifier='1', **updates):
    return dict(id=identifier, title='삼성전자 공급 계약 체결',
        url=f'https://www.businesspost.co.kr/BP?command=article_view&num={identifier}',
        entities=[dict(symbol='005930', name='삼성전자')],
        published_at=(NOW-timedelta(hours=1)).isoformat(), first_seen_at=NOW.isoformat(),
        provenance='marketflow_rss', event=dict(type='contract', certainty='reported_unverified'), **updates)


def save_articles(paths, rows):
    write_json_atomic(paths['article_root']/'snapshot.json', dict(items=rows, feeds={}))


def save_board(paths, *, decision='a'*64, symbol='005930', source_at=None):
    row = dict(opportunity_id='c'*64, symbol=symbol, name='삼성전자', market='KR', rank=1,
        strategy_id='recovery', source_at=source_at or (NOW-timedelta(hours=2)).isoformat(),
        why_stock='확인 구간 비용을 포함한 과거 수익이 양수입니다',
        plan=dict(entry_low=100, entry_high=102, stop_price=95, target_price=110),
        ranking=dict(score=.01), kelly=dict(fraction=.25), reference_weight=.02,
        reasons=['retrospective_challenger_not_independent_validation'],
        audit=dict(independent_validation=False))
    board = dict(schema_version=1, policy_version='profit-opportunity-v2', decision_id=decision,
        input_fingerprint='b'*64, source_audit_hash='d'*64,
        generated_at=(NOW-timedelta(hours=1)).isoformat(), latest_session='2026-11-06',
        candidates=[row], reasons=['entry_window_unavailable'], status='held')
    opportunity_store.register_board(paths['alpha_root'], board)
    store.publish(paths['alpha_root'], dict(schema_version=1, mode='research', opportunity_board=board),
                  now=NOW.isoformat())
    return board


class Router:
    def __init__(self, *, fail=False, mutate=None, interrupt=False):
        self.calls = []
        self.fail, self.mutate, self.interrupt = fail, mutate, interrupt

    def route_text(self, request):
        self.calls.append(request)
        if self.interrupt:
            raise KeyboardInterrupt()
        if self.fail:
            return RoutingResult(text=None, analysis_status=AnalysisStatus.FAILED_TECHNICAL,
                primary_provider='anthropic', fallback_reason='insufficient_balance', attempts=(ProviderAttempt(
                    request_id=request.request_id, provider='anthropic', model='fixture-model', endpoint='messages',
                    operation=request.operation, attempt_number=1, error_class='insufficient_balance',
                    usage=TokenUsage(input_tokens=0, output_tokens=0), estimated_cost_usd=Decimal('0')),))
        supplied = json.loads(request.prompt)
        evidence = supplied['sources'][0]
        result = dict(rows=[dict(symbol=row['symbol'], name=row['name'], market='KR',
            strengths=[dict(text='공급 근거를 확인할 수 있습니다', claim_status='inference', evidence_ids=[evidence['evidence_id']],
                            quotes=[dict(evidence_id=evidence['evidence_id'], quote=evidence['text'][:60])])],
            risks=[], what_to_watch=[]) for row in supplied['targets']])
        if self.mutate:
            self.mutate(result)
        text = json.dumps(result, ensure_ascii=False)
        return RoutingResult(text=text, analysis_status=AnalysisStatus.SUCCESS_PRIMARY,
            primary_provider='anthropic', actual_provider='anthropic', model='fixture-model',
            evidence_validated=True, usage=TokenUsage(input_tokens=100, output_tokens=30))


def test_success_survives_restart_and_read_is_no_write(service, paths):
    save_articles(paths, [article()])
    first = Router()
    service.run_once(**paths, now=NOW, router=first)
    before = {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}
    view = service.read_article_reviews(**paths, now=NOW)
    assert view['status'] == 'ready'
    assert view['items'][0]['rows'][0]['symbol'] == '005930'
    assert view['items'][0]['status'] == 'SUCCESS_PRIMARY'
    assert view['items'][0]['provider'] == 'anthropic'
    assert before == {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}
    second = Router()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=second)
    assert len(first.calls) == 1 and not second.calls
    assert 'raw' not in str(view) and 'prompt' not in str(view)


def test_changed_source_generates_new_bound_review(service, paths):
    save_articles(paths, [article()])
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    old = service.read_article_reviews(**paths, now=NOW)['items'][0]
    changed = article(); changed['title'] = '삼성전자 공급 계약 취소'
    save_articles(paths, [changed])
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['freshness'] == 'stale'
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    new = service.read_article_reviews(**paths, now=NOW+timedelta(minutes=5))['items'][0]
    assert len(router.calls) == 2
    assert old['input_fingerprint'] != new['input_fingerprint']


def test_recent_new_article_limit_and_future_rejection(service, paths):
    rows = [article(str(i)) for i in range(1, 12)]
    rows[0]['published_at'] = (NOW-timedelta(hours=73)).isoformat()
    rows[1]['first_seen_at'] = (NOW+timedelta(seconds=1)).isoformat()
    save_articles(paths, rows)
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    assert len(router.calls) == 8
    inputs = [json.loads(call.prompt)['article_id'] for call in router.calls]
    assert '1' not in inputs and '2' not in inputs


def test_outage_cooldown_recovers_without_repeating_completed_stages(service, paths):
    save_articles(paths, [article()])
    fail = Router(fail=True)
    service.run_once(**paths, now=NOW, router=fail)
    view = service.read_article_reviews(**paths, now=NOW)
    assert view['status'] == 'degraded'
    assert view['items'][0]['status'] == 'UNVERIFIED'
    assert view['items'][0]['fallback_reason'] == 'insufficient_balance'
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=fail)
    assert len(fail.calls) == 1
    success = Router()
    service.run_once(**paths, now=NOW+timedelta(hours=2), router=success)
    assert len(success.calls) == 1
    assert service.read_article_reviews(**paths, now=NOW+timedelta(hours=2))['status'] == 'ready'


def test_interrupted_call_has_durable_cooldown(service, paths):
    save_articles(paths, [article()])
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**paths, now=NOW, router=Router(interrupt=True))
    recovery = Router()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=recovery)
    assert not recovery.calls
    assert service.read_article_reviews(**paths, now=NOW+timedelta(minutes=5))['items'][0]['status'] == 'IN_PROGRESS'


@pytest.mark.parametrize('mutate', [
    lambda result: result['rows'][0]['strengths'][0].update(evidence_ids=['invented']),
    lambda result: result['rows'][0]['strengths'][0]['quotes'][0].update(quote='not in supplied evidence'),
    lambda result: result['rows'][0].update(symbol='000001'),
    lambda result: result['rows'][0]['strengths'][0].update(text='목표가 999999원 상승확률 99%'),
    lambda result: result['rows'][0].update(price=999999),
])
def test_invalid_model_evidence_is_unverified(service, paths, mutate):
    save_articles(paths, [article()])
    service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    item = service.read_article_reviews(**paths, now=NOW)['items'][0]
    assert item['status'] == 'UNVERIFIED'
    assert item['fallback_reason'] == 'evidence_validation_failed'
    assert not item['rows'][0]['strengths']


def test_candidate_uses_sealed_board_not_later_quotes_and_never_changes_it(service, paths):
    board = save_board(paths)
    before = {str(p): p.read_bytes() for p in paths['alpha_root'].rglob('*.json')}
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    view = service.read_candidate_review(**paths, now=NOW)
    assert view['items'][0]['decision_id'] == board['decision_id']
    assert view['items'][0]['review_scope'] == 'current_evidence_not_original_decision'
    assert len(router.calls) == 1
    assert 'current_price' not in router.calls[0].prompt
    assert 'outcomes' not in router.calls[0].prompt
    assert before == {str(p): p.read_bytes() for p in paths['alpha_root'].rglob('*.json')}
    save_board(paths, decision='e'*64)
    assert service.read_candidate_review(**paths, now=NOW)['items'] == []


def test_candidate_rejects_sources_after_original_decision(service, paths):
    save_board(paths, source_at=NOW.isoformat())
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    assert not router.calls
    assert service.read_candidate_review(**paths, now=NOW)['items'] == []


def test_display_clock_changes_do_not_renew_candidate_cache(service, paths):
    board = save_board(paths)
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    later = deepcopy(board)
    later.update(generated_at=(NOW+timedelta(minutes=5)).isoformat(), status='ready')
    later['candidates'][0]['current_price'] = 1000
    store.publish(paths['alpha_root'], dict(schema_version=1, mode='research', opportunity_board=later),
                  now=(NOW+timedelta(minutes=5)).isoformat())
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(router.calls) == 1


def test_empty_read_creates_nothing_and_reports_no_current_candidates(service, paths):
    assert service.read_candidate_review(**paths, now=NOW)['items'] == []
    assert not paths['root'].exists()


def test_private_excerpt_is_bound_to_actual_fetch_without_poll_clock_cache_bust(service, paths):
    item = article()
    item.update(rss_excerpt='공급 계약은 공식 공시 확인이 필요하다', rss_excerpt_fetched_at=NOW.isoformat())
    save_articles(paths, [item])
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    supplied = json.loads(router.calls[0].prompt)
    assert any(source['text'] == item['rss_excerpt'] for source in supplied['sources'])
    item['rss_excerpt_fetched_at'] = (NOW+timedelta(minutes=5)).isoformat()
    save_articles(paths, [item])
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(router.calls) == 1


def test_future_excerpt_is_excluded_from_title_only_review(service, paths):
    item = article()
    item.update(rss_excerpt='아직 도착하지 않은 본문', rss_excerpt_fetched_at=(NOW+timedelta(hours=1)).isoformat())
    save_articles(paths, [item])
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    assert item['rss_excerpt'] not in router.calls[0].prompt


def test_sealed_research_watchlist_without_issued_buy_board_remains_held(service, paths):
    board = dict(schema_version=1, policy_version='profit-opportunity-v2', decision_id='a'*64,
        input_fingerprint='b'*64, source_audit_hash='d'*64, generated_at=NOW.isoformat(),
        latest_session='2026-11-06', candidates=[], reasons=['no_qualified_survivors'], status='held')
    report = dict(schema_version=1, mode='research', input_fingerprint='b'*64, decision_at=NOW.isoformat(),
        provenance=dict(captured_at=(NOW-timedelta(hours=1)).isoformat()), opportunity_board=board,
        candidates=[dict(symbol='032640', name='LG유플러스', score=4.9, strategy_id='momentum')])
    alpha_store_before = store.publish(paths['alpha_root'], report, now=NOW.isoformat(), held=True)
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    view = service.read_candidate_review(**paths, now=NOW)
    assert len(router.calls) == 1
    assert view['items'][0]['candidate_basis'] == 'research_watchlist'
    assert view['items'][0]['original_status'] == 'held'
    assert view['items'][0]['rows'][0]['symbol'] == '032640'
    assert store.read_status(paths['alpha_root'], now=NOW.isoformat()) == alpha_store_before


def test_uncertain_retry_keeps_same_provider_request_identity(service, paths):
    save_articles(paths, [article()])
    initial = Router(interrupt=True)
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**paths, now=NOW, router=initial)
    retry = Router(fail=True)
    service.run_once(**paths, now=NOW+timedelta(hours=7), router=retry)
    assert retry.calls[0].request_id == initial.calls[0].request_id


def test_verification_status_changes_invalidate_but_checked_clock_does_not(service, paths, monkeypatch):
    save_articles(paths, [article()])
    verification = dict(article_id='1', symbol='005930', article_title=article()['title'],
        primary=dict(status='no_related_filing', checked_at=NOW.isoformat()))
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda *a, **k: dict(items=[verification]))
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    assert 'no_related_filing' in router.calls[0].prompt
    verification['primary']['checked_at'] = (NOW+timedelta(minutes=5)).isoformat()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(router.calls) == 1
    verification['primary']['status'] = 'source_unavailable'
    service.run_once(**paths, now=NOW+timedelta(minutes=10), router=router)
    assert len(router.calls) == 2


def test_model_configuration_change_invalidates_success(service, paths, monkeypatch):
    save_articles(paths, [article()])
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    policy = service.policy_for
    from dataclasses import replace
    monkeypatch.setattr(service, 'policy_for', lambda op: replace(policy(op), models=dict(anthropic='different-model')))
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['freshness'] == 'stale'
    service.run_once(**paths, now=NOW, router=router)
    assert len(router.calls) == 2


def test_overlapping_worker_cannot_enter_paid_stage(service, paths):
    from filelock import FileLock, Timeout
    save_articles(paths, [article()])
    paths['root'].mkdir()
    router = Router()
    with FileLock(str(paths['root']/'worker.lock')):
        with pytest.raises(Timeout):
            service.run_once(**paths, now=NOW, router=router)
    assert not router.calls


def test_oversized_quotes_are_rejected_even_when_verbatim(service, paths):
    item = article(); item['title'] = '가' * 300
    save_articles(paths, [item])
    mutate = lambda result: result['rows'][0]['strengths'][0]['quotes'][0].update(quote='가'*241)
    service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['status'] == 'UNVERIFIED'


def test_saved_verified_price_is_current_evidence_and_future_price_is_excluded(service, paths, monkeypatch):
    save_articles(paths, [article()])
    task = dict(article_id='1', symbol='005930', article_title=article()['title'], primary=dict(status='pending'),
        price=dict(status='verified', source='KIS:J:FHKST03010230', symbol='005930', close=100, latest_close=101,
            observed_at=(NOW-timedelta(minutes=30)).isoformat(), latest_observed_at=NOW.isoformat(),
            fetched_at=NOW.isoformat(), change_pct=1))
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda *a, **k: dict(items=[task]))
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    supplied = json.loads(router.calls[0].prompt)
    price = next(row for row in supplied['sources'] if row['evidence_id'] == 'price:1:005930')
    assert json.loads(price['text'])['latest_close'] == 101
    task['price']['latest_observed_at'] = (NOW+timedelta(days=1)).isoformat()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    price = next(row for row in json.loads(router.calls[1].prompt)['sources'] if row['evidence_id'] == 'price:1:005930')
    assert 'latest_close' not in json.loads(price['text'])
    assert price['verification_status'] == 'unavailable'


def test_candidate_adds_only_latest_two_current_articles_and_marks_later_evidence(service, paths):
    save_board(paths)
    rows = [article(str(i)) for i in range(1, 4)]
    for offset, row in enumerate(rows):
        row['published_at'] = (NOW-timedelta(minutes=30+offset)).isoformat()
    save_articles(paths, rows)
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    supplied = json.loads(router.calls[0].prompt)
    assert supplied['kind'] == 'candidate'
    source = next(row for row in supplied['sources'] if row['evidence_id'] == 'article:1')
    assert source['available_at_original_decision'] is False
    assert not any(row['evidence_id'] == 'article:3' for row in supplied['sources'])


def test_all_unverified_worker_receipt_is_failure_not_complete(service, paths):
    save_articles(paths, [article()])
    result = service.run_once(**paths, now=NOW, router=Router(fail=True))
    assert result['status'] == 'failed'
    assert result['successful'] == 0
    assert result['unverified'] == 1


@pytest.mark.parametrize('claim_status,text', [
    ('verified', '공식 공시로 공급 계약이 확정됐습니다'),
    ('inference', '공식 공시로 공급 계약이 확정됐습니다'),
    ('inference', '즉시 매수해도 안전합니다'),
    ('inference', '반드시 수익을 얻습니다'),
    ('inference', 'guaranteed profitable, buy immediately'),
    ('inference', '목표가는 백만원입니다'),
    ('reported', '원문에 없는 확정 계약 내용'),
])
def test_claim_classification_cannot_launder_confirmation_or_trade_advice(service, paths, claim_status, text):
    save_articles(paths, [article()])
    mutate = lambda result: result['rows'][0]['strengths'][0].update(claim_status=claim_status, text=text)
    service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['status'] == 'UNVERIFIED'


def test_reported_claim_is_literal_source_not_freeform_fact(service, paths):
    save_articles(paths, [article()])
    mutate = lambda result: result['rows'][0]['strengths'][0].update(claim_status='reported', text=article()['title'])
    service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    item = service.read_article_reviews(**paths, now=NOW)['items'][0]
    assert item['status'] == 'SUCCESS_PRIMARY'
    assert item['rows'][0]['strengths'][0]['claim_status'] == 'reported'


def test_verified_claim_requires_official_specific_numeric_match_template(service):
    target = dict(symbol='005930', name='삼성전자', market='KR')
    supplied = dict(targets=[target], sources=[dict(evidence_id='filing:1', source='OpenDART_saved_verification',
        verification_status='verified_numeric_claims', text='{"claims":[{"verified":true}],"status":"verified_numeric_claims"}')])
    finding = dict(text='공식 공시의 수치 대조 항목이 일치합니다.', claim_status='verified', evidence_ids=['filing:1'],
        quotes=[dict(evidence_id='filing:1', quote='"verified":true')])
    value = dict(rows=[dict(target, strengths=[finding], risks=[], what_to_watch=[])])
    assert service._validate(value, supplied)['rows'][0]['strengths'][0]['claim_status'] == 'verified'
    finding['text'] = '공식 공시에서 새로운 공급 계약이 확인됩니다'
    with pytest.raises(ValueError):
        service._validate(value, supplied)
    finding['text'] = '공식 공시의 수치 대조 항목이 일치합니다.'
    supplied['sources'][0]['source'] = 'KIS_saved_post_receipt_prices'
    with pytest.raises(ValueError):
        service._validate(value, supplied)


def test_empty_attempts_unknown_failure_never_mints_fresh_billing_identity(service, paths):
    save_articles(paths, [article()])
    class LostReceipt:
        def __init__(self):
            self.calls = []
        def route_text(self, request):
            self.calls.append(request)
            return RoutingResult(text=None, analysis_status=AnalysisStatus.FAILED_TECHNICAL,
                                 primary_provider='anthropic', fallback_reason='unknown', attempts=())
    router = LostReceipt()
    service.run_once(**paths, now=NOW, router=router)
    service.run_once(**paths, now=NOW+timedelta(hours=7), router=router)
    assert len(router.calls) == 2
    assert router.calls[0].request_id == router.calls[1].request_id


def test_post_dispatch_receipt_error_cannot_replay_real_router_charge(service, paths, monkeypatch):
    from app.services.ai_routing.providers import AdapterResponse
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    from app.services.ai_routing import router as routing_module
    save_articles(paths, [article()])
    output = Router()
    class ChargedAdapter:
        endpoint = 'fixture'
        def __init__(self):
            self.calls = 0
        def generate(self, request, **kwargs):
            self.calls += 1
            return AdapterResponse(output.route_text(request).text, TokenUsage(input_tokens=100, output_tokens=30))
    adapter = ChargedAdapter()
    ledger = RoutingStore(paths['root'].parent/'routing.sqlite3')
    def receipt_error(*args, **kwargs):
        raise OSError('receipt unavailable after provider dispatch')
    monkeypatch.setattr(routing_module, 'record_attempt', receipt_error)
    service.run_once(**paths, now=NOW, router=AIRouter({'anthropic':adapter}, store=ledger))
    service.run_once(**paths, now=NOW+timedelta(hours=7), router=AIRouter({'anthropic':adapter}, store=ledger))
    assert adapter.calls == 1


def test_worker_does_not_start_paid_stage_without_time_to_finish(service, paths):
    import time
    save_articles(paths, [article()])
    router = Router()
    service.run_once(**paths, now=NOW, router=router, deadline=time.monotonic()+95)
    assert not router.calls


def test_rejected_native_response_is_saved_privately_before_domain_validation(service, paths):
    from app.services.ai_routing.providers import AdapterResponse
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    save_articles(paths, [article()])
    fake = Router(mutate=lambda value: value['rows'][0]['strengths'][0].update(text='목표가는 백만원입니다'))
    class Native:
        endpoint = 'fixture'
        def generate(self, request, **kwargs):
            return AdapterResponse(fake.route_text(request).text, TokenUsage(input_tokens=100, output_tokens=30))
    service.run_once(**paths, now=NOW, router=AIRouter({'anthropic': Native()}, store=RoutingStore(paths['root'].parent/'routing.sqlite3')))
    record = service._read(next((paths['root']/'runs').glob('*.json')))
    assert record['raw_responses'][0]['validation_error'] == 'all_findings_invalid'
    assert record['raw_responses'][0]['rejections'][0]['reason'] == 'unsupported_trade_or_certainty'
    assert '백만원' in record['raw_responses'][0]['raw']
    public = service.read_article_reviews(**paths, now=NOW)
    assert '백만원' not in str(public) and 'raw_responses' not in str(public)


def test_failed_raw_receipt_stops_fallback_and_cannot_publish_success(service, paths, monkeypatch):
    from app.services.ai_routing.providers import AdapterResponse
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    save_articles(paths, [article()])
    fake = Router()
    class Native:
        endpoint = 'fixture'
        def __init__(self):
            self.calls = 0
        def generate(self, request, **kwargs):
            self.calls += 1
            return AdapterResponse(fake.route_text(request).text, TokenUsage(input_tokens=100, output_tokens=30))
    primary, fallback = Native(), Native()
    write = service._write
    failed = []
    def fail_response_once(path, value):
        if value.get('raw_responses') and not failed:
            failed.append(True)
            raise OSError('disk receipt failed')
        return write(path, value)
    monkeypatch.setattr(service, '_write', fail_response_once)
    service.run_once(**paths, now=NOW, router=AIRouter({'anthropic':primary, 'deepseek':fallback},
        store=RoutingStore(paths['root'].parent/'routing.sqlite3')))
    assert primary.calls == 1 and fallback.calls == 0
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['status'] == 'UNVERIFIED'


def test_wire_schema_uses_supported_structured_output_subset_and_local_caps_remain(service, paths):
    def inspect(schema):
        assert set(schema) <= {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum'}
        for child in schema.get('properties', {}).values():
            inspect(child)
        if 'items' in schema:
            inspect(schema['items'])
    inspect(service.RESPONSE_SCHEMA)
    save_articles(paths, [article()])
    router = Router(mutate=lambda value: value['rows'][0]['strengths'][0].update(text='근거'*41))
    service.run_once(**paths, now=NOW, router=router)
    assert service.read_article_reviews(**paths, now=NOW)['items'][0]['status'] == 'UNVERIFIED'


def test_live_haiku_domain_rejection_fixture_remains_rejected_offline(service):
    fixture = json.loads((Path(__file__).parent/'fixtures'/'evidence_review_haiku_domain_rejection.json').read_text(encoding='utf-8'))
    response = fixture['response']
    with pytest.raises(ValueError, match='reported_text_not_literal'):
        service._validate(response, fixture['supplied'])
    response['rows'][0]['strengths'][0]['claim_status'] = 'inference'
    with pytest.raises(ValueError, match='finding_count_exceeds_one'):
        service._validate(response, fixture['supplied'])
    response['rows'][0]['risks'] = response['rows'][0]['risks'][:1]
    with pytest.raises(ValueError, match='finding_status_or_references_invalid'):
        service._validate(response, fixture['supplied'])


def test_prompt_format_example_passes_the_same_strict_validator(service):
    example = service.FORMAT_EXAMPLE
    assert service._validate(example['response'], example['supplied']) == example['response']
    row = example['response']['rows'][0]
    assert {row[group][0]['claim_status'] for group in ('strengths', 'risks', 'what_to_watch')} == {'reported', 'missing', 'inference'}


def _three_candidate_response(supplied):
    rows = []
    for target in supplied['targets']:
        source = next(row for row in supplied['sources'] if row['evidence_id'] == 'candidate:'+target['symbol'])
        finding = dict(text='추가 출처 확인이 필요합니다.', claim_status='inference', evidence_ids=[source['evidence_id']],
                       quotes=[dict(evidence_id=source['evidence_id'], quote=target['symbol'])])
        rows.append(dict(target, strengths=[deepcopy(finding)], risks=[deepcopy(finding)], what_to_watch=[deepcopy(finding)]))
    rows[0]['risks'][0]['text'] = 't-stat이 2 미만입니다.'
    return dict(rows=rows)


def test_one_invalid_candidate_finding_preserves_eight_and_avoids_provider_fallback(service, paths):
    from app.services.ai_routing.providers import AdapterResponse
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    board = save_board(paths)
    board['decision_id'] = 'e'*64
    board['candidates'] = [dict(deepcopy(board['candidates'][0]), symbol=symbol, name=name,
        opportunity_id=f'{index:064x}') for index, (symbol, name) in enumerate(
            [('032640','LG유플러스'), ('028050','삼성E&A'), ('068270','셀트리온')], 1)]
    opportunity_store.register_board(paths['alpha_root'], board)
    store.publish(paths['alpha_root'], dict(schema_version=1, mode='research', opportunity_board=board), now=NOW.isoformat())
    class Native:
        endpoint = 'fixture'
        def __init__(self):
            self.calls = 0
        def generate(self, request, **kwargs):
            self.calls += 1
            return AdapterResponse(json.dumps(_three_candidate_response(json.loads(request.prompt)), ensure_ascii=False),
                                   TokenUsage(input_tokens=100, output_tokens=30))
    primary, fallback = Native(), Native()
    service.run_once(**paths, now=NOW, router=AIRouter({'anthropic':primary, 'deepseek':fallback},
        store=RoutingStore(paths['root'].parent/'routing.sqlite3')))
    item = service.read_candidate_review(**paths, now=NOW)['items'][0]
    assert item['status'] == 'SUCCESS_PRIMARY'
    assert item['omitted_findings'] == 1
    assert sum(len(row[group]) for row in item['rows'] for group in ('strengths','risks','what_to_watch')) == 8
    assert item['rows'][0]['risks'] == []
    assert primary.calls == 1 and fallback.calls == 0
    record = service._read(next((paths['root']/'runs').glob('*.json')))
    assert 't-stat' in record['raw_responses'][0]['raw']
    assert record['raw_responses'][0]['rejections'] == [dict(symbol='032640', group='risks', index=0, reason='nonliteral_number')]
    assert service._validate(dict(rows=item['rows']), record['supplied'])['rows'] == item['rows']


@pytest.mark.parametrize('mutate', [
    lambda value: value['rows'][0].update(symbol='000001'),
    lambda value: value.update(extra='unexpected'),
    lambda value: value['rows'][0]['strengths'][0].update(extra='unexpected'),
    lambda value: value['rows'][0]['strengths'].append(deepcopy(value['rows'][0]['strengths'][0])),
    lambda value: value['rows'][0]['strengths'][0]['quotes'][0].update(extra='unexpected'),
])
def test_partial_normalization_never_salvages_wrong_identity_or_malformed_shape(service, mutate):
    example = deepcopy(service.FORMAT_EXAMPLE)
    mutate(example['response'])
    with pytest.raises(ValueError):
        service._normalize(example['response'], example['supplied'])


def test_all_invalid_findings_are_still_unverified_and_fallback_omissions_are_not_mixed(service, paths):
    from app.services.ai_routing.providers import AdapterResponse
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    save_articles(paths, [article()])
    class Native:
        endpoint = 'fixture'
        def __init__(self, invalid):
            self.invalid = invalid
        def generate(self, request, **kwargs):
            result = Router(mutate=(lambda value: value['rows'][0]['strengths'][0].update(text='목표가는 백만원')) if self.invalid else None).route_text(request)
            return AdapterResponse(result.text, TokenUsage(input_tokens=100, output_tokens=30))
    service.run_once(**paths, now=NOW, router=AIRouter({'anthropic':Native(True), 'deepseek':Native(False)},
        store=RoutingStore(paths['root'].parent/'routing.sqlite3')))
    item = service.read_article_reviews(**paths, now=NOW)['items'][0]
    assert item['status'] == 'SUCCESS_FALLBACK'
    assert item['omitted_findings'] == 0
    record = service._read(next((paths['root']/'runs').glob('*.json')))
    assert record['raw_responses'][0]['omitted_findings'] == 1
    assert record['raw_responses'][1]['omitted_findings'] == 0
    for group in ('strengths', 'risks', 'what_to_watch'):
        assert item['rows'][0][group] == json.loads(record['raw_responses'][1]['raw'])['rows'][0][group]


class DailyBudget:
    def __init__(self, blocked=True):
        self.blocked = blocked

    def daily_summary(self, *, now):
        reset = (now+timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return dict(status='ok', hold_reason='top3_capacity_reserved' if self.blocked else None,
                    resets_at_utc=reset.isoformat())


def test_daily_call_hold_continues_basic_checks_for_all_articles_without_ai(service, paths):
    save_articles(paths, [article(str(i)) for i in range(1, 13)])
    router = Router()
    result = service.run_once(**paths, now=NOW, router=router, budget=DailyBudget())
    view = service.read_article_reviews(**paths, now=NOW)
    assert not router.calls and result['article_attempts'] == 0
    assert len(view['items']) == 12
    for item in view['items']:
        assert item['status'] == 'UNVERIFIED'
        assert item['budget_hold_reason'] == 'top3_capacity_reserved'
        assert item['next_retry_at'] == '2026-11-09T00:00:00Z'
        assert item['basic_checks']['rows'][0] == dict(symbol='005930', name='삼성전자',
            disclosure_status='unavailable', price_status='unavailable')
        assert item['rows'][0]['strengths'] == []
    before = {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}
    service.read_article_reviews(**paths, now=NOW+timedelta(minutes=1))
    assert before == {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}


def test_budget_reset_retries_same_request_identity_with_new_day_cache_key(service, paths):
    save_articles(paths, [article()])
    class Denied(Router):
        def route_text(self, request):
            self.calls.append(request)
            return RoutingResult(text=None, analysis_status=AnalysisStatus.FAILED_TECHNICAL,
                primary_provider='anthropic', fallback_reason='budget_exhausted',
                budget_hold_reason='daily_hard_cap')
    denied = Denied()
    service.run_once(**paths, now=NOW, router=denied)
    service.run_once(**paths, now=NOW+timedelta(hours=7), router=denied)
    assert len(denied.calls) == 1
    recovered = Router()
    service.run_once(**paths, now=NOW+timedelta(days=1), router=recovered)
    assert len(recovered.calls) == 1
    assert denied.calls[0].request_id == recovered.calls[0].request_id
    assert denied.calls[0].run_id != recovered.calls[0].run_id


def test_live_price_ticks_do_not_rebill_until_window_completes(service, paths, monkeypatch):
    save_articles(paths, [article()])
    task = dict(article_id='1', symbol='005930', article_title=article()['title'],
        price=dict(status='verified', source='KIS:J:FHKST03010230', symbol='005930', close=100, latest_close=101,
            observed_at=(NOW-timedelta(minutes=30)).isoformat(), latest_observed_at=NOW.isoformat(),
            fetched_at=NOW.isoformat(), change_pct=1, window_complete=False,
            window_end_at=(NOW+timedelta(minutes=30)).isoformat()))
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda *a, **k: dict(items=[task]))
    router = Router()
    service.run_once(**paths, now=NOW, router=router)
    task['price'].update(latest_close=102, change_pct=2,
        latest_observed_at=(NOW+timedelta(minutes=5)).isoformat(), fetched_at=(NOW+timedelta(minutes=5)).isoformat())
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(router.calls) == 1
    source = next(s for s in json.loads(router.calls[0].prompt)['sources'] if s['evidence_id'].startswith('price:'))
    assert source['verification_status'] == 'awaiting_window_completion'
    assert 'latest_close' not in json.loads(source['text'])
    task['price'].update(window_complete=True, latest_observed_at=(NOW+timedelta(minutes=30)).isoformat(),
                         fetched_at=(NOW+timedelta(minutes=30)).isoformat())
    service.run_once(**paths, now=NOW+timedelta(minutes=30), router=router)
    assert len(router.calls) == 2
    final_source = next(s for s in json.loads(router.calls[-1].prompt)['sources'] if s['evidence_id'].startswith('price:'))
    assert json.loads(final_source['text'])['latest_close'] == 102


def test_basic_checks_use_current_saved_status_without_rewriting_previous_ai(service, paths, monkeypatch):
    save_articles(paths, [article()])
    router = Router(); service.run_once(**paths, now=NOW, router=router)
    before = {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}
    task = dict(article_id='1', symbol='005930', article_title=article()['title'],
                primary=dict(status='issuer_name_conflict', checked_at=NOW.isoformat()))
    monkeypatch.setattr(kongming_verification, 'read_dashboard', lambda *a, **k: dict(items=[task]))
    item = service.read_article_reviews(**paths, now=NOW)['items'][0]
    assert item['freshness'] == 'stale'
    assert item['basic_checks']['rows'][0]['disclosure_status'] == 'issuer_name_conflict'
    assert item['status'] == 'SUCCESS_PRIMARY'
    assert before == {str(p): p.read_bytes() for p in paths['root'].rglob('*.json')}


def test_known_zero_failure_survives_budget_hold_and_rotates_only_dispatched_identity(service, paths):
    save_articles(paths, [article()])
    rejected = Router(fail=True)
    service.run_once(**paths, now=NOW, router=rejected)
    service.run_once(**paths, now=NOW+timedelta(hours=2), router=Router(), budget=DailyBudget())
    success = Router()
    service.run_once(**paths, now=NOW+timedelta(days=1), router=success, budget=DailyBudget(False))
    assert len(success.calls) == 1
    assert success.calls[0].request_id != rejected.calls[0].request_id


def test_first_preflight_hold_keeps_zero_charge_recovery_eligibility(service, paths):
    save_articles(paths, [article()])
    service.run_once(**paths, now=NOW, router=Router(), budget=DailyBudget())
    receipt = service._read(next((paths['root']/'runs').glob('*.json')))
    rejected = Router(fail=True)
    service.run_once(**paths, now=NOW+timedelta(days=1), router=rejected, budget=DailyBudget(False))
    assert rejected.calls[0].request_id == receipt['request_id']
    success = Router()
    service.run_once(**paths, now=NOW+timedelta(days=1, hours=2), router=success, budget=DailyBudget(False))
    assert len(success.calls) == 1
    assert success.calls[0].request_id != rejected.calls[0].request_id
