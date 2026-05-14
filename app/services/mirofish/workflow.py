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
        blocked_reason = None if allow_stale_sources else alpha_scanner.get_alert_block_reason(scanner_run)
        if blocked_reason:
            return {
                'ok': False,
                'status': 'blocked',
                'scanner_run_id': scanner_run.get('id'),
                'candidate_count': 0,
                'alert_blocked': True,
                'blocked_reason': blocked_reason,
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
    workflow['event_state_commit_requested'] = bool(commit_event_state and not force)
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
    """카카오톡 공유용 payload — Kakao SDK 'feed'/'list' 템플릿에 맞춘 풍부한 형식.

    각 TOP 종목별로 run.json 을 읽어 5인 에이전트 토론 핵심 발언 + CIO reasoning +
    opposing scenario 를 포함시킨다. 기본은 Feed (단일/전체) 형식, list_contents 도
    동시에 제공해 프론트가 list template 으로 표현 가능.

    Args:
        workflow: workflow dict (read_workflow 결과)
        rank: 1|2|3 — 단일 종목 공유 시. None이면 TOP 3 전체.

    Returns:
        {
            'title', 'description', 'image_url', 'link_url',
            'rank', 'top_items',
            'list_contents': [...]  # Kakao list template 호환 (TOP 3 전체 시),
            'kakao_buttons': [{'title','link_url'}],
            'analyst_quote', 'cio_reasoning' (rank 단일일 때),
            'workflow_id', 'completed_at',
        }
    """
    from app.services.mirofish import store as _store

    top3 = [item for item in (workflow.get('top3') or []) if isinstance(item, dict)]
    workflow_id = str(workflow.get('id') or '')
    completed_at = str(workflow.get('completed_at') or '')

    base_url = 'https://bit-man.net/admin/endpoints'
    fallback_image = 'https://bit-man.net/og/marketflow-mcp-share.png'

    # TOP 3 정규화 + run 상세 enrich
    top_items = []
    for index, item in enumerate(top3[:3], start=1):
        candidate = item.get('candidate') or {}
        verdict = item.get('verdict') or {}
        outcome = item.get('outcome') or {}
        run_id = str(item.get('run_id') or '')

        # run.json 에서 5인 토론 + CIO reasoning enrich
        analyst_quote = ''
        cio_reasoning = ''
        cio_opposing = ''
        cio_allocation_pct = None
        try:
            if run_id:
                run = _store.read_run(run_id)
                if isinstance(run, dict):
                    analyst_quote = _pick_top_analyst_quote(run.get('analysts') or [])
                    cio = run.get('cio') or {}
                    fa = cio.get('final_answer') or {}
                    cio_reasoning = _compress_text(fa.get('reasoning'), 180)
                    cio_opposing = _compress_text(fa.get('opposing_scenario'), 140)
                    cio_allocation_pct = fa.get('allocation_pct')
        except Exception:
            pass

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
            'outcome_horizon_days': outcome.get('primary_horizon_days'),
            'replay_safe_after': outcome.get('entry_date') or outcome.get('replay_safe_after'),
            'analyst_quote': analyst_quote,
            'cio_reasoning': cio_reasoning,
            'cio_opposing': cio_opposing,
            'cio_allocation_pct': cio_allocation_pct,
            'run_id': run_id,
        })

    if not top_items:
        return {
            'title': 'MarketFlow MCP TOP 3',
            'description': 'TOP 3 결과가 아직 준비되지 않았습니다.',
            'image_url': fallback_image,
            'link_url': base_url,
            'rank': None,
            'top_items': [],
            'list_contents': [],
            'kakao_buttons': [{'title': '대시보드 열기', 'link_url': base_url}],
            'workflow_id': workflow_id,
            'completed_at': completed_at,
        }

    # ── 단일 종목 공유 (Feed) ──────────────────────────
    if rank is not None:
        if rank < 1 or rank > len(top_items):
            raise ValueError(f'rank {rank} out of range (1-{len(top_items)})')
        target = top_items[rank - 1]
        verdict_label = _share_verdict_label(target['action'])
        title = f"TOP {rank} {target['name']} — {verdict_label} {target['confidence_pct']}% (score {target['score']:.0f})"

        # description 빌드 (Kakao Feed 200자 제한 — 한글 ~120자 effective)
        desc_lines = []
        if target.get('analyst_quote'):
            desc_lines.append(target['analyst_quote'])
        if target.get('cio_reasoning'):
            desc_lines.append(f"CIO: {_compress_text(target['cio_reasoning'], 110)}")
        # outcome
        if target.get('outcome_forward_return_pct') is not None and target.get('outcome_horizon_days'):
            sign = '+' if target['outcome_forward_return_pct'] >= 0 else ''
            hit_label = '적중' if target.get('outcome_hit') else '미달'
            desc_lines.append(
                f"검증 T{target['outcome_horizon_days']} {sign}{target['outcome_forward_return_pct']:.1f}% {hit_label}"
            )
        if target.get('cio_opposing'):
            desc_lines.append(f"리스크: {_compress_text(target['cio_opposing'], 80)}")
        description = ' / '.join(desc_lines) if desc_lines else f"{target['symbol']} · {verdict_label} {target['confidence_pct']}%"
        description = _compress_text(description, 200)

        return {
            'title': title,
            'description': description,
            'image_url': fallback_image,
            'link_url': f"{base_url}?workflow={workflow_id}&top={rank}",
            'rank': rank,
            'top_items': top_items,
            'list_contents': [],
            'kakao_buttons': [
                {'title': '분석 상세 보기', 'link_url': f"{base_url}?workflow={workflow_id}&top={rank}"},
                {'title': 'TOP 3 전체 보기', 'link_url': f"{base_url}?workflow={workflow_id}"},
            ],
            'analyst_quote': target.get('analyst_quote'),
            'cio_reasoning': target.get('cio_reasoning'),
            'cio_opposing': target.get('cio_opposing'),
            'workflow_id': workflow_id,
            'completed_at': completed_at,
        }

    # ── TOP 3 전체 공유 (Feed + List 양쪽 제공) ─────────
    title = f"MarketFlow MCP TOP 3 — {top_items[0]['name']}외 2종"

    # Feed description: 핵심 한 줄 + 핵심 분석 quote
    quote_lines = []
    for it in top_items:
        verdict_label = _share_verdict_label(it['action'])
        quote = (it.get('analyst_quote') or '')[:60]
        if quote:
            quote_lines.append(f"#{it['rank']} {it['name']}({verdict_label} {it['confidence_pct']}%): {quote}")
        else:
            quote_lines.append(f"#{it['rank']} {it['name']}({verdict_label} {it['confidence_pct']}%) score {it['score']:.0f}")
    description = '\n'.join(quote_lines)
    description = _compress_text(description, 200)

    # List template — 각 종목별 풍부한 카드
    list_contents = []
    for it in top_items:
        verdict_label = _share_verdict_label(it['action'])
        card_title = f"#{it['rank']} {it['name']} — {verdict_label} {it['confidence_pct']}% (score {it['score']:.0f})"
        # 카드 description: analyst quote + 검증 결과 (각 100자)
        card_lines = []
        if it.get('analyst_quote'):
            card_lines.append(it['analyst_quote'])
        if it.get('cio_reasoning'):
            card_lines.append(f"CIO: {_compress_text(it['cio_reasoning'], 70)}")
        if it.get('outcome_forward_return_pct') is not None:
            sign = '+' if it['outcome_forward_return_pct'] >= 0 else ''
            hit = '적중' if it.get('outcome_hit') else '미달'
            card_lines.append(f"T{it.get('outcome_horizon_days') or '?'} {sign}{it['outcome_forward_return_pct']:.1f}% {hit}")
        card_desc = _compress_text(' / '.join(card_lines) if card_lines else f"{it['symbol']} {verdict_label}", 100)
        list_contents.append({
            'title': _compress_text(card_title, 100),
            'description': card_desc,
            'image_url': fallback_image,
            'link_url': f"{base_url}?workflow={workflow_id}&top={it['rank']}",
        })

    return {
        'title': title,
        'description': description,
        'image_url': fallback_image,
        'link_url': f"{base_url}?workflow={workflow_id}",
        'rank': None,
        'top_items': top_items,
        'list_contents': list_contents,
        'kakao_buttons': [
            {'title': 'TOP 3 분석 상세', 'link_url': f"{base_url}?workflow={workflow_id}"},
        ],
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


_PERSONA_AGENT_IDS = {'kim_risk', 'park_momentum', 'lee_quant', 'choi_contrarian', 'jung_hedge'}
_PERSONA_NAMES = {'김리스크', '박모멘텀', '이퀀트', '최역발상', '정헤지'}


def _pick_top_analyst_quote(analysts: list[dict]) -> str:
    """5인 페르소나(김리스크/박모멘텀/이퀀트/최역발상/정헤지) 중 가장 확신도 높은 발언 우선.

    fallback: 다른 모든 analyst 중 confidence 최고.

    예: 박모멘텀(BUY 90%): "sector_momentum 92, ml_prediction 87 모멘텀 강함"
    """
    if not analysts:
        return ''
    valid = [a for a in analysts if isinstance(a, dict) and a.get('message')]
    if not valid:
        return ''

    # 1) 5인 페르소나 우선
    personas = [
        a for a in valid
        if str(a.get('id') or a.get('agent_id') or '') in _PERSONA_AGENT_IDS
        or str(a.get('name') or a.get('agent_name') or '') in _PERSONA_NAMES
    ]
    pool = personas if personas else valid

    # 2) confidence 최고 선택
    sorted_a = sorted(pool, key=lambda a: a.get('confidence', 0), reverse=True)
    top = sorted_a[0]
    name = top.get('name') or top.get('agent_name') or '에이전트'
    stance = (top.get('stance') or top.get('verdict') or 'HOLD').upper()
    conf_raw = top.get('confidence') or 0
    conf = int(round(conf_raw * 100)) if conf_raw <= 1 else int(round(conf_raw))
    msg = _compress_text(top.get('message') or '', 60)
    return f"{name}({stance} {conf}%): \"{msg}\""


def _compress_text(text: Any, max_len: int) -> str:
    """텍스트 정규화 + 길이 제한 (한글 끝잘림 방지)."""
    if not text:
        return ''
    s = ' '.join(str(text).split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'


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
    # Phase C: workflow-level graphrag + source_freshness 보강
    # scanner_run 의 freshness 는 workflow record 의 scanner_freshness 에 기록되어 있음.
    scanner_run_proxy = {
        'freshness': workflow.get('scanner_freshness') or {},
        'generated_at': workflow.get('created_at'),
        'created_at': workflow.get('created_at'),
    }
    graphrag_summary = _workflow_graphrag_summary(top3, scanner_run_proxy)
    source_freshness = _workflow_source_freshness(scanner_run_proxy, graphrag_summary)

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
        # ── Phase C: GraphRAG enrichment + source freshness ────────────
        'graphrag': graphrag_summary,
        'source_freshness': source_freshness,
    })
    if workflow.get('event_state_commit_requested') and not workflow.get('event_state_committed'):
        try:
            commit_workflow_event_state(workflow)
        except Exception as exc:
            workflow['event_state_commit_error'] = f'{type(exc).__name__}: {exc}'
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

    # Phase C: per-top3 graphrag mini-dict
    extraction = run.get('graph_extraction') or {}
    merge_stats = run.get('graph_merge') or {}
    graph_links = pipeline.get('graph_links')
    if graph_links is None:
        graph_links = merge_stats.get('total_relations') or len(extraction.get('relations') or [])
    graphrag_item = {
        'links': graph_links,
        'entities': len(extraction.get('entities') or []),
        'relations': len(extraction.get('relations') or []),
        'method': pipeline.get('graph_method') or extraction.get('method') or 'ascii_brain_v1',
    }

    # Phase C: P0 #4 verdict identity 보강 (run.verdict 가 4필드를 못 채웠을 때 candidate 로 fallback)
    verdict_symbol = verdict.get('symbol') or run.get('symbol') or candidate.get('symbol')
    verdict_market = verdict.get('market') or run.get('market') or candidate.get('market')
    verdict_target_label = verdict.get('target') or run.get('display_name') or candidate.get('display_name') or candidate.get('name')
    verdict_reference_date = verdict.get('reference_date') or run.get('created_at') or (candidate.get('price') or {}).get('date')
    verdict_target_display = verdict.get('target_display')
    if not verdict_target_display:
        if verdict_symbol and verdict_market and verdict_target_label:
            verdict_target_display = f"{verdict_target_label} ({verdict_symbol} {verdict_market})"
        else:
            verdict_target_display = verdict_target_label or verdict_symbol or '(unknown target)'

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
            'target': verdict_target_label,
            'summary': verdict.get('summary'),
            # ── P0 #4: 종목 식별 + 분석 기준일 (UI/Telegram 직접 사용) ──
            'symbol': verdict_symbol,
            'market': verdict_market,
            'reference_date': verdict_reference_date,
            'target_display': verdict_target_display,
        },
        'graph': {
            'links': pipeline.get('graph_links'),
            'similar_events': pipeline.get('similar_events'),
            'method': pipeline.get('graph_method'),
        },
        # Phase C: per-top3 graphrag mini-dict
        'graphrag': graphrag_item,
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


def _workflow_graphrag_summary(top3: list[dict[str, Any]], scanner_run: dict[str, Any]) -> dict[str, Any]:
    """Phase C: workflow-level GraphRAG 요약.

    - entity_count / edge_count: top3 의 graphrag.entities / graphrag.links 합산
    - source_coverage: 5개 운영 데이터 소스(scanner/kis/tradingview/dart/news)의 status 분류
    """
    entity_count = 0
    edge_count = 0
    for item in top3 or []:
        if not isinstance(item, dict):
            continue
        gr = item.get('graphrag') or {}
        try:
            entity_count += int(gr.get('entities') or 0)
        except (TypeError, ValueError):
            pass
        try:
            edge_count += int(gr.get('links') or 0)
        except (TypeError, ValueError):
            pass

    # source_coverage: scanner_run.freshness + 각 top3 candidate 의 data sources 종합
    scanner_freshness = scanner_run.get('freshness') or {}
    scanner_status_raw = str(scanner_freshness.get('status') or '').lower()
    scanner_status = {
        'fresh': 'live',
        'partial': 'cached',
        'unknown': 'stale',
        'stale': 'stale',
        'missing': 'unavailable',
    }.get(scanner_status_raw, scanner_status_raw or 'unavailable')

    # KIS / DART / news 가용성 — top3 candidate 의 replay_context + run-side data_context 합산
    kis_seen = False
    dart_seen = False
    news_seen = False
    tv_seen = False
    for item in top3 or []:
        if not isinstance(item, dict):
            continue
        candidate = item.get('candidate') or {}
        # candidate.replay_context.data_sources 만 안전하게 사용 (workflow.json 페이로드에 항상 있음)
        sources = (candidate.get('replay_context') or {}).get('data_sources') or []
        for src in sources:
            src_lower = str(src or '').lower()
            if 'kis' in src_lower:
                kis_seen = True
            if 'dart' in src_lower:
                dart_seen = True
            if 'news' in src_lower or 'briefing' in src_lower:
                news_seen = True
            if 'tradingview' in src_lower or 'tv' in src_lower:
                tv_seen = True

    return {
        'mode': 'hybrid_temporal',
        'entity_count': entity_count,
        'edge_count': edge_count,
        'source_coverage': {
            'scanner': scanner_status,
            'kis': 'cached' if kis_seen else 'unavailable',
            'tradingview': 'cached' if tv_seen else 'unavailable',
            'dart': 'cached' if dart_seen else 'unavailable',
            'news': 'cached' if news_seen else 'unavailable',
        },
    }


def _workflow_source_freshness(scanner_run: dict[str, Any], graphrag_summary: dict[str, Any]) -> dict[str, Any]:
    """Phase C: workflow-level source_freshness 요약.

    scanner_run.freshness (status, stale_files, available_files) +
    graphrag.source_coverage 를 단일 'fresh|partial|stale' 상태로 통합.
    """
    scanner_freshness = scanner_run.get('freshness') or {}
    scanner_status_raw = str(scanner_freshness.get('status') or '').lower()
    # last_update / data_age_hours 계산
    last_update = scanner_run.get('generated_at') or scanner_run.get('created_at')
    data_age_hours: float | None = None
    if last_update:
        try:
            normalized = str(last_update).replace('Z', '+00:00')
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - dt
            data_age_hours = round(delta.total_seconds() / 3600.0, 2)
        except (ValueError, TypeError):
            data_age_hours = None

    # 통합 status — scanner status + source_coverage 결합
    if scanner_status_raw == 'fresh':
        status = 'fresh'
    elif scanner_status_raw in {'stale', 'missing'}:
        status = 'stale'
    elif scanner_status_raw in {'partial', 'unknown'}:
        status = 'partial'
    else:
        status = 'partial'

    coverage = (graphrag_summary or {}).get('source_coverage') or {}
    return {
        'status': status,
        'last_update': last_update,
        'data_age_hours': data_age_hours,
        'sources': {
            'scanner_freshness': scanner_status_raw or 'unknown',
            'stale_files': scanner_freshness.get('stale_files'),
            'available_files': scanner_freshness.get('available_files'),
            'missing_required_files': scanner_freshness.get('missing_required_files'),
            'kis_freshness': coverage.get('kis'),
            'tradingview_freshness': coverage.get('tradingview'),
            'dart_freshness': coverage.get('dart'),
            'news_freshness': coverage.get('news'),
        },
    }


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
        # ── Phase C: workflow summary 에도 GraphRAG/freshness 노출 ─────
        'graphrag': workflow.get('graphrag'),
        'source_freshness': workflow.get('source_freshness'),
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
