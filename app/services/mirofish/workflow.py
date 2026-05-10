"""MiroFish Control Plane workflow automation.

The workflow connects alpha scanner events to multiple GraphRAG analysis runs
and synthesizes a final Top 3 ranking for the admin console.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.mirofish import alpha_scanner, outcome_tracker, store
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
WORKFLOWS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'workflows')
WORKFLOW_STATE_ROOT = os.path.join(WORKFLOWS_ROOT, '_state')

DEFAULT_LIMIT = 20
DEFAULT_MIN_ALPHA = 50.0
DEFAULT_MAX_RISK = 65.0
DEFAULT_MAX_EVENTS = 5
DEFAULT_AGENT_COUNT = 10
DEFAULT_TOP_N = 3
DEFAULT_MAX_PARALLEL = 3
DEFAULT_ACTIONS = ('BUY_CANDIDATE', 'WATCH')


def start_workflow_from_scanner_events(
    payload: dict[str, Any] | None = None,
    *,
    async_mode: bool = True,
    commit_event_state: bool = True,
) -> dict[str, Any]:
    """Detect new scanner events and start a multi-target GraphRAG workflow."""
    payload = payload or {}
    scanner_payload = _scanner_payload(payload)
    force = _bool(payload.get('force'), False)
    dry_run = _bool(payload.get('dry_run'), False)
    agent_count = _int(payload.get('agent_count'), DEFAULT_AGENT_COUNT, 1, store.MAX_AGENT_COUNT)
    top_n = _int(payload.get('top_n'), DEFAULT_TOP_N, 1, 10)
    max_parallel = _int(payload.get('max_parallel'), DEFAULT_MAX_PARALLEL, 1, 8)
    mode = _mode(payload.get('mode'))
    max_events = _int(payload.get('max_events'), DEFAULT_MAX_EVENTS, 1, 20)
    min_alpha = _float(payload.get('min_alpha'), DEFAULT_MIN_ALPHA)
    max_risk = _float(payload.get('max_risk'), DEFAULT_MAX_RISK)
    actions = _actions(payload.get('actions'))
    allow_stale_sources = _bool(payload.get('allow_stale_sources', payload.get('allow_stale')), False)

    if force:
        scanner_run = alpha_scanner.create_scanner_run(scanner_payload)
        freshness_status = str(((scanner_run.get('freshness') or {}).get('status') or 'unknown')).lower()
        if not allow_stale_sources and freshness_status in alpha_scanner.ALERT_BLOCKING_FRESHNESS:
            return {
                'ok': False,
                'status': 'blocked',
                'scanner_run_id': scanner_run.get('id'),
                'candidate_count': 0,
                'alert_blocked': True,
                'blocked_reason': f'source_freshness:{freshness_status}',
                'scanner_freshness': scanner_run.get('freshness'),
            }
        candidates = _eligible_candidates(
            scanner_run,
            min_alpha=min_alpha,
            max_risk=max_risk,
            actions=actions,
            max_count=max_events,
        )
        scanner_result = {
            'run': scanner_run,
            'events': [_candidate_event(candidate) for candidate in candidates],
            'new_event_count': len(candidates),
            'alert_blocked': False,
            'blocked_reason': None,
            'state_committed': False,
        }
    else:
        scanner_result = alpha_scanner.run_scanner_alert_check(
            scanner_payload,
            state_path=_event_state_path(),
            min_alpha=min_alpha,
            max_risk=max_risk,
            actions=actions,
            max_events=max_events,
            commit_state=False,
            block_on_stale=not allow_stale_sources,
        )
        candidates = [
            event.get('candidate')
            for event in scanner_result.get('events') or []
            if isinstance(event, dict) and isinstance(event.get('candidate'), dict)
        ]

    if dry_run:
        return {
            'ok': True,
            'status': 'dry_run',
            'scanner_run_id': (scanner_result.get('run') or {}).get('id'),
            'candidate_count': len(candidates),
            'candidates': [_candidate_summary(candidate) for candidate in candidates],
            'alert_blocked': bool(scanner_result.get('alert_blocked')),
            'blocked_reason': scanner_result.get('blocked_reason'),
        }

    if scanner_result.get('alert_blocked'):
        return {
            'ok': False,
            'status': 'blocked',
            'scanner_run_id': (scanner_result.get('run') or {}).get('id'),
            'candidate_count': 0,
            'alert_blocked': True,
            'blocked_reason': scanner_result.get('blocked_reason'),
        }

    if not candidates:
        return {
            'ok': True,
            'status': 'no_new_events',
            'scanner_run_id': (scanner_result.get('run') or {}).get('id'),
            'candidate_count': 0,
            'event_state_committed': False,
        }

    workflow = _create_workflow_record(
        scanner_result=scanner_result,
        candidates=candidates,
        agent_count=agent_count,
        top_n=top_n,
        max_parallel=max_parallel,
        mode=mode,
        force=force,
        filters={
            'min_alpha': min_alpha,
            'max_risk': max_risk,
            'actions': list(actions),
            'batch_size': max_events,
            'top_n': top_n,
            'allow_stale_sources': allow_stale_sources,
        },
    )
    _write_workflow(workflow)

    if commit_event_state and not force:
        alpha_scanner.commit_scanner_alert_events(scanner_result)
        workflow['event_state_committed'] = True
        _write_workflow(workflow)

    if async_mode:
        thread = threading.Thread(
            target=_complete_workflow_background,
            args=(workflow['id'], candidates, agent_count, mode, max_parallel, top_n),
            name=f"mirofish-mcp-{workflow['id'][:24]}",
            daemon=True,
        )
        thread.start()
        return _workflow_summary(workflow)

    return _complete_workflow(workflow['id'], candidates, agent_count, mode, max_parallel, top_n)


def run_workflow_monitor_check(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Scheduler entrypoint: check events and start the workflow."""
    payload = payload or {}
    sync = _bool(payload.get('sync'), False)
    commit_event_state = _bool(payload.get('commit_event_state'), True)
    return start_workflow_from_scanner_events(
        payload,
        async_mode=not sync,
        commit_event_state=commit_event_state,
    )


def build_share_payload(workflow: dict[str, Any], rank: int | None = None) -> dict[str, Any]:
    """카카오톡 공유용 payload — Kakao SDK 'feed' 템플릿에 맞춘 형식.

    Args:
        workflow: workflow dict (read_workflow 결과)
        rank: 1|2|3 — 단일 종목 공유 시. None이면 TOP 3 전체 요약.

    Returns:
        {
            'title': str,
            'description': str,
            'image_url': str,
            'link_url': str,
            'rank': int|None,
            'top_items': [{'rank', 'symbol', 'name', 'score', 'action', 'confidence_pct', 'outcome_status'}],
            'workflow_id': str,
            'completed_at': str,
        }
    """
    top3 = [item for item in (workflow.get('top3') or []) if isinstance(item, dict)]
    workflow_id = str(workflow.get('id') or '')
    completed_at = str(workflow.get('completed_at') or '')

    # 표준 share base URL — production frontend
    base_url = 'https://bit-man.net/admin/endpoints'
    fallback_image = 'https://bit-man.net/og/marketflow-mcp-share.png'

    # TOP 3 정규화 (UI 카드와 동일 구조)
    top_items = []
    for index, item in enumerate(top3[:3], start=1):
        candidate = item.get('candidate') or {}
        verdict = item.get('verdict') or {}
        outcome = item.get('outcome') or {}
        top_items.append({
            'rank': index,
            'symbol': item.get('symbol') or candidate.get('symbol') or '',
            'name': item.get('target') or candidate.get('display_name') or candidate.get('name') or '',
            'market': item.get('market') or candidate.get('market') or 'KR',
            'score': round(float(item.get('final_score') or 0), 1),
            'action': verdict.get('action') or 'HOLD',
            'confidence_pct': int(verdict.get('confidence_pct') or 0),
            'outcome_status': outcome.get('status') or 'pending',
            'outcome_hit': outcome.get('hit'),
            'outcome_forward_return_pct': outcome.get('forward_return_pct'),
            'replay_safe_after': outcome.get('entry_date') or outcome.get('replay_safe_after'),
        })

    if not top_items:
        return {
            'title': 'MarketFlow MCP TOP 3',
            'description': 'TOP 3 결과가 아직 준비되지 않았습니다.',
            'image_url': fallback_image,
            'link_url': base_url,
            'rank': None,
            'top_items': [],
            'workflow_id': workflow_id,
            'completed_at': completed_at,
        }

    # 단일 종목 공유 모드
    if rank is not None:
        if rank < 1 or rank > len(top_items):
            raise ValueError(f'rank {rank} out of range (1-{len(top_items)})')
        target = top_items[rank - 1]
        title = f"MarketFlow TOP {rank} — {target['name']}"
        verdict_label = _share_verdict_label(target['action'])
        description = (
            f"{target['symbol']} · score {target['score']:.0f} · "
            f"{verdict_label} {target['confidence_pct']}%"
        )
        if target.get('replay_safe_after'):
            description += f" · replay-safe {target['replay_safe_after']}"
        return {
            'title': title,
            'description': description,
            'image_url': fallback_image,
            'link_url': f"{base_url}?workflow={workflow_id}&top={rank}",
            'rank': rank,
            'top_items': top_items,
            'workflow_id': workflow_id,
            'completed_at': completed_at,
        }

    # TOP 3 전체 공유 모드
    rank_lines = ' / '.join(
        f"#{item['rank']} {item['name']}({item['symbol']}) {_share_verdict_label(item['action'])} {item['confidence_pct']}%"
        for item in top_items
    )
    title = f"MarketFlow MCP TOP 3 — AI 자동 분석"
    description = rank_lines if len(rank_lines) <= 200 else rank_lines[:197] + '…'
    return {
        'title': title,
        'description': description,
        'image_url': fallback_image,
        'link_url': f"{base_url}?workflow={workflow_id}",
        'rank': None,
        'top_items': top_items,
        'workflow_id': workflow_id,
        'completed_at': completed_at,
    }


def _share_verdict_label(action: str) -> str:
    a = (action or '').upper()
    if a == 'BUY':
        return '매수'
    if a == 'SELL':
        return '매도'
    return '관망'


def build_workflow_top3_telegram_message(workflow: dict[str, Any]) -> str:
    """Build a Korean Telegram summary for the completed scanner -> GraphRAG Top 3."""
    top3 = [item for item in (workflow.get('top3') or []) if isinstance(item, dict)]
    analysis_runs = workflow.get('analysis_runs') or []
    summary = workflow.get('summary') or {}
    freshness = workflow.get('scanner_freshness') or {}
    freshness_status = freshness.get('status') if isinstance(freshness, dict) else ''
    lines = [
        '<b>MiroFish MCP Top 3 자동 분석</b>',
        '신규 스캐너 이벤트를 다중 종목 GraphRAG 분석으로 처리했습니다.',
        f"워크플로우: <code>{_escape(workflow.get('id'))}</code>",
        f"스캐너 실행: <code>{_escape(workflow.get('scanner_run_id'))}</code>",
        (
        f"이벤트: <b>{_escape(workflow.get('event_count') or 0)}</b> / "
        f"분석 완료: <b>{_escape(len(analysis_runs))}</b> / "
        f"선별: <b>Top {_escape(summary.get('top_count') or len(top3))}</b>"
        ),
        f"데이터 신선도: <b>{_escape(_korean_freshness(freshness_status))}</b>",
    ]
    filters = workflow.get('filters') or {}
    if filters.get('batch_size') or filters.get('top_n'):
        lines.append(
            f"자동화: 스캔 {_escape(filters.get('batch_size') or workflow.get('event_count') or 0)}종 "
            f"-> Top {_escape(filters.get('top_n') or summary.get('top_count') or len(top3))} 선별"
        )
    if freshness_status and freshness_status != 'fresh':
        lines.append('데이터 경고: 캐시 또는 지연 데이터가 포함되었습니다. 실행 전 신선도를 다시 확인하세요.')
    if workflow.get('completed_at'):
        lines.append(f"완료 시각: {_escape(_format_kst(workflow.get('completed_at')))}")
    if not top3:
        lines.append('')
        lines.append('Top 3 결과가 생성되지 않았습니다. 실행 전 워크플로우 산출물을 확인하세요.')
        return '\n'.join(lines)

    for index, item in enumerate(top3, start=1):
        candidate = item.get('candidate') or {}
        verdict = item.get('verdict') or {}
        graph = item.get('graph') or {}
        brain = item.get('brain') or {}
        price = candidate.get('price') or {}
        name = item.get('target') or candidate.get('display_name') or candidate.get('name') or item.get('symbol')
        symbol = item.get('symbol') or candidate.get('symbol')
        market = item.get('market') or candidate.get('market')
        action = verdict.get('action') or 'HOLD'
        confidence = verdict.get('confidence_pct')
        lines.extend([
            '',
            f"#{index} <b>{_escape(name)}</b> (<code>{_escape(symbol)}</code> {_escape(market)})",
            (
                f"종합 점수: <b>{_format_metric(item.get('final_score'), decimals=2)}</b> / "
                f"CIO 판정: <b>{_escape(_korean_action(action))}</b> "
                f"{_format_metric(confidence, suffix='%', decimals=0)}"
            ),
            (
                f"스캐너 알파/리스크: "
                f"<b>{_format_metric(candidate.get('alpha_score'), decimals=0)}</b> / "
                f"<b>{_format_metric(candidate.get('risk_score'), decimals=0)}</b>"
            ),
            (
                f"GraphRAG 연결: {_format_metric(graph.get('links'), decimals=0)} / "
                f"Brain: {_format_metric(brain.get('score'), decimals=0)} "
                f"{_escape(_korean_regime(brain.get('regime')))}"
            ),
            (
                f"가격: {_format_metric(price.get('current_price'), decimals=0)} "
                f"{_escape(price.get('currency') or 'KRW')} / "
                f"기준일: {_escape(price.get('date') or '')}"
            ),
        ])
        reason = _korean_reason(item, candidate, verdict)
        if reason:
            lines.append(f"핵심 근거: {_escape(reason)}")
        outcome = item.get('outcome') or {}
        if outcome:
            if outcome.get('forward_return_pct') is not None:
                hit_label = '성공' if outcome.get('hit') is True else '실패'
                lines.append(
                    f"사후 검증: T{_escape(outcome.get('primary_horizon_days') or '?')} "
                    f"<b>{_format_signed_metric(outcome.get('forward_return_pct'), suffix='%')}</b> "
                    f"/ {_escape(hit_label)} / 룩어헤드 방지"
                )
            else:
                available_days = outcome.get('available_future_days')
                if available_days is None:
                    available_days = 0
                lines.append(
                    f"사후 검증: {_escape(_korean_outcome_status(outcome.get('status')))} "
                    f"(확보된 미래 거래일 {_escape(available_days)}일)"
                )
    return '\n'.join(lines)


def commit_workflow_event_state(workflow: dict[str, Any] | str) -> dict[str, Any]:
    """Commit scanner-event state after a workflow result is successfully handled."""
    record = read_workflow(workflow) if isinstance(workflow, str) else workflow
    if not isinstance(record, dict):
        raise ValueError('workflow not found')
    candidates = [
        candidate
        for candidate in (record.get('candidates') or [])
        if isinstance(candidate, dict)
    ]
    result = {
        'state_path': _event_state_path(),
        'run': {
            'id': record.get('scanner_run_id'),
            'generated_at': record.get('created_at'),
            'candidate_count': record.get('scanner_candidate_count') or record.get('event_count'),
        },
        'events': [_candidate_event(candidate) for candidate in candidates],
    }
    state = alpha_scanner.commit_scanner_alert_events(result)
    record['event_state_committed'] = True
    record['event_state_committed_at'] = datetime.now(timezone.utc).isoformat()
    record['event_state'] = state
    _write_workflow(record)
    return state


def read_workflow(workflow_id: str) -> dict[str, Any] | None:
    safe_id = _safe_workflow_id(workflow_id)
    path = os.path.join(_workflow_dir(safe_id), 'workflow.json')
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def read_latest_workflow() -> dict[str, Any] | None:
    workflows = list_workflows(limit=1)
    if not workflows:
        return None
    return read_workflow(workflows[0]['id'])


def list_workflows(limit: int = 20) -> list[dict[str, Any]]:
    if not os.path.isdir(WORKFLOWS_ROOT):
        return []
    records: list[dict[str, Any]] = []
    for name in os.listdir(WORKFLOWS_ROOT):
        if name == '_state':
            continue
        try:
            workflow = read_workflow(name)
        except ValueError:
            continue
        if workflow:
            records.append(_workflow_summary(workflow))
    records.sort(key=lambda item: item.get('created_at', ''), reverse=True)
    return records[:max(1, min(int(limit or 20), 100))]


def get_workflow_status() -> dict[str, Any]:
    latest = read_latest_workflow()
    return {
        'service': 'mirofish-control-plane',
        'ready': True,
        'mode': 'scanner_event_to_graphrag_top3',
        'storage': os.path.relpath(WORKFLOWS_ROOT, REPO_ROOT).replace('\\', '/'),
        'latest_workflow': _workflow_summary(latest) if latest else None,
        'state': _read_json(_event_state_path()) if os.path.isfile(_event_state_path()) else {},
        'checked_at': datetime.now(timezone.utc).isoformat(),
    }


def _complete_workflow_background(
    workflow_id: str,
    candidates: list[dict[str, Any]],
    agent_count: int,
    mode: str,
    max_parallel: int,
    top_n: int,
) -> None:
    try:
        _complete_workflow(workflow_id, candidates, agent_count, mode, max_parallel, top_n)
    except Exception as exc:
        workflow = read_workflow(workflow_id) or {'id': workflow_id}
        workflow.update({
            'status': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
            'completed_at': datetime.now(timezone.utc).isoformat(),
        })
        _write_workflow(workflow)


def _complete_workflow(
    workflow_id: str,
    candidates: list[dict[str, Any]],
    agent_count: int,
    mode: str,
    max_parallel: int,
    top_n: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    workflow = read_workflow(workflow_id)
    if not workflow:
        raise ValueError('workflow not found')
    workflow['status'] = 'running'
    workflow['started_at'] = workflow.get('started_at') or datetime.now(timezone.utc).isoformat()
    workflow['progress'] = {
        'phase': 'graphrag_batch',
        'completed': 0,
        'total': len(candidates),
        'percent': 5,
    }
    _write_workflow(workflow)

    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_parallel) as executor:
        future_map = {
            executor.submit(_create_analysis_run, candidate, agent_count, mode): candidate
            for candidate in candidates
        }
        for future in concurrent.futures.as_completed(future_map):
            candidate = future_map[future]
            try:
                run = future.result()
                item = _analysis_result(candidate, run)
            except Exception as exc:
                item = {
                    'candidate': _candidate_summary(candidate),
                    'status': 'failed',
                    'error': f'{type(exc).__name__}: {exc}',
                    'final_score': -999.0,
                }
            results.append(item)
            workflow['analysis_runs'] = sorted(results, key=lambda item: item.get('final_score', -999), reverse=True)
            workflow['progress'] = {
                'phase': 'graphrag_batch',
                'completed': len(results),
                'total': len(candidates),
                'percent': min(95, int((len(results) / max(1, len(candidates))) * 90) + 5),
            }
            _write_workflow(workflow)

    ranked = sorted(results, key=lambda item: item.get('final_score', -999), reverse=True)
    top3 = ranked[:top_n]
    summary = _workflow_decision_summary(top3, ranked)
    outcome_summary: dict[str, Any] = {}
    outcome_status = 'not_evaluated'
    try:
        outcome_payload = outcome_tracker.refresh_workflow_outcomes(workflow_id, workflow={
            **workflow,
            'analysis_runs': ranked,
            'top3': top3,
        }, workflows_root=WORKFLOWS_ROOT)
        ranked = outcome_tracker.attach_outcomes_to_results(ranked, outcome_payload)
        top3 = outcome_tracker.attach_outcomes_to_results(top3, outcome_payload)
        outcome_summary = outcome_tracker.workflow_outcome_summary(outcome_payload)
        outcome_status = str(outcome_payload.get('status') or 'unknown')
        summary = _workflow_decision_summary(top3, ranked)
        summary['outcome'] = outcome_summary
    except Exception as exc:
        outcome_status = 'failed'
        outcome_summary = {
            'status': 'failed',
            'error': f'{type(exc).__name__}: {exc}',
            'lookahead_safe': True,
        }
        summary['outcome'] = outcome_summary
    workflow.update({
        'status': 'completed',
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'elapsed_ms': int((time.perf_counter() - started) * 1000),
        'analysis_runs': ranked,
        'top3': top3,
        'outcome_status': outcome_status,
        'outcome_summary': outcome_summary,
        'progress': {
            'phase': 'completed',
            'completed': len(results),
            'total': len(candidates),
            'percent': 100,
        },
        'summary': summary,
    })
    _write_workflow(workflow)
    return workflow


def _create_analysis_run(candidate: dict[str, Any], agent_count: int, mode: str) -> dict[str, Any]:
    target = candidate.get('display_name') or candidate.get('name') or candidate.get('symbol')
    if candidate.get('symbol') and target != candidate.get('symbol'):
        target = f"{target} {candidate.get('symbol')}"
    return store.create_run({
        'target': target,
        'agent_count': agent_count,
        'mode': mode,
        'async': False,
    })


def _analysis_result(candidate: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    verdict = run.get('verdict') or {}
    pipeline = run.get('pipeline') or {}
    brain = run.get('brain') or run.get('brain_summary') or {}
    final_score = _final_score(candidate, run)
    return {
        'candidate': _candidate_summary(candidate),
        'status': run.get('status', 'completed'),
        'run_id': run.get('id'),
        'target': run.get('display_name') or run.get('target'),
        'symbol': run.get('symbol') or candidate.get('symbol'),
        'market': run.get('market') or candidate.get('market'),
        'verdict': {
            'action': verdict.get('action') or verdict.get('label'),
            'confidence_pct': verdict.get('confidence_pct'),
            'bullish': verdict.get('bullish'),
            'neutral': verdict.get('neutral'),
            'bearish': verdict.get('bearish'),
            'target': verdict.get('target') or run.get('display_name') or candidate.get('display_name'),
            'summary': verdict.get('summary'),
        },
        'graph': {
            'links': pipeline.get('graph_links'),
            'similar_events': pipeline.get('similar_events'),
            'method': pipeline.get('graph_method'),
        },
        'brain': {
            'score': brain.get('score') or brain.get('alignment_score'),
            'regime': brain.get('regime'),
            'crisis': brain.get('crisis_level') or brain.get('crisis'),
        },
        'final_score': final_score,
        'reason': _ranking_reason(candidate, run, final_score),
        'artifacts': run.get('artifacts') or {},
    }


def _final_score(candidate: dict[str, Any], run: dict[str, Any]) -> float:
    verdict = run.get('verdict') or {}
    pipeline = run.get('pipeline') or {}
    brain = run.get('brain') or run.get('brain_summary') or {}
    action = str(verdict.get('action') or verdict.get('label') or 'HOLD').upper()
    action_bonus = {'BUY': 20.0, 'HOLD': 4.0, 'SELL': -30.0}.get(action, 0.0)
    confidence_pct = _number(verdict.get('confidence_pct'))
    if confidence_pct <= 0:
        confidence_pct = _number(verdict.get('confidence')) * 100
    alpha = _number(candidate.get('alpha_score'))
    risk = _number(candidate.get('risk_score'))
    graph_links = min(_number(pipeline.get('graph_links')), 120.0)
    brain_score = _number(brain.get('score') or brain.get('alignment_score'))
    source_count = _number((candidate.get('analysis_profile') or {}).get('source_count'))
    quality_bonus = {
        'high_conviction': 6.0,
        'actionable': 3.0,
        'watch': 1.0,
    }.get(str(candidate.get('signal_quality') or '').lower(), 0.0)
    score = (
        alpha * 0.46
        - risk * 0.32
        + confidence_pct * 0.24
        + action_bonus
        + brain_score * 0.08
        + graph_links * 0.05
        + source_count * 1.6
        + quality_bonus
    )
    return round(score, 2)


def _ranking_reason(candidate: dict[str, Any], run: dict[str, Any], final_score: float) -> str:
    verdict = run.get('verdict') or {}
    profile = candidate.get('analysis_profile') or {}
    action = verdict.get('action') or verdict.get('label') or 'HOLD'
    return (
        f"{candidate.get('display_name') or candidate.get('symbol')} final_score={final_score}; "
        f"scanner alpha={candidate.get('alpha_score')} risk={candidate.get('risk_score')}; "
        f"CIO={action} {verdict.get('confidence_pct')}%; "
        f"T20={profile.get('trend_20d_pct')} volume={profile.get('volume_ratio')}"
    )


def _workflow_decision_summary(top3: list[dict[str, Any]], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    buy_count = sum(1 for item in ranked if (item.get('verdict') or {}).get('action') == 'BUY')
    return {
        'title': 'MiroFish MCP Top 3',
        'top_count': len(top3),
        'analyzed_count': len(ranked),
        'buy_count': buy_count,
        'top_symbols': [item.get('symbol') for item in top3],
        'top_names': [item.get('target') for item in top3],
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


def _create_workflow_record(
    *,
    scanner_result: dict[str, Any],
    candidates: list[dict[str, Any]],
    agent_count: int,
    top_n: int,
    max_parallel: int,
    mode: str,
    force: bool,
    filters: dict[str, Any],
) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    scanner_run = scanner_result.get('run') or {}
    workflow_id = _workflow_id(created_at, scanner_run.get('id'), candidates)
    return {
        'id': workflow_id,
        'status': 'queued',
        'type': 'scanner_event_graphrag_batch_top3',
        'label': 'MiroFish Control Plane',
        'created_at': created_at,
        'scanner_run_id': scanner_run.get('id'),
        'scanner_freshness': scanner_run.get('freshness'),
        'scanner_candidate_count': scanner_run.get('candidate_count'),
        'force': bool(force),
        'agent_count': agent_count,
        'mode': mode,
        'top_n': top_n,
        'max_parallel': max_parallel,
        'filters': filters,
        'event_count': len(candidates),
        'candidates': [_candidate_summary(candidate) for candidate in candidates],
        'analysis_runs': [],
        'top3': [],
        'event_state_committed': False,
        'progress': {
            'phase': 'queued',
            'completed': 0,
            'total': len(candidates),
            'percent': 0,
        },
        'links': {
            'self': f'/api/admin/mirofish/workflows/{workflow_id}',
            'scanner_run': f"/api/admin/mirofish/scanner/runs/{scanner_run.get('id')}",
        },
    }


def _eligible_candidates(
    scanner_run: dict[str, Any],
    *,
    min_alpha: float,
    max_risk: float,
    actions: tuple[str, ...],
    max_count: int,
) -> list[dict[str, Any]]:
    candidates = []
    action_set = {str(action).upper() for action in actions}
    for candidate in scanner_run.get('candidates') or []:
        if _number(candidate.get('alpha_score')) < min_alpha:
            continue
        if _number(candidate.get('risk_score')) > max_risk:
            continue
        if str(candidate.get('action') or '').upper() not in action_set:
            continue
        candidates.append(candidate)
    return candidates[:max_count]


def _candidate_event(candidate: dict[str, Any]) -> dict[str, Any]:
    event_key = f"{candidate.get('symbol')}:{candidate.get('action')}:{(candidate.get('price') or {}).get('date')}"
    return {
        'event_key': event_key,
        'key': event_key,
        'candidate': candidate,
    }


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        'rank': candidate.get('rank'),
        'symbol': candidate.get('symbol'),
        'name': candidate.get('name') or candidate.get('display_name'),
        'display_name': candidate.get('display_name') or candidate.get('name') or candidate.get('symbol'),
        'market': candidate.get('market'),
        'action': candidate.get('action'),
        'alpha_score': candidate.get('alpha_score'),
        'risk_score': candidate.get('risk_score'),
        'ranking_score': candidate.get('ranking_score'),
        'signal_quality': candidate.get('signal_quality'),
        'strategy_tags': candidate.get('strategy_tags') or [],
        'analysis_profile': candidate.get('analysis_profile') or {},
        'entry_plan': candidate.get('entry_plan') or {},
        'replay_context': candidate.get('replay_context') or {},
        'price': candidate.get('price') or {},
    }


def _scanner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    scanner_payload = {
        key: payload[key]
        for key in ('symbols', 'market', 'horizon', 'strategy', 'risk_profile')
        if key in payload
    }
    scanner_payload['limit'] = _int(payload.get('limit'), DEFAULT_LIMIT, 1, 100)
    return scanner_payload


def _workflow_summary(workflow: dict[str, Any] | None) -> dict[str, Any] | None:
    if not workflow:
        return None
    return {
        'id': workflow.get('id'),
        'status': workflow.get('status'),
        'type': workflow.get('type'),
        'created_at': workflow.get('created_at'),
        'completed_at': workflow.get('completed_at'),
        'scanner_run_id': workflow.get('scanner_run_id'),
        'scanner_freshness': workflow.get('scanner_freshness'),
        'scanner_candidate_count': workflow.get('scanner_candidate_count'),
        'event_count': workflow.get('event_count'),
        'analyzed_count': len(workflow.get('analysis_runs') or []),
        'top3': workflow.get('top3') or [],
        'summary': workflow.get('summary') or {},
        'progress': workflow.get('progress') or {},
        'filters': workflow.get('filters') or {},
        'links': workflow.get('links') or {},
    }


def _write_workflow(workflow: dict[str, Any]) -> None:
    write_json_atomic(os.path.join(_workflow_dir(workflow['id']), 'workflow.json'), workflow, sort_keys=False)


def _workflow_dir(workflow_id: str) -> str:
    safe_id = _safe_workflow_id(workflow_id)
    root = os.path.abspath(WORKFLOWS_ROOT)
    path = os.path.abspath(os.path.join(root, safe_id))
    if not path.startswith(root):
        raise ValueError('invalid workflow_id')
    os.makedirs(path, exist_ok=True)
    return path


def _event_state_path() -> str:
    os.makedirs(WORKFLOW_STATE_ROOT, exist_ok=True)
    return os.path.join(WORKFLOW_STATE_ROOT, 'scanner_event_state.json')


def _workflow_id(created_at: str, scanner_run_id: Any, candidates: list[dict[str, Any]]) -> str:
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    digest_src = '|'.join([
        str(created_at),
        str(scanner_run_id or ''),
        ','.join(str(candidate.get('symbol') or '') for candidate in candidates),
        str(os.getpid()),
    ])
    digest = hashlib.sha256(digest_src.encode('utf-8')).hexdigest()[:10]
    return f'mcp_{stamp}_{digest}'


def _safe_workflow_id(workflow_id: str) -> str:
    safe_id = str(workflow_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,80}', safe_id):
        raise ValueError('invalid workflow_id')
    return safe_id


def _read_json(path: str) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('json root must be object')
    return data


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _number(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _format_kst(value: Any) -> str:
    if not value:
        return ''
    text = str(value)
    try:
        normalized = text.replace('Z', '+00:00')
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        return kst.strftime('%Y-%m-%d %H:%M KST')
    except Exception:
        return text


def _korean_freshness(status: Any) -> str:
    mapping = {
        'fresh': '최신',
        'stale': '지연',
        'unknown': '확인 필요',
        'missing': '데이터 없음',
    }
    key = str(status or 'unknown').strip().lower()
    return mapping.get(key, key or '확인 필요')


def _korean_action(action: Any) -> str:
    mapping = {
        'BUY': '매수',
        'SELL': '매도',
        'HOLD': '보유',
        'WATCH': '관망',
        'BUY_CANDIDATE': '매수 후보',
    }
    key = str(action or 'HOLD').strip().upper()
    return mapping.get(key, key)


def _korean_regime(regime: Any) -> str:
    mapping = {
        'constructive_accumulation': '건설적 매집',
        'neutral': '중립',
        'risk_off': '위험 회피',
        'risk_on': '위험 선호',
        'distribution': '분산/매도 우위',
    }
    key = str(regime or '').strip().lower()
    return mapping.get(key, str(regime or ''))


def _korean_outcome_status(status: Any) -> str:
    mapping = {
        'pending': '검증 대기',
        'partial': '부분 검증',
        'evaluated': '검증 완료',
        'missing_entry': '진입가 없음',
        'not_evaluated': '미검증',
        'failed': '검증 실패',
    }
    key = str(status or 'pending').strip().lower()
    return mapping.get(key, key or '검증 대기')


def _korean_reason(
    item: dict[str, Any],
    candidate: dict[str, Any],
    verdict: dict[str, Any],
) -> str:
    profile = candidate.get('analysis_profile') or {}
    parts = [
        f"최종점수 {_format_metric(item.get('final_score'), decimals=2)}",
        f"알파 {_format_metric(candidate.get('alpha_score'), decimals=0)}",
        f"리스크 {_format_metric(candidate.get('risk_score'), decimals=0)}",
        (
            f"CIO {_korean_action(verdict.get('action') or verdict.get('label'))} "
            f"{_format_metric(verdict.get('confidence_pct'), suffix='%', decimals=0)}"
        ),
    ]
    if profile.get('trend_20d_pct') is not None:
        parts.append(f"T20 {_format_signed_metric(profile.get('trend_20d_pct'), suffix='%')}")
    if profile.get('volume_ratio') is not None:
        parts.append(f"거래량 {_format_metric(profile.get('volume_ratio'), decimals=2)}배")
    return ', '.join(parts)


def _escape(value: Any) -> str:
    return html.escape('' if value is None else str(value), quote=False)


def _format_metric(value: Any, *, suffix: str = '', decimals: int = 0) -> str:
    number = _number(value)
    if decimals <= 0:
        formatted = f'{int(round(number)):,}'
    else:
        formatted = f'{number:,.{decimals}f}'
    return f'{formatted}{suffix}'


def _format_signed_metric(value: Any, *, suffix: str = '', decimals: int = 2) -> str:
    number = _number(value)
    return f'{number:+,.{decimals}f}{suffix}'


def _mode(value: Any) -> str:
    mode = str(value or 'full').strip().lower()
    return mode if mode in {'full', 'rule', 'llm'} else 'full'


def _actions(value: Any) -> tuple[str, ...]:
    if value is None:
        return DEFAULT_ACTIONS
    if isinstance(value, str):
        items = [item.strip() for item in value.split(',')]
    elif isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value]
    else:
        items = []
    actions = tuple(item.upper() for item in items if item)
    return actions or DEFAULT_ACTIONS
