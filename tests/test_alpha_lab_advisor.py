"""The advisor must ground independent role calls without replaying paid work."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib
import importlib.util
import json

import pytest

from app.services.ai_routing import AnalysisStatus, Operation, ProviderAttempt, RoutingResult, TokenUsage


NOW = datetime(2026, 11, 8, 1, tzinfo=timezone.utc)


def input_fixture():
    targets = [dict(symbol=symbol, name=name, market='KR') for symbol, name in
               [('005930', '삼성전자'), ('000660', 'SK하이닉스'), ('035420', 'NAVER'), ('035720', '카카오')]]
    sources = [dict(evidence_id='candidate:'+row['symbol'], text=row['name']+' 추가 확인이 필요합니다.',
                    title=row['name']+' 저장된 근거', source='AlphaLab_sealed_current_report',
                    published_at=None, fetched_at=(NOW-timedelta(hours=2)).isoformat(), url=None,
                    verification_status='research_not_independent_validation',
                    target_symbols=[row['symbol']], available_at_original_decision=True) for row in targets]
    candidates = [dict(row, rank=index+1, score=90-index*10,
        score_components=dict(saved_metric_name='score', saved_metric_value=.2,
            saved_metric_percentile=.8, leadership_checks_fraction=.5,
            official_evidence_available=False, price_evidence_available=False,
            evidence_completeness_score=0, news_count=0, unverified_news_count=0, negative_news_count=0),
        basis='research_watchlist', entry_status='held', hold_reasons=['entry_window_unavailable'],
        plan=dict(entry_price=100, stop_price=95, target_price=110, horizon_sessions=5),
        reference_price=100, source_at=(NOW-timedelta(hours=2)).isoformat(),
        evidence_ids=['candidate:'+row['symbol']]) for index, row in enumerate(targets)]
    return dict(status='held', targets=targets, sources=sources, candidates=candidates,
        coverage=dict(inspected=40, pool=4, shortlisted=4, with_recent_news=0,
            with_verified_filings=0, with_verified_prices=0, source_count=4),
        warnings=['news_evidence_missing'], decision_id='a'*64, source_input_fingerprint='b'*64,
        source_origin_at=(NOW-timedelta(hours=1)).isoformat(), source_cutoff_at=NOW.isoformat(), fingerprint='c'*64)


@pytest.fixture
def service():
    assert importlib.util.find_spec('app.services.mirofish.alpha_lab.advisor'), 'advisor implementation missing'
    return importlib.import_module('app.services.mirofish.alpha_lab.advisor')


@pytest.fixture
def paths(tmp_path):
    return dict(root=tmp_path/'advisor', alpha_root=tmp_path/'alpha', article_root=tmp_path/'articles')


@pytest.fixture
def supplied(service, monkeypatch):
    item = input_fixture()
    monkeypatch.setattr(service, 'build_input', lambda **kw: deepcopy(item))
    return item


def response_for(request):
    payload = json.loads(request.prompt)
    targets = payload['targets']
    if payload['role'] == 'chair':
        targets = [targets[2], targets[0]]
    rows = []
    for target in targets:
        source = next(row for row in payload['sources'] if target['symbol'] in row['target_symbols'])
        finding = dict(text='추가 근거를 점검할 필요가 있습니다.', claim_status='inference',
            evidence_ids=[source['evidence_id']], quotes=[dict(evidence_id=source['evidence_id'], quote=source['text'][:60])])
        rows.append(dict(target, strengths=[finding], risks=[], what_to_watch=[]))
    return dict(rows=rows)


class Router:
    def __init__(self, *, mutate=None, failure=None, interrupt=None, after=None):
        self.calls = []
        self.mutate, self.failure, self.interrupt, self.after = mutate, failure, interrupt, after

    def route_text(self, request):
        self.calls.append(request)
        role = json.loads(request.prompt)['role']
        if self.interrupt == role:
            raise KeyboardInterrupt()
        if self.failure == role:
            return RoutingResult(text=None, analysis_status=AnalysisStatus.FAILED_TECHNICAL,
                primary_provider='anthropic', fallback_reason='insufficient_balance', attempts=(ProviderAttempt(
                    request_id=request.request_id, provider='anthropic', model='fixture-model', endpoint='messages',
                    operation=request.operation, attempt_number=1, error_class='insufficient_balance',
                    usage=TokenUsage(input_tokens=0, output_tokens=0), estimated_cost_usd=Decimal('0')),))
        value = response_for(request)
        if self.mutate:
            self.mutate(value, role)
        raw = json.dumps(value, ensure_ascii=False)
        if request.response_normalizer:
            request.response_normalizer(raw)
        if self.after:
            self.after(role)
        return RoutingResult(text=raw, analysis_status=AnalysisStatus.SUCCESS_PRIMARY,
            primary_provider='anthropic', actual_provider='anthropic', model='fixture-model',
            evidence_validated=True, usage=TokenUsage(input_tokens=100, output_tokens=30),
            estimated_cost_usd=Decimal('0.001'))


def test_contextual_top3_keeps_frozen_order_and_retains_all_candidates_after_debate(service, paths, supplied):
    supplied.update(source_basis='candidate-regular-v1', source_session='2026-11-06',
                    source_price_basis='KRX_regular_0900_1530_OHLC')
    supplied['candidates'] = supplied['candidates'][:3]
    supplied['targets'] = supplied['targets'][:3]
    supplied['sources'] = supplied['sources'][:3]
    supplied['candidates'][0]['plan']['entry_upper'] = 102
    supplied['candidates'][0]['risk'] = dict(reference_weight=.01, approved_exposure=0., live_orders=False)
    result = service.run_once(**paths, now=NOW, router=Router())
    assert result['debate']['debate_complete']
    assert result['debate']['ranking_basis'] == 'sealed_contextual'
    assert [row['symbol'] for row in result['top3']] == [row['symbol'] for row in supplied['targets']]
    assert [row['rank'] for row in result['top3']] == [1, 2, 3]
    assert result['top3'][1]['strengths'] == []
    assert result['top3'][0]['plan']['entry_upper'] == 102
    assert result['top3'][0]['risk']['approved_exposure'] == 0
    assert result['source_session'] == '2026-11-06'


def test_three_calls_are_dependent_and_chair_ranks_only_supplied_research_rows(service, paths, supplied):
    before = deepcopy(supplied)
    router = Router()
    view = service.run_once(**paths, now=NOW, router=router)
    assert view['status'] == 'ready'
    assert view['debate']['debate_complete'] is True
    assert [row['symbol'] for row in view['top3']] == ['035420', '005930']
    assert [row['rank'] for row in view['top3']] == [1, 2]
    assert [row['baseline_rank'] for row in view['top3']] == [3, 1]
    assert all(row['entry_status'] == 'held' and row['plan']['entry_price'] == 100 for row in view['top3'])
    assert supplied == before
    prompts = [json.loads(call.prompt) for call in router.calls]
    assert [prompt['role'] for prompt in prompts] == ['analyst', 'critic', 'chair']
    assert prompts[0]['prior_stages'] == {}
    assert set(prompts[1]['prior_stages']) == {'analyst'}
    assert set(prompts[2]['prior_stages']) == {'analyst', 'critic'}
    assert prompts[1]['prior_stages']['analyst']['rows'][0]['strengths']
    assert [call.operation for call in router.calls] == [Operation.NEWS_EVENT_EXTRACT, Operation.NEWS_EVENT_EXTRACT, Operation.CANDIDATE_REVIEW]
    assert all(call.max_primary_attempts == 1 and call.temperature == 0 for call in router.calls)
    assert view['debate']['stages'][0]['provider'] == 'anthropic'
    assert view['debate']['stages'][0]['usage']['input_tokens'] == 100
    assert view['debate']['stages'][0]['estimated_cost_usd'] == '0.001'


def test_reads_and_refresh_never_infer_write_or_reset_completed_work(service, paths, supplied, monkeypatch):
    first = Router()
    service.run_once(**paths, now=NOW, router=first)
    before = {str(path): path.read_bytes() for path in paths['root'].rglob('*.json')}
    service.read_view(**paths, now=NOW)
    assert before == {str(path): path.read_bytes() for path in paths['root'].rglob('*.json')}
    queued = service.request_refresh(paths['root'])
    assert queued['status'] == 'queued'
    assert service.request_refresh(paths['root']) == queued
    later = Router()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=later)
    assert later.calls == []
    assert service.read_view(**paths, now=NOW)['debate']['debate_complete'] is True


def test_pending_or_failed_debate_returns_truthful_deterministic_research_picks(service, paths, supplied):
    view = service.read_view(**paths, now=NOW)
    assert view['status'] == 'degraded'
    assert view['debate']['debate_complete'] is False
    assert view['debate']['ranking_basis'] == 'deterministic_research'
    assert [row['symbol'] for row in view['top3']] == ['005930', '000660', '035420']
    assert all(row['strengths'] == [] for row in view['top3'])
    failed = service.run_once(**paths, now=NOW, router=Router(failure='analyst'))
    assert failed['status'] == 'degraded' and not failed['debate']['debate_complete']
    assert failed['debate']['stages'][0]['fallback_reason'] == 'insufficient_balance'


@pytest.mark.parametrize('mutation', ['stale', 'future', 'unavailable', 'binding_changed'])
def test_get_rechecks_current_source_and_cannot_publish_old_chair_result(service, paths, supplied, mutation):
    service.run_once(**paths, now=NOW, router=Router())
    if mutation == 'stale':
        supplied['source_origin_at'] = (NOW-timedelta(hours=73)).isoformat()
    elif mutation == 'future':
        supplied['source_origin_at'] = (NOW+timedelta(minutes=1)).isoformat()
    elif mutation == 'unavailable':
        supplied['status'] = 'unavailable'
        supplied['candidates'] = []
    else:
        supplied['decision_id'] = 'd'*64
        supplied['fingerprint'] = 'e'*64
    view = service.read_view(**paths, now=NOW)
    assert view['debate']['debate_complete'] is False
    if mutation != 'binding_changed':
        assert view['top3'] == []
    else:
        assert view['debate']['ranking_basis'] == 'deterministic_research'
        assert view['top3'][0]['symbol'] == '005930'


@pytest.mark.parametrize('change', ['model', 'prompt', 'eligibility', 'source_text'])
def test_versioned_facts_invalidate_but_poll_clock_never_rebills(service, paths, supplied, monkeypatch, change):
    from dataclasses import replace
    router = Router()
    first = service.run_once(**paths, now=NOW, router=router)
    supplied['source_cutoff_at'] = (NOW+timedelta(minutes=5)).isoformat()
    supplied['sources'][0]['fetched_at'] = (NOW+timedelta(minutes=5)).isoformat()
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(router.calls) == 3
    if change == 'model':
        policy = service.policy_for
        monkeypatch.setattr(service, 'policy_for', lambda op: replace(policy(op), models={'anthropic':'changed-model'}))
    elif change == 'prompt':
        monkeypatch.setitem(service.ROLE_SYSTEM, 'analyst', service.ROLE_SYSTEM['analyst']+' Updated contract.')
    elif change == 'eligibility':
        supplied['candidates'][0]['hold_reasons'].append('new_risk')
    else:
        supplied['sources'][0]['text'] += ' 손실 우려'
    next_view = service.run_once(**paths, now=NOW+timedelta(minutes=6), router=router)
    assert len(router.calls) == 6
    assert first['input_fingerprint'] != next_view['input_fingerprint']


@pytest.mark.parametrize('bad', ['unknown', 'duplicate', 'name', 'overcount', 'extra', 'price', 'empty'])
def test_chair_invalid_ranking_cannot_be_published(service, paths, supplied, bad):
    def mutate(value, role):
        if role != 'chair':
            return
        if bad == 'unknown': value['rows'][0]['symbol'] = '999999'
        elif bad == 'duplicate': value['rows'][1] = deepcopy(value['rows'][0])
        elif bad == 'name': value['rows'][0]['name'] = 'wrong company'
        elif bad == 'overcount': value['rows'] *= 2
        elif bad == 'extra': value['ranking'] = ['035420']
        elif bad == 'price': value['rows'][0]['price'] = 999999
        else: value['rows'] = []
    view = service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert view['status'] == 'degraded'
    assert view['debate']['debate_complete'] is False
    assert view['top3'][0]['symbol'] == '005930'


def test_chair_omits_ungrounded_row_and_preserves_valid_partial_findings(service, paths, supplied):
    def mutate(value, role):
        if role == 'chair':
            value['rows'][0]['strengths'][0]['text'] = '목표가는 백만원입니다'
            value['rows'][1]['risks'] = [deepcopy(value['rows'][1]['strengths'][0])]
            value['rows'][1]['risks'][0]['text'] = '수익률은 999 퍼센트입니다'
    view = service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert view['debate']['debate_complete'] is True
    assert [row['symbol'] for row in view['top3']] == ['005930']
    assert view['debate']['stages'][2]['omitted_findings'] == 2
    assert view['top3'][0]['risks'] == []


def test_cross_symbol_official_filing_cannot_launder_verified_claim(service, paths, supplied):
    official = dict(supplied['sources'][0], evidence_id='filing:only-first',
        text='{"claims":[{"verified":true}],"status":"verified_numeric_claims"}',
        source='OpenDART_saved_verification', verification_status='verified_numeric_claims')
    supplied['sources'].append(official)
    supplied['candidates'][0]['evidence_ids'].append(official['evidence_id'])
    def mutate(value, role):
        if role == 'chair':
            value['rows'] = value['rows'][:1]
            value['rows'][0]['strengths'] = [dict(text='공식 공시의 수치 대조 항목이 일치합니다.',
                claim_status='verified', evidence_ids=[official['evidence_id']],
                quotes=[dict(evidence_id=official['evidence_id'], quote='"verified":true')])]
    view = service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert not view['debate']['debate_complete']
    assert all(row['symbol'] != '035420' or not row['strengths'] for row in view['top3'])


@pytest.mark.parametrize('text', ['즉시 매수해도 안전합니다', '수익률은 95%입니다',
    '공식 공시로 계약이 확정됐습니다', 'guaranteed profitable, buy immediately', 'sk-secret-token'])
def test_untrusted_prose_is_rejected_without_becoming_consensus(service, paths, supplied, text):
    def mutate(value, role):
        for row in value['rows']:
            row['strengths'][0]['text'] = text
    view = service.run_once(**paths, now=NOW, router=Router(mutate=mutate))
    assert not view['debate']['debate_complete']
    assert text not in json.dumps(view, ensure_ascii=False)


def test_public_projection_removes_private_fields_at_every_nested_boundary(service, paths, supplied):
    supplied['sources'][0]['raw'] = 'source-secret'
    supplied['candidates'][0]['plan']['raw'] = 'plan-secret'
    supplied['candidates'][0]['score_components']['prompt'] = 'score-secret'
    supplied['coverage']['raw'] = 'coverage-secret'
    view = service.run_once(**paths, now=NOW, router=Router())
    projected = service.public_projection(dict(view, raw='top-secret',
        debate=dict(view['debate'], raw='debate-secret', stages=[dict(row, raw='stage-secret') for row in view['debate']['stages']])))
    rendered = json.dumps(projected)
    assert 'secret' not in rendered
    assert not any('text' in source for source in projected['sources'])
    assert set(projected) == {'schema_version','status','generated_at','decision_id','input_fingerprint',
        'source_origin_at','source_cutoff_at','coverage','warnings','top3','debate','sources','empty_reason','live_orders'}


def test_stages_span_ticks_and_resume_without_repeating_completed_calls(service, paths, supplied, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    first = Router(after=lambda role: clock.__setitem__(0, clock[0]+60))
    view = service.run_once(**paths, now=NOW, router=first, deadline=210)
    assert [json.loads(call.prompt)['role'] for call in first.calls] == ['analyst','critic']
    assert not view['debate']['debate_complete']
    second = Router()
    view = service.run_once(**paths, now=NOW+timedelta(minutes=5), router=second, deadline=400)
    assert [json.loads(call.prompt)['role'] for call in second.calls] == ['chair']
    assert view['debate']['debate_complete']


def test_zero_usage_failure_cooldown_retries_only_failed_role(service, paths, supplied):
    from app.services.ai_routing.store import RoutingStore
    first = Router(failure='critic')
    service.run_once(**paths, now=NOW, router=first)
    later = Router()
    later.store = RoutingStore(paths['root'].parent/'routing.sqlite3')
    service.run_once(**paths, now=NOW+timedelta(minutes=5), router=later)
    assert later.calls == []
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=later)
    assert [json.loads(call.prompt)['role'] for call in later.calls] == ['critic','chair']
    assert first.calls[1].request_id != later.calls[0].request_id
    assert view['debate']['debate_complete']


def test_interrupted_unknown_request_is_never_redispatched(service, paths, supplied):
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**paths, now=NOW, router=Router(interrupt='critic'))
    recovery = Router()
    view = service.run_once(**paths, now=NOW+timedelta(hours=7), router=recovery)
    assert recovery.calls == []
    assert not view['debate']['debate_complete']
    assert view['debate']['stages'][0]['status'] == 'SUCCESS_PRIMARY'


def test_saved_raw_receipt_recovers_locally_without_rebilling_or_fabricated_metadata(service, paths, supplied):
    def stop_after_receipt(role):
        if role == 'critic': raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**paths, now=NOW, router=Router(after=stop_after_receipt))
    recovery = Router()
    view = service.run_once(**paths, now=NOW+timedelta(minutes=5), router=recovery)
    assert [json.loads(call.prompt)['role'] for call in recovery.calls] == ['chair']
    stage = view['debate']['stages'][1]
    assert stage['status'] == 'RECOVERED_RESPONSE'
    assert stage['provider'] is None and stage['model'] is None
    assert stage['estimated_cost_usd'] is None and not stage['cost_known']
    assert view['status'] == 'degraded' and view['debate']['debate_complete']


def test_paid_invalid_response_is_not_retried_after_cooldown(service, paths, supplied):
    def mutate(value, role):
        if role == 'analyst': value['rows'][0]['symbol'] = '999999'
    first = Router(mutate=mutate)
    service.run_once(**paths, now=NOW, router=first)
    later = Router()
    view = service.run_once(**paths, now=NOW+timedelta(hours=7), router=later)
    assert later.calls == [] and not view['debate']['debate_complete']


def test_worker_does_not_start_stage_without_whole_request_budget(service, paths, supplied, monkeypatch):
    monkeypatch.setattr(service.time, 'monotonic', lambda: 0)
    router = Router()
    view = service.run_once(**paths, now=NOW, router=router, deadline=99)
    assert router.calls == [] and not view['debate']['debate_complete']


def test_corrupt_paid_record_never_triggers_repayment(service, paths, supplied):
    service.run_once(**paths, now=NOW, router=Router())
    path = next((paths['root']/'runs').glob('*.json'))
    path.write_text('{broken', encoding='utf-8')
    router = Router()
    view = service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert router.calls == [] and not view['debate']['debate_complete']
    assert view['status'] == 'degraded'


def test_worker_lock_prevents_duplicate_inference(service, paths, supplied):
    from filelock import FileLock, Timeout
    paths['root'].mkdir()
    router = Router()
    with FileLock(str(paths['root']/'worker.lock')):
        with pytest.raises(Timeout):
            service.run_once(**paths, now=NOW, router=router)
    assert not router.calls


def native_router(paths, primary, fallback=None):
    from app.services.ai_routing.router import AIRouter
    from app.services.ai_routing.store import RoutingStore
    adapters = {'anthropic': primary}
    if fallback:
        adapters['deepseek'] = fallback
    return AIRouter(adapters, store=RoutingStore(paths['root'].parent/'routing.sqlite3'))


class Native:
    endpoint = 'fixture'

    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def generate(self, request, **kwargs):
        from app.services.ai_routing.providers import AdapterResponse
        self.calls.append(request)
        value = response_for(request)
        if self.mutate:
            self.mutate(value, json.loads(request.prompt)['role'])
        return AdapterResponse(json.dumps(value, ensure_ascii=False), TokenUsage(input_tokens=100, output_tokens=30))


def test_real_router_fallback_publishes_only_selected_receipt_and_total_charge(service, paths, supplied):
    def invalid(value, role):
        for row in value['rows']:
            row['strengths'][0]['text'] = '목표가는 백만원입니다'
    primary, fallback = Native(invalid), Native()
    view = service.run_once(**paths, now=NOW, router=native_router(paths, primary, fallback))
    assert view['status'] == 'degraded' and view['debate']['debate_complete']
    assert all(stage['provider'] == 'deepseek' and stage['status'] == 'SUCCESS_FALLBACK' for stage in view['debate']['stages'])
    assert all(stage['omitted_findings'] == 0 for stage in view['debate']['stages'])
    assert all(stage['cost_known'] and Decimal(stage['estimated_cost_usd']) > 0 for stage in view['debate']['stages'])
    assert all(stage['usage']['input_tokens'] == 200 and stage['usage']['output_tokens'] == 60 for stage in view['debate']['stages'])
    assert '백만원' not in json.dumps(view, ensure_ascii=False)
    record = service._read(next((paths['root']/'runs').glob('*.json')))
    assert record['stages']['analyst']['raw_receipts'][0]['validation_error'] == 'all_findings_invalid'
    assert len(record['stages']['analyst']['raw_receipts']) == 2
    assert len(primary.calls) == 3 and len(fallback.calls) == 3


def test_real_router_receipt_write_failure_stops_fallback_and_never_recovers_success(service, paths, supplied, monkeypatch):
    primary, fallback = Native(), Native()
    write = service._write
    failed = []
    def fail_raw(path, value):
        if not failed and any(stage.get('raw_receipts') for stage in value.get('stages', {}).values()):
            failed.append(True)
            raise OSError('receipt disk failure')
        write(path, value)
    monkeypatch.setattr(service, '_write', fail_raw)
    view = service.run_once(**paths, now=NOW, router=native_router(paths, primary, fallback))
    assert len(primary.calls) == 1 and len(fallback.calls) == 0
    assert view['status'] == 'degraded' and not view['debate']['debate_complete']
    assert view['debate']['stages'][0]['fallback_reason'] == 'response_receipt_unavailable'
    later = Native()
    view = service.run_once(**paths, now=NOW+timedelta(hours=7), router=native_router(paths, later))
    assert not later.calls and not view['debate']['debate_complete']


def test_raw_receipt_is_durable_before_any_normalization_and_repaired_after_kill(service, paths, supplied, monkeypatch):
    normalize = service._normalize
    interrupted = []
    def stop_before_validation(value, item, role, **kwargs):
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt()
        return normalize(value, item, role, **kwargs)
    monkeypatch.setattr(service, '_normalize', stop_before_validation)
    with pytest.raises(KeyboardInterrupt):
        service.run_once(**paths, now=NOW, router=Router())
    record = service._read(next((paths['root']/'runs').glob('*.json')))
    receipt = record['stages']['analyst']['raw_receipts'][0]
    assert receipt['raw'] and 'normalized' not in receipt
    restart = Router()
    view = service.run_once(**paths, now=NOW, router=restart)
    assert [json.loads(call.prompt)['role'] for call in restart.calls] == ['critic', 'chair']
    assert view['debate']['stages'][0]['status'] == 'RECOVERED_RESPONSE'
    assert view['debate']['debate_complete']


def test_shared_router_budget_exhaustion_keeps_real_completed_stage_and_never_consensus(service, paths, supplied, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    primary = Native()
    view = service.run_once(**paths, now=NOW, router=native_router(paths, primary))
    assert len(primary.calls) == 1
    assert view['debate']['stages'][0]['status'] == 'SUCCESS_PRIMARY'
    assert view['debate']['stages'][1]['fallback_reason'] == 'budget_exhausted'
    assert not view['debate']['debate_complete']
    assert view['top3'][0]['symbol'] == '005930'


def test_router_ledger_receipt_loss_cannot_repay_dispatched_request(service, paths, supplied, monkeypatch):
    from app.services.ai_routing import router as routing_module
    primary = Native()
    def lose_ledger_receipt(*args, **kwargs):
        raise OSError('ledger receipt unavailable')
    monkeypatch.setattr(routing_module, 'record_attempt', lose_ledger_receipt)
    view = service.run_once(**paths, now=NOW, router=native_router(paths, primary))
    assert len(primary.calls) == 1 and not view['debate']['debate_complete']
    later = Native()
    service.run_once(**paths, now=NOW+timedelta(hours=7), router=native_router(paths, later))
    assert not later.calls


def test_get_waits_for_final_seal_and_worker_reseals_without_new_calls(service, paths, supplied):
    service.run_once(**paths, now=NOW, router=Router())
    path = next((paths['root']/'runs').glob('*.json'))
    record = service._read(path)
    record['final'] = None
    service._write(path, record)
    view = service.read_view(**paths, now=NOW)
    assert view['status'] == 'degraded' and not view['debate']['debate_complete']
    assert view['top3'][0]['symbol'] == '005930'
    router = Router()
    final = service.run_once(**paths, now=NOW, router=router)
    assert not router.calls and final['debate']['debate_complete']


def test_read_preserves_debate_source_clocks_after_fact_identical_refresh(service, paths, supplied):
    first = service.run_once(**paths, now=NOW, router=Router())
    supplied['source_cutoff_at'] = (NOW+timedelta(minutes=10)).isoformat()
    supplied['sources'][0]['fetched_at'] = (NOW+timedelta(minutes=10)).isoformat()
    read = service.read_view(**paths, now=NOW+timedelta(minutes=10))
    assert read['source_cutoff_at'] == first['source_cutoff_at']
    assert read['sources'][0]['fetched_at'] == first['sources'][0]['fetched_at']


def test_budget_replenishment_resumes_same_request_identity_without_replaying_analyst(service, paths, supplied, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    primary = Native()
    router = native_router(paths, primary)
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['critic']['request_id']
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    waiting = service.run_once(**paths, now=NOW+timedelta(minutes=5), router=router)
    assert len(primary.calls) == 1 and not waiting['debate']['debate_complete']
    # Reuse the actual router/process, including its single-flight result cache.
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert [json.loads(call.prompt)['role'] for call in primary.calls] == ['analyst', 'critic', 'chair']
    assert primary.calls[1].request_id == denied
    assert view['debate']['debate_complete']


@pytest.mark.parametrize('settled', [False, True])
def test_same_identity_budget_retry_respects_claimed_and_charged_ledger_fences(service, paths, supplied, monkeypatch, settled):
    from app.services.ai_routing import RoutingRequest
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    primary, fallback = Native(), Native()
    router = native_router(paths, primary, fallback)
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['critic']['request_id']
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    # Represent another process's unknown/charged receipt for this identity.
    budget = EvidenceReviewBudget(router.store)
    permit = budget.reserve_attempt(request=RoutingRequest(operation=Operation.NEWS_EVENT_EXTRACT,
        prompt='fixture', run_id='other-process', request_id=denied), provider='anthropic',
        input_tokens=100, output_tokens=30, estimated_cost_usd=Decimal('0.01'), pricing_version='fixture')
    assert permit.approved
    if settled:
        assert budget.settle(permit.reservation_id, TokenUsage(input_tokens=100, output_tokens=30), actual_cost_usd=Decimal('0.001'))
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    service.run_once(**paths, now=NOW+timedelta(hours=4), router=router)
    assert len(primary.calls) == 1 and fallback.calls == []
    assert not view['debate']['debate_complete']
    saved = service._read(path)['stages']['critic']
    assert saved['request_id'] == denied
    assert saved['history'] == []
    assert view['debate']['stages'][1]['fallback_reason'] == 'retry_prior_charge_or_unknown'


def test_unknown_empty_attempts_cannot_enter_same_identity_budget_retry(service, paths, supplied):
    class Unknown:
        def __init__(self):
            self.calls = []

        def route_text(self, request):
            self.calls.append(request)
            return RoutingResult(text=None, analysis_status=AnalysisStatus.FAILED_TECHNICAL,
                primary_provider='anthropic', fallback_reason='unknown', attempts=())
    router = Unknown()
    service.run_once(**paths, now=NOW, router=router)
    service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert len(router.calls) == 1


@pytest.mark.parametrize('reserved_provider', ['anthropic', 'deepseek'])
@pytest.mark.parametrize('settled', [False, True])
def test_missing_primary_cannot_bypass_unknown_or_charged_request_reservations(service, paths, supplied, monkeypatch, reserved_provider, settled):
    from app.services.ai_routing import RoutingRequest
    from app.services.ai_routing.budget import EvidenceReviewBudget
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    primary, fallback = Native(), Native()
    router = native_router(paths, primary, fallback)
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['critic']['request_id']
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    budget = EvidenceReviewBudget(router.store)
    permit = budget.reserve_attempt(request=RoutingRequest(operation=Operation.NEWS_EVENT_EXTRACT,
        prompt='fixture', run_id='other-process', request_id=denied), provider=reserved_provider,
        input_tokens=100, output_tokens=30, estimated_cost_usd=Decimal('0.01'), pricing_version='fixture')
    assert permit.approved
    if settled:
        assert budget.settle(permit.reservation_id, TokenUsage(input_tokens=100, output_tokens=30), actual_cost_usd=Decimal('0.001'))
    router.adapters.pop('anthropic')
    service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    view = service.run_once(**paths, now=NOW+timedelta(hours=4), router=router)
    assert len(primary.calls) == 1 and fallback.calls == []
    assert not view['debate']['debate_complete']
    assert service._read(path)['stages']['critic']['request_id'] == denied


@pytest.mark.parametrize('proof', ['missing', 'unreadable'])
def test_admission_retry_fails_closed_without_readable_shared_ledger(service, paths, supplied, monkeypatch, proof):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    service.run_once(**paths, now=NOW, router=native_router(paths, Native()))
    retry = Router()
    if proof == 'unreadable':
        class BrokenStore:
            def transaction(self, **kwargs):
                raise OSError('fixture ledger read failure')
        retry.store = BrokenStore()
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=retry)
    assert retry.calls == []
    assert view['debate']['stages'][1]['fallback_reason'] == 'retry_ledger_unavailable'


def test_budget_denial_after_skipped_primary_never_mints_new_identity(service, paths, supplied, monkeypatch):
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '0')
    primary, fallback = Native(), Native()
    router = native_router(paths, primary, fallback)
    router.adapters.pop('anthropic')
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['analyst']['request_id']
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert fallback.calls[0].request_id == denied
    assert view['debate']['debate_complete']


def test_generic_openai_reservation_also_blocks_advisor_retry(service, paths, supplied, monkeypatch):
    from app.services.ai_routing.budget import BudgetManager
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    primary = Native()
    router = native_router(paths, primary)
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['critic']['request_id']
    generic = BudgetManager(router.store)
    permit = generic.reserve(run_id='other-process', request_id=denied, operation=Operation.NEWS_EVENT_EXTRACT,
        input_tokens=100, output_tokens=30, estimated_cost_usd=Decimal('0.01'), cost_pricing_version='fixture')
    assert permit.approved
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert len(primary.calls) == 1 and not view['debate']['debate_complete']
    assert view['debate']['stages'][1]['fallback_reason'] == 'retry_prior_charge_or_unknown'


def test_native_definitive_zero_use_settlement_allows_new_identity_retry(service, paths, supplied):
    from app.services.ai_routing.providers import ProviderCallError
    class ZeroUse:
        endpoint = 'fixture'
        def generate(self, request, **kwargs):
            raise ProviderCallError('empty', usage=TokenUsage(input_tokens=0, output_tokens=0))
    router = native_router(paths, ZeroUse())
    service.run_once(**paths, now=NOW, router=router)
    path = next((paths['root']/'runs').glob('*.json'))
    rejected = service._read(path)['stages']['analyst']['request_id']
    primary = Native()
    router.adapters['anthropic'] = primary
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert len(primary.calls) == 3 and primary.calls[0].request_id != rejected
    assert view['debate']['debate_complete']


def test_zero_use_primary_then_fallback_budget_denial_recovers_with_ledger_proven_new_id(service, paths, supplied, monkeypatch):
    from app.services.ai_routing.providers import ProviderCallError
    class ZeroUse:
        endpoint = 'fixture'
        def generate(self, request, **kwargs):
            raise ProviderCallError('empty', usage=TokenUsage(input_tokens=0, output_tokens=0))
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '1')
    fallback = Native()
    router = native_router(paths, ZeroUse(), fallback)
    first = service.run_once(**paths, now=NOW, router=router)
    assert first['debate']['stages'][0]['fallback_reason'] == 'budget_exhausted'
    assert fallback.calls == []
    path = next((paths['root']/'runs').glob('*.json'))
    denied = service._read(path)['stages']['analyst']['request_id']
    monkeypatch.setenv('AI_EVIDENCE_REVIEW_DAILY_MAX_CALLS', '100')
    primary = Native()
    router.adapters['anthropic'] = primary
    view = service.run_once(**paths, now=NOW+timedelta(hours=2), router=router)
    assert [json.loads(call.prompt)['role'] for call in primary.calls] == ['analyst', 'critic', 'chair']
    assert primary.calls[0].request_id != denied
    assert view['debate']['debate_complete'] and fallback.calls == []
