from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import outcome_tracker, workflow


@pytest.fixture(autouse=True)
def _disable_tradingagents_layer(monkeypatch):
    """These tests exercise the ranking / kalman / outcome pipeline in isolation.

    The TradingAgents deep-verification layer (Task 6) is default-ON in production
    and wired into `_complete_workflow`, but these pre-existing integration tests
    do not mock it. Left live it would invoke the real multi-agent engine per
    candidate — slow, log-noisy, writes to the real repo data dir, and its rule
    verdict depends on shared on-disk data (sector RS cache), making these tests
    order-dependent. Gate it off so each test remains hermetic and deterministic.
    TradingAgents intervention itself is covered by
    tests/test_mirofish_tradingagents_workflow.py.
    """
    monkeypatch.setenv('MIROFISH_TRADINGAGENTS_DISABLED', 'true')


def _candidate(symbol, name, alpha, risk, rank=1, action='BUY_CANDIDATE'):
    observed_at = '2026-05-07T06:00:00+00:00'
    return {
        'rank': rank,
        'symbol': symbol,
        'name': name,
        'display_name': name,
        'market': 'KOSPI',
        'action': action,
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_score': alpha - risk * 0.5,
        'signal_quality': 'high_conviction' if alpha >= 80 else 'actionable',
        'strategy_tags': ['momentum', 'trend_quality'],
        'analysis_profile': {
            'source_count': 4,
            'trend_20d_pct': 20 + rank,
            'volume_ratio': 1.5,
            'profitability_scorecard': {
                'goal_fit_score': 78,
                'goal_verdict': 'candidate_needs_confirmation',
                'hard_blockers': [],
                'missing_confirmations': ['capital_flow'],
                'ranking_effect': 'direct_bounded_quality_adjustment',
            },
        },
        'entry_plan': {'status': 'ready'},
        'price': {'date': '2026-05-07', 'current_price': 1000 * rank},
        'generated_at': observed_at,
        'source_cutoff': observed_at,
        'source': 'local_marketflow_artifacts',
        'freshness': {'status': 'fresh'},
        'source_packets': [{
            'evidence_id': f'scanner-{symbol}', 'source': 'local_marketflow_artifacts',
            'fetched_at': observed_at, 'freshness': 'fresh', 'confidence': 1.0,
            'content': {'price': 1000 * rank},
        }],
    }


def _scanner_result(candidates):
    return {
        'run': {
            'id': 'mfas_test',
            'candidate_count': len(candidates),
            'freshness': {'status': 'fresh'},
            'candidates': candidates,
        },
        'events': [
            {
                'event_key': f"{item['symbol']}:{item['action']}:2026-05-07",
                'key': f"{item['symbol']}:{item['action']}:2026-05-07",
                'candidate': item,
            }
            for item in candidates
        ],
        'new_event_count': len(candidates),
        'alert_blocked': False,
        'blocked_reason': None,
        'state_path': 'unused.json',
        'state': {},
    }


def _analysis_run(candidate, action='BUY', confidence=75, graph_links=40, brain_score=60):
    return {
        'id': f"mf_{candidate['symbol']}",
        'status': 'completed',
        'analysis_status': 'SUCCESS_PRIMARY',
        'display_name': candidate['display_name'],
        'symbol': candidate['symbol'],
        'market': candidate['market'],
        'pipeline': {'graph_links': graph_links, 'similar_events': 3, 'graph_method': 'rule'},
        'brain': {'score': brain_score, 'regime': 'neutral', 'crisis': 'Lv.2'},
        'verdict': {
            'action': action,
            'label': action,
            'confidence_pct': confidence,
            'bullish': 5,
            'neutral': 4,
            'bearish': 1,
            'target': candidate['display_name'],
            'summary': f"{candidate['display_name']} {action}",
        },
        'artifacts': {'run': f"/api/admin/mirofish/runs/mf_{candidate['symbol']}"},
    }


def test_automatic_analysis_seam_uses_compact_once_without_legacy_stack(monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 85, 20)
    monkeypatch.setattr(workflow.store, 'create_run', pytest.fail)
    captured = []
    monkeypatch.setattr(
        workflow.ta_engine, 'run_deep_analysis',
        lambda target, **kwargs: captured.append(kwargs) or {
            'id': 'ta_compact', 'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'verdict': 'BUY', 'confidence': 80},
        },
    )
    monkeypatch.setattr(
        workflow.store, 'create_compact_run',
        lambda candidate, ta, **kwargs: {'id': 'mf_compact', 'source_run_id': ta['id']},
    )
    out = workflow._create_analysis_run(candidate, 10, 'full', workflow_id='mcp_parent')
    assert out['source_run_id'] == 'ta_compact'
    assert len(captured) == 1
    assert captured[0]['profile'] == 'compact'
    assert captured[0]['routing_run_id'] == 'mcp_parent'


def test_scanner_summary_never_synthesizes_missing_source_provenance():
    candidate = _candidate('005930', '삼성전자', 85, 20)
    candidate.pop('source_packets')

    summary = workflow._candidate_summary(candidate)
    with pytest.raises(ValueError, match='provenance'):
        workflow._build_candidate_packet(summary, use_llm=True)


def test_scanner_candidate_with_partial_required_provenance_is_rejected():
    candidate = _candidate('005930', '삼성전자', 85, 20)
    candidate['provenance_missing'] = ['dart_event_latest.json']

    with pytest.raises(ValueError, match='required provenance'):
        workflow._build_candidate_packet(candidate, use_llm=True)


def test_candidate_summary_source_cutoff_uses_timezone_aware_maximum():
    candidate = _candidate('005930', '삼성전자', 85, 20)
    candidate.pop('source_cutoff')
    candidate['source_packets'] = [
        {**candidate['source_packets'][0], 'fetched_at': '2026-09-03T10:00:00+09:00'},
        {**candidate['source_packets'][0], 'evidence_id': 'later',
         'fetched_at': '2026-09-03T03:00:00+00:00'},
    ]

    summary = workflow._candidate_summary(candidate)

    assert summary['source_cutoff'] == '2026-09-03T03:00:00+00:00'


def test_candidate_admission_happens_before_executor_submission(tmp_path, monkeypatch):
    candidates = [_candidate(f'{index:06d}', f'종목{index}', 90 - index, 20, index) for index in range(10)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    submitted = []
    monkeypatch.setattr(
        workflow, '_create_analysis_run',
        lambda candidate, agent_count, mode: submitted.append(candidate['symbol']) or _analysis_run(candidate),
    )
    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 10, 'top_n': 3, 'require_buy': False}, async_mode=False,
    )
    assert len(submitted) == 5
    assert result['budget_summary']['admitted'] == 5
    assert result['budget_summary']['deferred'] == 5


def test_budget_permits_are_reserved_before_worker_submission(tmp_path, monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidates = [_candidate('005930', '삼성전자', 90, 20)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *a, **k: _scanner_result(candidates))
    order = []
    def reserve(run_id, packets):
        order.append('reserve')
        packet = packets[0]
        return ([{'packet': packet, 'request_ids': {'decisive_text': 'stable-request'},
                  'reservation_ids': {'decisive_text': 'permit-1'}}],
                [{'symbol': packet['symbol'], 'status': 'admitted'}])
    monkeypatch.setattr(workflow.ta_engine, 'reserve_compact_batch', reserve)
    def create(candidate, agent_count, mode, *, workflow_id=None, force=False,
               evidence_packet=None, request_ids=None, reservation_ids=None,
               permits_preflighted=False):
        order.append('submit')
        assert request_ids['decisive_text'] == 'stable-request'
        assert reservation_ids['decisive_text'] == 'permit-1'
        return _analysis_run(candidate)
    monkeypatch.setattr(workflow, '_create_analysis_run', create)
    workflow.start_workflow_from_scanner_events(
        {'max_events': 1, 'top_n': 1, 'require_buy': False}, async_mode=False)
    assert order == ['reserve', 'submit']


def test_preflight_permits_are_released_when_executor_creation_fails(tmp_path, monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packets[0],
            'request_ids': {'decisive_text': 'stable-request'},
            'reservation_ids': {'decisive_text': 'permit-1'},
            'reservation_owner_tokens': {'decisive_text': 'owner-1'},
        }], [{'symbol': '005930', 'status': 'admitted'}]),
    )
    released = []
    monkeypatch.setattr(
        workflow.ta_engine, 'release_compact_permits',
        lambda permits, owners: released.append((dict(permits), dict(owners))),
    )
    monkeypatch.setattr(
        workflow.concurrent.futures, 'ThreadPoolExecutor',
        lambda **kwargs: (_ for _ in ()).throw(OSError('executor unavailable')),
    )

    with pytest.raises(OSError, match='executor unavailable'):
        workflow.start_workflow_from_scanner_events(
            {'max_events': 1, 'top_n': 1, 'require_buy': False}, async_mode=False,
        )

    assert released == [(
        {'decisive_text': 'permit-1'}, {'decisive_text': 'owner-1'},
    )]


def test_partial_executor_submission_aborts_already_running_worker(tmp_path, monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidates = [
        _candidate('005930', '삼성전자', 90, 20),
        _candidate('000660', 'SK하이닉스', 89, 20),
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result(candidates),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packet,
            'request_ids': {'decisive_text': f'request-{index}'},
            'reservation_ids': {'decisive_text': f'permit-{index}'},
            'reservation_owner_tokens': {'decisive_text': f'owner-{index}'},
        } for index, packet in enumerate(packets)], [
            {'symbol': packet['symbol'], 'status': 'admitted'} for packet in packets
        ]),
    )
    monkeypatch.setattr(workflow.ta_engine, 'release_compact_permits', lambda *_args: None)
    worker_started = workflow.threading.Event()
    worker_saw_abort = workflow.threading.Event()

    def invoke(candidate, *args, permit_abort_event=None, **kwargs):
        worker_started.set()
        if permit_abort_event.wait(timeout=0.5):
            worker_saw_abort.set()
        return _analysis_run(candidate)

    monkeypatch.setattr(workflow, '_invoke_analysis_run', invoke)
    original_executor = workflow.concurrent.futures.ThreadPoolExecutor

    class PartialFailExecutor:
        def __init__(self, **kwargs):
            self.delegate = original_executor(max_workers=1)
            self.submissions = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.delegate.shutdown(wait=True)

        def submit(self, *args, **kwargs):
            self.submissions += 1
            if self.submissions == 2:
                raise OSError('second submit failed')
            future = self.delegate.submit(*args, **kwargs)
            assert worker_started.wait(timeout=0.5)
            return future

    monkeypatch.setattr(workflow.concurrent.futures, 'ThreadPoolExecutor', PartialFailExecutor)

    with pytest.raises(OSError, match='second submit failed'):
        workflow.start_workflow_from_scanner_events(
            {'max_events': 2, 'top_n': 2, 'max_parallel': 1, 'require_buy': False},
            async_mode=False,
        )

    assert worker_saw_abort.is_set()


def test_supervision_exception_aborts_running_worker(tmp_path, monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packets[0], 'request_ids': {'decisive_text': 'request'},
            'reservation_ids': {'decisive_text': 'permit'},
            'reservation_owner_tokens': {'decisive_text': 'owner'},
        }], [{'symbol': '005930', 'status': 'admitted'}]),
    )
    monkeypatch.setattr(workflow.ta_engine, 'release_compact_permits', lambda *_args: None)
    worker_started = workflow.threading.Event()
    worker_saw_abort = workflow.threading.Event()

    def invoke(candidate, *args, permit_abort_event=None, **kwargs):
        worker_started.set()
        if permit_abort_event.wait(timeout=0.5):
            worker_saw_abort.set()
        return _analysis_run(candidate)

    def fail_wait(*args, **kwargs):
        assert worker_started.wait(timeout=0.5)
        raise OSError('wait failed')

    monkeypatch.setattr(workflow, '_invoke_analysis_run', invoke)
    monkeypatch.setattr(workflow.concurrent.futures, 'wait', fail_wait)

    with pytest.raises(OSError, match='wait failed'):
        workflow.start_workflow_from_scanner_events(
            {'max_events': 1, 'top_n': 1, 'max_parallel': 1, 'require_buy': False},
            async_mode=False,
        )

    assert worker_saw_abort.is_set()


def test_max_parallel_one_renews_queued_permit_until_second_candidate_claims(
    tmp_path, monkeypatch,
):
    from app.services.ai_routing.budget import BudgetManager
    from app.services.ai_routing.contracts import Operation, TokenUsage
    from app.services.ai_routing.store import RoutingStore

    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    monkeypatch.setenv('AI_OPENAI_PERMIT_LEASE_SECONDS', '1')
    candidates = [
        _candidate('005930', '삼성전자', 90, 20),
        _candidate('000660', 'SK하이닉스', 89, 20),
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result(candidates),
    )
    now = {'value': datetime(2026, 9, 3, tzinfo=timezone.utc)}
    monkeypatch.setattr(
        'app.services.ai_routing.budget._utc_now_datetime', lambda: now['value'],
    )
    manager = BudgetManager(RoutingStore(tmp_path / 'usage.sqlite3'))
    request_ids = {}

    def reserve_batch(run_id, packets):
        prepared = []
        records = []
        for index, packet in enumerate(packets):
            request_id = f'{run_id}:{index}:decisive'
            owner = f'owner-{index}'
            permit = manager.reserve(
                run_id=run_id, request_id=request_id,
                operation=Operation.DECISIVE_TEXT,
                input_tokens=100, output_tokens=100, owner_token=owner,
            )
            request_ids[packet['symbol']] = request_id
            prepared.append({
                'packet': packet,
                'request_ids': {'decisive_text': request_id},
                'reservation_ids': {'decisive_text': permit.reservation_id},
                'reservation_owner_tokens': {'decisive_text': owner},
            })
            records.append({'symbol': packet['symbol'], 'status': 'admitted'})
        return prepared, records

    monkeypatch.setattr(workflow.ta_engine, 'reserve_compact_batch', reserve_batch)
    first_can_finish = workflow.threading.Event()
    renewals = []

    def renew(permits, owners):
        now['value'] += timedelta(milliseconds=600)
        renewals.append(now['value'])
        ok = manager.renew_many([
            (reservation_id, owners[operation])
            for operation, reservation_id in permits.items()
        ], terminal_ok=True)
        if len(renewals) >= 2:
            first_can_finish.set()
        return ok

    monkeypatch.setattr(workflow.ta_engine, 'renew_compact_permits', renew, raising=False)
    monkeypatch.setattr(workflow.ta_engine, 'compact_permit_heartbeat_seconds', lambda: 0.001, raising=False)
    monkeypatch.setattr(
        workflow.ta_engine, 'release_compact_permits',
        lambda permits, owners: [
            manager.release(reservation_id, owner_token=owners[operation])
            for operation, reservation_id in permits.items()
        ],
    )
    claims = []

    def create(candidate, agent_count, mode, *, workflow_id=None, force=False,
               evidence_packet=None, request_ids=None, reservation_ids=None,
               reservation_owner_tokens=None, permits_preflighted=False):
        operation = 'decisive_text'
        claim = manager.claim(
            reservation_ids[operation], run_id=workflow_id,
            request_id=request_ids[operation],
            owner_token=reservation_owner_tokens[operation],
            input_tokens=100, output_tokens=100,
        )
        claims.append((candidate['symbol'], claim.approved, claim.reason))
        if candidate['symbol'] == '005930' and not first_can_finish.wait(timeout=0.2):
            now['value'] += timedelta(seconds=2)
        if claim.approved:
            manager.settle(
                reservation_ids[operation], TokenUsage(input_tokens=10, output_tokens=5),
            )
        return _analysis_run(candidate)

    monkeypatch.setattr(workflow, '_create_analysis_run', create)

    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 2, 'top_n': 2, 'max_parallel': 1, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert len(renewals) >= 2
    assert claims == [
        ('005930', True, None),
        ('000660', True, None),
    ]
    assert manager.snapshot(result['id']).used_calls == 2


def test_permit_renewal_persistence_failure_fails_closed_workflow(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packets[0],
            'request_ids': {'decisive_text': 'stable-request'},
            'reservation_ids': {'decisive_text': 'permit-1'},
            'reservation_owner_tokens': {'decisive_text': 'owner-1'},
        }], [{'symbol': '005930', 'status': 'admitted'}]),
    )
    worker_can_finish = workflow.threading.Event()

    def renew(*_args, **_kwargs):
        worker_can_finish.set()
        raise OSError('budget store unavailable')

    monkeypatch.setattr(workflow.ta_engine, 'renew_compact_permits', renew, raising=False)
    monkeypatch.setattr(workflow.ta_engine, 'compact_permit_heartbeat_seconds', lambda: 0.001, raising=False)
    monkeypatch.setattr(workflow.ta_engine, 'release_compact_permits', lambda *_args: None)

    def create(candidate, agent_count, mode, **kwargs):
        worker_can_finish.wait(timeout=0.2)
        return _analysis_run(candidate)

    monkeypatch.setattr(workflow, '_create_analysis_run', create)

    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 1, 'top_n': 1, 'max_parallel': 1, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'failed'
    assert result['analysis_status'] == 'FAILED_TECHNICAL'
    assert result['failure_reason'] == 'permit_lease_renewal_failed'
    assert result['top3'] == []
    assert result['analysis_runs'][0]['status'] == 'failed'
    assert result['analysis_runs'][0]['error'] == 'PermitLeaseError: permit_lease_renewal_failed'


def test_aborted_permit_worker_never_enters_analysis(monkeypatch):
    abort = workflow.threading.Event()
    abort.set()
    monkeypatch.setattr(workflow, '_create_analysis_run', pytest.fail)

    with pytest.raises(RuntimeError, match='permit_lease_renewal_failed'):
        workflow._invoke_analysis_run(
            _candidate('005930', '삼성전자', 90, 20),
            10, 'full', 'wf-aborted', False,
            permit_abort_event=abort,
        )


def test_permit_abort_event_is_forwarded_into_compact_engine(monkeypatch):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    abort = workflow.threading.Event()
    captured = []
    monkeypatch.setattr(
        workflow.ta_engine, 'run_deep_analysis',
        lambda target, **kwargs: captured.append(kwargs) or {
            'id': 'ta_abort_fence', 'analysis_status': 'SUCCESS_PRIMARY',
            'verdict': {'verdict': 'BUY', 'confidence': 80},
        },
    )
    monkeypatch.setattr(
        workflow.store, 'create_compact_run',
        lambda candidate, ta, **kwargs: {'id': 'mf_abort_fence'},
    )

    workflow._invoke_analysis_run(
        _candidate('005930', '삼성전자', 90, 20),
        10, 'full', 'wf-abort-fence', False,
        permit_abort_event=abort,
    )

    assert captured[0]['permit_abort_event'] is abort


def test_worker_abort_signal_promotes_workflow_to_lease_failure_without_tick(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packets[0], 'request_ids': {'decisive_text': 'request'},
            'reservation_ids': {'decisive_text': 'permit'},
            'reservation_owner_tokens': {'decisive_text': 'owner'},
        }], [{'symbol': '005930', 'status': 'admitted'}]),
    )
    monkeypatch.setattr(workflow.ta_engine, 'release_compact_permits', lambda *_args: None)
    monkeypatch.setattr(workflow.ta_engine, 'compact_permit_heartbeat_seconds', lambda: 60)

    def create(
        candidate, *args, workflow_id=None, permit_abort_event=None, **kwargs,
    ):
        permit_abort_event.set()
        raise RuntimeError('permit_lease_renewal_failed')

    monkeypatch.setattr(workflow, '_create_analysis_run', create)

    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 1, 'top_n': 1, 'max_parallel': 1, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'failed'
    assert result['failure_reason'] == 'permit_lease_renewal_failed'
    assert result['top3'] == []


def test_renewal_and_cleanup_persistence_failure_still_returns_failed_workflow(
    tmp_path, monkeypatch,
):
    monkeypatch.delenv('MIROFISH_TRADINGAGENTS_DISABLED', raising=False)
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(
        workflow.ta_engine, 'reserve_compact_batch',
        lambda run_id, packets: ([{
            'packet': packets[0], 'request_ids': {'decisive_text': 'request'},
            'reservation_ids': {'decisive_text': 'permit'},
            'reservation_owner_tokens': {'decisive_text': 'owner'},
        }], [{'symbol': '005930', 'status': 'admitted'}]),
    )
    worker_can_finish = workflow.threading.Event()

    def fail_renew(*_args):
        worker_can_finish.set()
        raise OSError('renew unavailable')

    monkeypatch.setattr(workflow.ta_engine, 'renew_compact_permits', fail_renew)
    monkeypatch.setattr(workflow.ta_engine, 'compact_permit_heartbeat_seconds', lambda: 0.001)
    monkeypatch.setattr(
        workflow.ta_engine, 'release_compact_permits',
        lambda *_args: (_ for _ in ()).throw(OSError('cleanup unavailable')),
    )
    monkeypatch.setattr(
        workflow, '_create_analysis_run',
        lambda candidate, *args, **kwargs: (
            worker_can_finish.wait(timeout=0.2) and _analysis_run(candidate)
        ),
    )

    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 1, 'top_n': 1, 'max_parallel': 1, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'failed'
    assert result['failure_reason'] == 'permit_lease_renewal_failed'


def test_automatic_kill_switch_does_not_run_compact_or_legacy(monkeypatch):
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis', pytest.fail)
    monkeypatch.setattr(workflow.store, 'create_run', pytest.fail)
    with pytest.raises(RuntimeError, match='disabled'):
        workflow._create_analysis_run(candidate, 10, 'full', workflow_id='wf')


def test_automatic_kill_switch_projects_explicit_disabled_workflow(tmp_path, monkeypatch):
    candidate = _candidate('005930', '삼성전자', 90, 20)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner, 'run_scanner_alert_check',
        lambda *args, **kwargs: _scanner_result([candidate]),
    )
    monkeypatch.setattr(workflow.ta_engine, 'run_deep_analysis', pytest.fail)
    monkeypatch.setattr(workflow.ta_engine, 'reserve_compact_batch', pytest.fail)
    monkeypatch.setattr(workflow.store, 'create_run', pytest.fail)

    result = workflow.start_workflow_from_scanner_events(
        {'max_events': 1, 'top_n': 1, 'require_buy': False}, async_mode=False,
    )

    assert result['status'] == 'disabled'
    assert result['analysis_status'] == 'DISABLED'
    assert result['analysis_runs'] == []
    assert result['top3'] == []
    assert result['progress']['phase'] == 'disabled'
    assert result['progress']['percent'] < 100
    assert result['budget_summary']['reason'] == 'tradingagents_disabled'


def test_analysis_projection_preserves_decision_diagnostics():
    candidate = _candidate('005930', '삼성전자', 90, 20)
    run = _analysis_run(candidate)
    run['analysis_status'] = 'SUCCESS_FALLBACK'
    run['rule_candidate_verdict'] = {'action': 'HOLD', 'confidence': 0.51}
    run['verdict'].update({
        'analysis_status': 'SUCCESS_FALLBACK',
        'rule_candidate_verdict': {'action': 'HOLD', 'confidence': 0.51},
        'reasoning': 'fallback evidence is decisive',
        'opposing_scenario': 'volume confirmation fails',
    })

    result = workflow._analysis_result(candidate, run)

    assert result['analysis_status'] == 'SUCCESS_FALLBACK'
    assert result['rule_candidate_verdict'] == {'action': 'HOLD', 'confidence': 0.51}
    assert result['verdict']['analysis_status'] == 'SUCCESS_FALLBACK'
    assert result['verdict']['rule_candidate_verdict']['action'] == 'HOLD'
    assert result['verdict']['reasoning'] == 'fallback evidence is decisive'
    assert result['verdict']['opposing_scenario'] == 'volume confirmation fails'


def test_workflow_runs_multi_target_graphrag_and_selects_top3(tmp_path, monkeypatch):
    candidates = [
        _candidate('000001', 'Alpha One', 80, 20, 1),
        _candidate('000002', 'Beta Two', 76, 35, 2),
        _candidate('000003', 'Gamma Three', 90, 18, 3),
        _candidate('000004', 'Delta Four', 72, 40, 4),
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})

    def fake_create(candidate, agent_count, mode):
        if candidate['symbol'] == '000002':
            return _analysis_run(candidate, action='HOLD', confidence=55, graph_links=20, brain_score=50)
        if candidate['symbol'] == '000004':
            return _analysis_run(candidate, action='SELL', confidence=62, graph_links=10, brain_score=45)
        return _analysis_run(candidate, action='BUY', confidence=80 if candidate['symbol'] == '000003' else 72, graph_links=60, brain_score=70)

    monkeypatch.setattr(workflow, '_create_analysis_run', fake_create)

    result = workflow.start_workflow_from_scanner_events(
        # require_buy=False: this test exercises the ranking pipeline across mixed
        # verdicts (HOLD/SELL/BUY); the BUY-only filter is covered separately.
        {'limit': 20, 'agent_count': 10, 'top_n': 3, 'max_parallel': 2, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 4
    assert len(result['analysis_runs']) == 4
    assert len(result['top3']) == 3
    assert result['top3'][0]['symbol'] == '000003'
    assert all(item['verdict']['target'] for item in result['top3'])
    assert result['summary']['top_symbols'] == [item['symbol'] for item in result['top3']]
    assert result['summary']['quality']['recommendation'] == 'send'
    assert result['top3'][0]['score_formula_version'] == 'alpha_top3_v3_quality_weighted'


def test_workflow_quality_score_penalizes_weak_evidence_and_rewards_memory():
    strong = _candidate('000001', 'Strong Memory', 78, 25, 1)
    strong['analysis_profile']['evidence_quality'] = {'grade': 'strong'}
    strong['analysis_profile']['performance_memory'] = {'hit_rate_pct': 75, 'sample_size': 20}
    strong['analysis_profile']['profitability_scorecard']['goal_fit_score'] = 85

    weak = _candidate('000002', 'Weak Source', 78, 25, 2)
    weak['analysis_profile']['source_count'] = 1
    weak['analysis_profile']['evidence_quality'] = {'grade': 'weak'}
    weak['analysis_profile']['performance_memory'] = {'hit_rate_pct': 20, 'sample_size': 20}
    weak['analysis_profile']['profitability_scorecard']['hard_blockers'] = ['dilution_risk']
    weak['replay_context'] = {'lookahead_safe': False}

    strong_score = workflow._score_breakdown(strong, _analysis_run(strong, action='BUY', confidence=70))
    weak_score = workflow._score_breakdown(weak, _analysis_run(weak, action='BUY', confidence=70))

    assert strong_score['components']['evidence_quality'] == 5.0
    assert strong_score['components']['performance_memory'] > 0
    assert weak_score['components']['source_penalty'] == -6.0
    assert weak_score['components']['hard_blocker_penalty'] == -10.0
    assert strong_score['score'] > weak_score['score'] + 20


def test_workflow_quality_summary_holds_low_confidence_top3():
    weak = _candidate('000002', 'Weak Source', 55, 60, 2)
    weak['analysis_profile']['source_count'] = 1
    weak['analysis_profile']['evidence_quality'] = {'grade': 'weak'}
    item = {
        'candidate': weak,
        'symbol': weak['symbol'],
        'target': weak['display_name'],
        'status': 'completed',
        'analysis_status': 'SUCCESS_PRIMARY',
        'final_score': 42.0,
        'verdict': {'action': 'HOLD'},
    }

    summary = workflow._workflow_decision_summary([item], [item])

    assert summary['quality']['recommendation'] == 'hold'
    assert 'best_score_below_floor' in summary['quality']['reasons']
    ok, reason = workflow.should_send_workflow_top3({'top3': [item], 'summary': summary})
    assert ok is False
    assert 'best_score_below_floor' in reason


def test_workflow_attaches_forward_outcomes_without_lookahead(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    price_history = tmp_path / 'daily_prices.csv'
    price_history.write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000001,2026-05-07,Alpha One,9999,0,0,9999,9999,9999,10,now',
            '000001,2026-05-08,Alpha One,1010,0,0,1010,1010,1010,10,now',
            '000001,2026-05-11,Alpha One,1020,0,0,1020,1020,1020,10,now',
            '000001,2026-05-12,Alpha One,1030,0,0,1030,1030,1030,10,now',
            '000001,2026-05-13,Alpha One,1040,0,0,1040,1040,1040,10,now',
            '000001,2026-05-14,Alpha One,1100,0,0,1100,1100,1100,10,now',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(outcome_tracker, 'PRICE_HISTORY_PATH', str(price_history))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=80))

    result = workflow.start_workflow_from_scanner_events(
        {'limit': 20, 'top_n': 1, 'max_parallel': 1},
        async_mode=False,
    )

    outcome = result['top3'][0]['outcome']
    assert outcome['lookahead_safe'] is True
    assert outcome['entry_date'] == '2026-05-07'
    assert outcome['entry_price'] == 1000
    assert outcome['feature_snapshot']['alpha_score'] == 80
    assert outcome['feature_snapshot']['risk_score'] == 20
    assert outcome['feature_snapshot']['goal_fit_score'] == 78
    assert outcome['feature_snapshot']['goal_verdict'] == 'candidate_needs_confirmation'
    assert outcome['feature_snapshot']['goal_missing_confirmations'] == ['capital_flow']
    assert outcome['feature_snapshot']['signal_quality'] == 'high_conviction'
    assert outcome['feature_snapshot']['strategy_tags'] == ['momentum', 'trend_quality']
    assert outcome['feature_snapshot']['cio_action'] == 'BUY'
    assert outcome['horizons']['5']['exit_date'] == '2026-05-14'
    assert outcome['horizons']['5']['return_pct'] == 10.0
    assert outcome['forward_return_pct'] == 10.0
    assert outcome['hit'] is True
    assert result['summary']['outcome']['top3_hit_rate_pct'] == 100.0
    assert (tmp_path / 'workflows' / result['id'] / 'outcomes.json').is_file()


def test_outcome_tracker_prefers_full_analysis_runs_over_top3():
    workflow_record = {
        'analysis_runs': [
            {'symbol': '000001', 'target': 'Alpha One'},
            {'symbol': '000002', 'target': 'Beta Two'},
            {'symbol': '000003', 'target': 'Gamma Three'},
            {'symbol': '000004', 'target': 'Delta Four'},
            {'symbol': '000005', 'target': 'Epsilon Five'},
        ],
        'top3': [
            {'symbol': '000001', 'target': 'Alpha One'},
            {'symbol': '000002', 'target': 'Beta Two'},
            {'symbol': '000003', 'target': 'Gamma Three'},
        ],
    }

    results = outcome_tracker._workflow_results(workflow_record)

    assert [item['symbol'] for item in results] == ['000001', '000002', '000003', '000004', '000005']


def test_workflow_defaults_to_five_event_batch_and_top3(tmp_path, monkeypatch):
    candidates = [
        _candidate(f'00000{index}', f'Alpha {index}', 90 - index, 20 + index, index)
        for index in range(1, 7)
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates[:kwargs['max_events']]))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=70))

    result = workflow.start_workflow_from_scanner_events({'limit': 20}, async_mode=False)

    assert result['status'] == 'completed'
    assert result['event_count'] == 5
    assert len(result['analysis_runs']) == 5
    assert len(result['top3']) == 3
    assert result['filters']['batch_size'] == 5
    assert result['filters']['top_n'] == 3


def test_workflow_backfills_single_event_but_commits_only_trigger(tmp_path, monkeypatch):
    candidates = [
        _candidate(f'00000{index}', f'Alpha {index}', 90 - index, 20 + index, index)
        for index in range(1, 6)
    ]
    scanner_result = _scanner_result(candidates)
    scanner_result['events'] = scanner_result['events'][:1]
    scanner_result['new_event_count'] = 1

    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(
        workflow.alpha_scanner,
        'run_scanner_alert_check',
        lambda *args, **kwargs: scanner_result,
    )
    committed = []
    monkeypatch.setattr(
        workflow.alpha_scanner,
        'commit_scanner_alert_events',
        lambda result: committed.append(result) or {'sent_event_count': len(result['events'])},
    )
    monkeypatch.setattr(
        workflow,
        '_create_analysis_run',
        lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=70),
    )

    result = workflow.start_workflow_from_scanner_events(
        {'limit': 20, 'top_n': 3, 'max_events': 5},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 1
    assert result['analysis_candidate_count'] == 5
    assert result['backfill_count'] == 4
    assert len(result['analysis_runs']) == 5
    assert len(result['top3']) == 3
    assert [item['symbol'] for item in result['event_candidates']] == ['000001']
    assert committed
    assert [event['candidate']['symbol'] for event in committed[0]['events']] == ['000001']


def test_workflow_returns_no_new_events_without_creating_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result([]))

    result = workflow.start_workflow_from_scanner_events({'limit': 20}, async_mode=False)

    assert result['status'] == 'no_new_events'
    assert result['candidate_count'] == 0


def test_workflow_dry_run_previews_candidates(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))

    result = workflow.start_workflow_from_scanner_events({'limit': 20, 'dry_run': True}, async_mode=False)

    assert result['status'] == 'dry_run'
    assert result['candidate_count'] == 1
    assert result['candidates'][0]['display_name'] == 'Alpha One'


def test_force_workflow_accepts_watch_candidates_for_top3_pipeline(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 61, 35, 1, action='WATCH')]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'create_scanner_run', lambda payload: _scanner_result(candidates)['run'])
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='HOLD', confidence=65))

    result = workflow.start_workflow_from_scanner_events(
        # require_buy=False: this test verifies WATCH candidates enter the pipeline;
        # the BUY-only TOP3 filter is covered by test_mirofish_workflow_buy_filter.
        {'force': True, 'limit': 20, 'top_n': 1, 'max_parallel': 1, 'require_buy': False},
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 1
    assert result['top3'][0]['symbol'] == '000001'
    assert result['filters']['actions'] == ['BUY_CANDIDATE', 'WATCH']


def test_workflow_dual_kalman_gate_blocks_spike_and_scores_pass(tmp_path, monkeypatch):
    candidates = [
        _candidate('000001', 'Stable Alpha', 82, 20, 1),
        _candidate('000002', 'Noisy Spike', 90, 18, 2),
    ]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: {'committed': True})

    def fake_kalman(scanner_run, selected, **kwargs):
        return {
            'id': 'dkf_test',
            'status': 'completed',
            'profile': kwargs.get('profile'),
            'candidate_count': len(selected),
            'signal_count': len(selected),
            'lookahead_safe': True,
            'summary': {'gate_counts': {'pass': 1, 'watch': 0, 'block': 1}, 'avg_score_delta': -2.0},
            'links': {'signals': '/api/admin/mirofish/kalman/runs/dkf_test/signals'},
            'signals': [
                {
                    'symbol': '000001',
                    'gate': 'pass',
                    'score_delta': 3.5,
                    'shadow_alpha_score': 85.5,
                    'reason': 'stable',
                    'kalman': {
                        'signal_confidence': 0.72,
                        'latent_return_z': 1.2,
                        'innovation_z': 0.4,
                        'fair_value_gap_z': 0.7,
                        'volatility_state': 'normal',
                    },
                },
                {
                    'symbol': '000002',
                    'gate': 'block',
                    'score_delta': -7.5,
                    'shadow_alpha_score': 82.5,
                    'reason': 'spike',
                    'kalman': {'signal_confidence': 0.25},
                },
            ],
        }

    monkeypatch.setattr(workflow.dual_kalman, 'run_dual_kalman_signal_gate', fake_kalman)
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate, action='BUY', confidence=75))

    result = workflow.start_workflow_from_scanner_events(
        {
            'limit': 20,
            'top_n': 1,
            'max_parallel': 1,
            'quality_gate': 'dual_kalman',
        },
        async_mode=False,
    )

    assert result['status'] == 'completed'
    assert result['event_count'] == 1
    assert result['kalman_gate']['gate_counts']['block'] == 1
    assert result['analysis_runs'][0]['symbol'] == '000001'
    assert result['analysis_runs'][0]['candidate']['analysis_profile']['dual_kalman_gate']['gate'] == 'pass'
    assert result['analysis_runs'][0]['score_breakdown']['components']['dual_kalman'] == 3.5
    assert result['filters']['quality_gate'] == 'dual_kalman'


def test_force_workflow_blocks_stale_sources_by_default(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    scanner_run = _scanner_result(candidates)['run']
    scanner_run['freshness'] = {'status': 'stale'}
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'create_scanner_run', lambda payload: scanner_run)

    result = workflow.start_workflow_from_scanner_events(
        {'force': True, 'limit': 20, 'top_n': 1},
        async_mode=False,
    )

    assert result['status'] == 'blocked'
    assert result['blocked_reason'] == 'source_freshness:stale'


def test_workflow_monitor_check_can_run_sync_without_committing_event_state(tmp_path, monkeypatch):
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    scanner_kwargs = {}
    def fake_scanner(*args, **kwargs):
        scanner_kwargs.update(kwargs)
        return _scanner_result(candidates)
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', fake_scanner)
    commit_calls = []
    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', lambda result: commit_calls.append(result) or {'committed': True})
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate))

    result = workflow.run_workflow_monitor_check({
        'limit': 20,
        'sync': True,
        'commit_event_state': False,
        'top_n': 1,
        'max_parallel': 1,
    })

    assert result['status'] == 'completed'
    assert result['event_state_committed'] is False
    assert scanner_kwargs['block_on_stale'] is True
    assert commit_calls == []


def test_analysis_only_workflow_commit_never_mirrors_canonical_alert_state(tmp_path, monkeypatch):
    """Workflow completion without transport may update only its private dedupe state."""
    candidates = [_candidate('000001', 'Alpha One', 80, 20, 1)]
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    monkeypatch.setattr(workflow.alpha_scanner, 'run_scanner_alert_check', lambda *args, **kwargs: _scanner_result(candidates))
    monkeypatch.setattr(workflow, '_create_analysis_run', lambda candidate, agent_count, mode: _analysis_run(candidate))
    commits = []
    real_commit = workflow.commit_workflow_event_state

    def commit(record, **kwargs):
        commits.append(kwargs)
        return real_commit(record, **kwargs)

    monkeypatch.setattr(workflow, 'commit_workflow_event_state', commit)
    monkeypatch.setattr(
        workflow.alpha_scanner,
        'commit_scanner_alert_events',
        lambda result: {'sent_event_count': len(result.get('events') or [])},
    )

    result = workflow.run_workflow_monitor_check({
        'limit': 20,
        'sync': True,
        'commit_event_state': True,
        'top_n': 1,
        'max_parallel': 1,
    })

    assert result['status'] == 'completed'
    assert commits == [{'sync_dashboard': False}]
    assert result['dashboard_event_state_committed'] is False


def test_build_workflow_top3_telegram_message_names_exact_targets():
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    message = workflow.build_workflow_top3_telegram_message({
        'id': 'mcp_test123',
        'scanner_run_id': 'mfas_test',
        'scanner_freshness': {'status': 'fresh'},
        'event_count': 1,
        'completed_at': '2026-05-07T12:00:00+00:00',
        'analysis_runs': [{'symbol': '000001'}],
        'summary': {'top_count': 1},
        'top3': [{
            'candidate': candidate,
            'target': 'Alpha One',
            'symbol': '000001',
            'market': 'KOSPI',
            'final_score': 88.5,
            'verdict': {'action': 'BUY', 'confidence_pct': 75},
            'graph': {'links': 42},
            'brain': {'score': 63, 'regime': 'neutral'},
            'reason': 'Alpha One final_score=88.5',
            'outcome': {'status': 'pending', 'available_future_days': 0},
        }],
    })

    assert 'MiroFish MCP Top 3 자동 분석' in message
    assert 'Alpha One' in message
    assert '000001' in message
    assert '종합 점수' in message
    assert '데이터 신선도: <b>최신</b>' in message
    assert 'CIO 판정: <b>매수</b> 75%' in message
    assert '사후 검증: 검증 대기 (확보된 미래 거래일 0일)' in message
    assert 'Completed' not in message
    assert 'Forward check' not in message


def test_commit_workflow_event_state_mirrors_dashboard_alert_state(tmp_path, monkeypatch):
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    captured = []

    def fake_commit(result):
        captured.append(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    state = workflow.commit_workflow_event_state({
        'id': 'mcp_test123',
        'created_at': '2026-05-07T12:00:00+00:00',
        'scanner_run_id': 'mfas_test',
        'scanner_candidate_count': 1,
        'event_count': 1,
        'candidates': [candidate],
        'top3': [],
    })

    assert state == {'sent_event_count': 1}
    assert len(captured) == 2
    assert 'state_path' not in captured[0]
    assert captured[1]['state_path'].endswith('scanner_event_state.json')
    assert captured[0]['run']['id'] == 'mfas_test'
    assert captured[1]['run']['id'] == 'mfas_test'
    assert captured[0]['events'][0]['event_key'] == '000001:BUY_CANDIDATE:2026-05-07'
    assert captured[1]['events'][0]['event_key'] == '000001:BUY_CANDIDATE:2026-05-07'


def test_commit_workflow_event_state_preserves_canonical_claim_when_private_write_fails(
    tmp_path,
    monkeypatch,
):
    """A successful transport cannot become resendable when workflow-private state fails."""
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    canonical_commits = []

    def fake_commit(result):
        if 'state_path' in result:
            raise OSError('private workflow state unavailable')
        canonical_commits.append(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    with pytest.raises(OSError, match='private workflow state unavailable'):
        workflow.commit_workflow_event_state({
            'id': 'mcp_private_failure',
            'created_at': '2026-05-07T12:00:00+00:00',
            'scanner_run_id': 'mfas_private_failure',
            'scanner_candidate_count': 1,
            'event_count': 1,
            'candidates': [candidate],
            'top3': [],
        })

    assert len(canonical_commits) == 1
    assert canonical_commits[0]['events'][0]['event_key'] == '000001:BUY_CANDIDATE:2026-05-07'


def test_commit_workflow_event_state_keeps_watch_out_of_dashboard_alert_state(tmp_path, monkeypatch):
    buy = _candidate('000001', 'Alpha One', 80, 20, 1)
    watch = _candidate('000002', 'Watch Two', 74, 45, 2, action='WATCH')
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    captured = []

    def fake_commit(result):
        captured.append(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    workflow.commit_workflow_event_state({
        'id': 'mcp_test123',
        'created_at': '2026-05-07T12:00:00+00:00',
        'scanner_run_id': 'mfas_test',
        'scanner_candidate_count': 2,
        'event_count': 2,
        'candidates': [buy, watch],
        'top3': [],
    })

    assert len(captured) == 2
    assert [event['event_key'] for event in captured[0]['events']] == [
        '000001:BUY_CANDIDATE:2026-05-07',
    ]
    assert [event['event_key'] for event in captured[1]['events']] == [
        '000001:BUY_CANDIDATE:2026-05-07',
        '000002:WATCH:2026-05-07',
    ]


def test_commit_workflow_event_state_skips_dashboard_sync_for_watch_only(tmp_path, monkeypatch):
    watch = _candidate('000002', 'Watch Two', 74, 45, 1, action='WATCH')
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    captured = []

    def fake_commit(result):
        captured.append(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    workflow.commit_workflow_event_state({
        'id': 'mcp_test123',
        'created_at': '2026-05-07T12:00:00+00:00',
        'scanner_run_id': 'mfas_test',
        'scanner_candidate_count': 1,
        'event_count': 1,
        'candidates': [watch],
        'top3': [],
    })

    persisted = workflow.read_workflow('mcp_test123')

    assert len(captured) == 1
    assert captured[0]['state_path'].endswith('scanner_event_state.json')
    assert persisted['dashboard_event_state_committed'] is False
    assert persisted['dashboard_event_state_skipped_reason'] == 'no_buy_candidate_events'


def test_commit_workflow_event_state_can_skip_dashboard_sync(tmp_path, monkeypatch):
    candidate = _candidate('000001', 'Alpha One', 80, 20, 1)
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(tmp_path / 'workflows'))
    monkeypatch.setattr(workflow, 'WORKFLOW_STATE_ROOT', str(tmp_path / 'workflows' / '_state'))
    captured = []

    def fake_commit(result):
        captured.append(result)
        return {'sent_event_count': len(result['events'])}

    monkeypatch.setattr(workflow.alpha_scanner, 'commit_scanner_alert_events', fake_commit)

    workflow.commit_workflow_event_state(
        {
            'id': 'mcp_test123',
            'created_at': '2026-05-07T12:00:00+00:00',
            'scanner_run_id': 'mfas_test',
            'scanner_candidate_count': 1,
            'event_count': 1,
            'candidates': [candidate],
            'top3': [],
        },
        sync_dashboard=False,
    )

    assert len(captured) == 1
    assert captured[0]['state_path'].endswith('scanner_event_state.json')


def test_read_workflow_missing_id_does_not_create_directory(tmp_path, monkeypatch):
    workflows_root = tmp_path / 'workflows'
    missing_id = 'mcp_99999999999999_deadbeef'
    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(workflows_root))

    result = workflow.read_workflow(missing_id)

    assert result is None
    assert not (workflows_root / missing_id).exists()


def test_admin_mirofish_workflow_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/workflow/status' in rules
    assert '/api/admin/mirofish/workflow/scan-analyze' in rules
    assert '/api/admin/mirofish/workflows' in rules
    assert '/api/admin/mirofish/workflows/latest' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>/outcomes' in rules
    assert '/api/admin/mirofish/workflows/<workflow_id>/outcomes/refresh' in rules


def test_candidate_summary_promotes_rs_rating_from_evidence():
    candidate = _candidate('005930', '삼성전자', 82, 30)
    candidate['evidence'] = [
        {'source': 'daily_prices.csv', 'field': 'price_momentum', 'score': 10, 'value': 3.2},
        {'source': 'alpha_rs_ratings.json', 'field': 'relative_strength', 'score': 4.0, 'value': 95},
    ]

    summary = workflow._candidate_summary(candidate)

    assert summary['rs_rating'] == 95
    assert 'evidence' not in summary  # 용량 절약 정책 유지


def test_candidate_summary_rs_rating_none_when_absent():
    candidate = _candidate('000660', 'SK하이닉스', 75, 40)

    summary = workflow._candidate_summary(candidate)

    assert summary['rs_rating'] is None


def test_extract_rs_rating_prefers_direct_key_over_evidence():
    candidate = {
        'rs_rating': 88,
        'evidence': [{'field': 'relative_strength', 'value': 12}],
    }

    assert workflow._extract_rs_rating(candidate) == 88
