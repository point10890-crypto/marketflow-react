"""File-backed live MiroFish runs for the admin console."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish import agent_debate, cio_react, graphrag_extractor, live_data
from app.utils.atomic_json import write_json_atomic

_log = logging.getLogger(__name__)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'runs')
MAX_AGENT_COUNT = 15


PIPELINE_PHASES = [
    {'id': 'intake', 'label': 'Target Intake', 'status': 'ready'},
    {'id': 'brain_snapshot', 'label': 'Brain 13D Snapshot', 'status': 'ready'},
    {'id': 'graph_build', 'label': 'GraphRAG Build', 'status': 'ready'},
    {'id': 'analyst_mesh', 'label': 'Agent Debate', 'status': 'ready'},
    {'id': 'verdict', 'label': 'CIO Verdict', 'status': 'ready'},
    {'id': 'report', 'label': 'Markdown Report', 'status': 'ready'},
]


def get_status() -> dict[str, Any]:
    os.makedirs(RUNS_ROOT, exist_ok=True)
    brain = _brain_summary('MiroFish')
    ekg = graphrag_extractor.get_ekg_stats()
    return {
        'service': 'admin-mirofish',
        'ready': True,
        'mode': 'live_file_artifacts',
        'source': 'MarketFlow scheduler artifacts',
        'storage': {
            'type': 'filesystem',
            'path': os.path.relpath(RUNS_ROOT, REPO_ROOT).replace('\\', '/'),
        },
        'brain_summary': brain,
        'brain': _frontend_brain(brain),
        'pipeline': {
            'status': 'ready',
            'graph_links': ekg.get('total_relations', 0),
            'similar_events': max(0, min(99, ekg.get('total_entities', 0))),
            'agent_count': MAX_AGENT_COUNT,
        },
        'pipeline_phases': PIPELINE_PHASES,
        'data_sources': live_data.summarize_data_sources(),
        'limits': {
            'max_agent_count': MAX_AGENT_COUNT,
            'external_llm_required': False,
        },
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }


def get_data_sources() -> dict[str, Any]:
    return live_data.summarize_data_sources()


def search_target_candidates(target: str, limit: int = 16) -> dict[str, Any]:
    clean_target = str(target or '').strip()
    if not clean_target:
        return {'target': '', 'candidates': []}
    clean_limit = max(1, min(int(limit or 16), 30))
    return {
        'target': clean_target,
        'source': 'ticker_map',
        'candidates': live_data.search_target_candidates(clean_target, limit=clean_limit),
    }


def resolve_target_snapshot(target: str) -> dict[str, Any]:
    clean_target = _clean_target(target)
    context = live_data.build_context(clean_target)
    resolved = context.get('resolved') or {}
    price = context.get('price') or {}
    signals = context.get('signals') or {}
    candidates = live_data.search_target_candidates(clean_target, limit=16)
    return {
        'target': clean_target,
        'source': 'live_file_artifacts',
        'resolved': resolved,
        'candidates': candidates,
        'price': price,
        'kis': context.get('kis'),
        'signals': signals,
        'signal_count': sum(1 for item in signals.values() if item),
        'briefing_count': len(context.get('briefings') or []),
        'dart_available': bool(context.get('dart')),
        'source_packet_count': len(context.get('source_packets') or []),
        'hybrid_context': context.get('hybrid_context'),
        'source_files': context.get('source_files', []),
        'built_at': context.get('built_at'),
    }


def create_run(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    target = _clean_target(payload.get('target'))
    mode = _clean_mode(payload.get('mode'))
    agent_count = _clean_agent_count(payload.get('agent_count'))
    run_id = _run_id(target, agent_count, mode)

    run_dir = _run_dir(run_id)
    os.makedirs(run_dir, exist_ok=True)

    if _async_requested(payload):
        run = _create_running_run(run_id, target, agent_count, mode)
        graph = _build_graph(run)
        write_json_atomic(os.path.join(run_dir, 'run.json'), run, sort_keys=False)
        write_json_atomic(os.path.join(run_dir, 'graph.json'), graph, sort_keys=False)
        _write_text_atomic(os.path.join(run_dir, 'report.md'), _running_report(run))
        _append_run_event(
            run_id,
            'info',
            'intake',
            f'Queued live MiroFish run for {target}.',
            text=f'대상 입력 대기열 등록: {target}',
            progress=2,
        )
        thread = threading.Thread(
            target=_complete_run_background,
            args=(run_id, target, agent_count, mode),
            name=f'mirofish-{run_id[:24]}',
            daemon=True,
        )
        thread.start()
        return run

    run = _build_run(run_id, target, agent_count, mode)
    graph = _build_graph(run)
    report = _build_report(run, graph)

    write_json_atomic(os.path.join(run_dir, 'run.json'), run, sort_keys=False)
    write_json_atomic(os.path.join(run_dir, 'graph.json'), graph, sort_keys=False)
    _write_text_atomic(os.path.join(run_dir, 'report.md'), report)
    _write_events(run_id, run.get('logs', []))
    return run


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not os.path.isdir(RUNS_ROOT):
        return []

    runs: list[dict[str, Any]] = []
    for name in os.listdir(RUNS_ROOT):
        try:
            run_file = os.path.join(_run_dir(name), 'run.json')
        except ValueError:
            continue
        if not os.path.isfile(run_file):
            continue
        try:
            run = _read_json(run_file)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        runs.append(_summary(run))

    runs.sort(key=lambda item: item.get('created_at', ''), reverse=True)
    return runs[:limit]


def read_run(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = os.path.join(_run_dir(safe_id), 'run.json')
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def get_graph(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = os.path.join(_run_dir(safe_id), 'graph.json')
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def get_report(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = os.path.join(_run_dir(safe_id), 'report.md')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        markdown = f.read()
    return {'run_id': safe_id, 'format': 'markdown', 'markdown': markdown}


def attach_tradingagents(run_id: str, ta: dict[str, Any]) -> dict[str, Any] | None:
    """TradingAgents 딥검증 결과 요약을 run.json 에 원자적으로 부착.

    run 이 없으면 None. verdict 요약만 저장(전문 트레이스는 tradingagents_runs 스토어에 별도 영속).
    """
    safe_id = _safe_run_id(run_id)
    run = read_run(safe_id)
    if not run:
        return None
    v = (ta or {}).get('verdict') or {}
    summary = {
        'run_id': ta.get('id'),
        'verdict': v.get('verdict'),
        'confidence': v.get('confidence'),
        'strong_buy': bool(v.get('strong_buy')),
        'regime': v.get('regime'),
        'regime_adjustment': v.get('regime_adjustment'),
        'method': ta.get('method'),
        'bull_case': v.get('bull_case'),
        'bear_case': v.get('bear_case'),
        'risk_summary': v.get('risk_summary'),
        'attached_at': datetime.now(timezone.utc).isoformat(),
    }
    run['tradingagents'] = summary
    write_json_atomic(os.path.join(_run_dir(safe_id), 'run.json'), run, sort_keys=False)
    return summary


def create_compact_run(
    candidate: dict[str, Any], ta: dict[str, Any], *, agent_count: int | None = None,
) -> dict[str, Any]:
    """Persist one compact TA result in the legacy run/graph/report contract."""
    source_run_id = str(ta.get('id') or '')
    digest = hashlib.sha256(source_run_id.encode('utf-8')).hexdigest()[:10]
    run_id = f'mf_compact_{digest}'
    created_at = str(ta.get('created_at') or datetime.now(timezone.utc).isoformat())
    tav = ta.get('verdict') or {}
    confidence_pct = max(0.0, min(100.0, float(tav.get('confidence') or 0.0)))
    confidence = confidence_pct / 100.0
    target = str(candidate.get('display_name') or candidate.get('name') or ta.get('target') or candidate.get('symbol'))
    action = str(tav.get('verdict') or 'HOLD_REVIEW').upper()
    status = str(ta.get('analysis_status') or tav.get('analysis_status') or 'HOLD_REVIEW')
    raw_price = candidate.get('price')
    price_snapshot = dict(raw_price) if isinstance(raw_price, dict) else {
        'current_price': raw_price, 'price': raw_price,
    }
    current_price = price_snapshot.get('current_price', price_snapshot.get('price'))
    price_snapshot.setdefault('current_price', current_price)
    price_snapshot.setdefault('price', current_price)
    compatibility_agent_count = max(1, int(agent_count or len(ta.get('analyst_reports') or []) or 1))
    verdict = {
        'action': action, 'label': action, 'confidence': confidence,
        'confidence_pct': int(round(confidence_pct)), 'bullish': 0, 'neutral': 0, 'bearish': 0,
        'target': target, 'summary': str(tav.get('reasoning') or ''),
        'reasoning': str(tav.get('reasoning') or ''), 'opposing_scenario': tav.get('bear_case'),
        'symbol': candidate.get('symbol'), 'market': candidate.get('market'),
        'reference_date': price_snapshot.get('date') or (ta.get('evidence_packet') or {}).get('as_of'),
        'target_display': f"{target} ({candidate.get('symbol')} {candidate.get('market')})",
        'analysis_status': status, 'rule_candidate_verdict': tav.get('rule_candidate_verdict'),
    }
    reports = ta.get('analyst_reports') or []
    analysts = [{
        'id': f"ta_{row.get('role')}", 'name': row.get('title') or row.get('role'),
        'role': row.get('role'), 'stance': 'BUY' if row.get('stance') == 'bullish' else 'SELL' if row.get('stance') == 'bearish' else 'HOLD',
        'confidence': min(1.0, abs(float(row.get('score') or 0)) / 100.0),
        'message': row.get('summary'),
    } for row in reports]
    run = {
        'id': run_id, 'target': target, 'display_name': target,
        'symbol': candidate.get('symbol'), 'market': candidate.get('market'),
        'mode': 'compact', 'source': 'tradingagents_compact', 'status': 'completed',
        'analysis_status': status, 'created_at': created_at,
        'completed_at': ta.get('completed_at') or datetime.now(timezone.utc).isoformat(),
        'deterministic': False, 'price': current_price,
        'change_pct': price_snapshot.get('change_pct', price_snapshot.get('change_rate', 0)),
        'price_snapshot': price_snapshot, 'brain_summary': {}, 'brain': {},
        'graph_extraction': {'entities': [], 'relations': [], 'method': 'compact_evidence_packet'},
        'graph_merge': {'total_relations': 0}, 'debate': ta.get('research_debate') or {},
        'cio': {'final_answer': verdict, 'analysis_status': status},
        'pipeline': {'status': 'completed', 'graph_links': 0, 'similar_events': 0,
                     'agent_count': compatibility_agent_count,
                     'compact_role_count': len(analysts),
                     'compatibility_schema': 'legacy-agent-count-v1',
                     'graph_method': 'compact_evidence_packet',
                     'debate_method': (ta.get('research_debate') or {}).get('method'),
                     'cio_method': 'compact_portfolio_manager'},
        'pipeline_phases': [{**phase, 'status': 'completed', 'progress': 1.0} for phase in PIPELINE_PHASES],
        'progress': {'completed_phases': len(PIPELINE_PHASES), 'total_phases': len(PIPELINE_PHASES), 'percent': 100},
        'layers': [
            {'label': 'TARGET', 'count': 1, 'color': 'bg-red-500'},
            {'label': 'CAUSAL HISTORY', 'count': 0, 'color': 'bg-blue-500'},
            {'label': 'AI ANALYSTS', 'count': compatibility_agent_count, 'color': 'bg-violet-500'},
            {'label': 'PREDICTIONS', 'count': compatibility_agent_count, 'color': 'bg-orange-400'},
            {'label': 'VERDICT', 'count': 1, 'color': 'bg-emerald-400'},
        ],
        'logs': [], 'analysts': analysts, 'graph_nodes': [], 'prediction_nodes': [],
        'verdict': verdict, 'data_context': {'source_packets': (ta.get('evidence_packet') or {}).get('sources') or []},
        'source_run_id': source_run_id, 'provider_usage': ta.get('provider_usage') or {},
        'profile': 'compact', 'evidence_fingerprint': ta.get('evidence_fingerprint'),
        'tradingagents': {
            'run_id': source_run_id, 'verdict': action, 'confidence': confidence_pct,
            'strong_buy': action == 'STRONG_BUY', 'method': ta.get('method'),
            'provider_usage': ta.get('provider_usage') or {},
        },
        'artifacts': _artifact_links(run_id),
    }
    graph = _build_graph(run)
    report = _build_report(run, graph)
    run_dir = _run_dir(run_id)
    os.makedirs(run_dir, exist_ok=True)
    write_json_atomic(os.path.join(run_dir, 'run.json'), run, sort_keys=False)
    write_json_atomic(os.path.join(run_dir, 'graph.json'), graph, sort_keys=False)
    _write_text_atomic(os.path.join(run_dir, 'report.md'), report)
    return run


def _create_running_run(run_id: str, target: str, agent_count: int, mode: str) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    return {
        'id': run_id,
        'target': target,
        'display_name': target,
        'symbol': None,
        'market': None,
        'mode': mode,
        'source': 'live_file_artifacts',
        'status': 'running',
        'created_at': created_at,
        'started_at': created_at,
        'deterministic': False,
        'price': None,
        'change_pct': 0,
        'pipeline': {
            'status': 'running',
            'graph_links': 0,
            'similar_events': 0,
            'agent_count': agent_count,
        },
        'pipeline_phases': _phase_states('intake', 2),
        'progress': {
            'completed_phases': 0,
            'total_phases': len(PIPELINE_PHASES),
            'percent': 2,
            'current_phase': 'intake',
            'current_label': 'Target Intake',
            'started_at': created_at,
            'updated_at': created_at,
            'elapsed_ms': 0,
        },
        'performance': {
            'elapsed_ms': 0,
            'phase_durations_ms': {},
            'events_count': 1,
            'graph_nodes': 0,
            'graph_edges': 0,
        },
        'layers': _layers(0, 0, 0, False),
        'logs': [],
        'analysts': [],
        'graph_nodes': [],
        'prediction_nodes': [],
        'data_context': {
            'source_files': [],
            'source_packets': [],
            'hybrid_context': None,
            'signals': {},
            'briefing_count': 0,
            'dart_available': False,
        },
        'artifacts': _artifact_links(run_id),
    }


def _complete_run_background(run_id: str, target: str, agent_count: int, mode: str) -> None:
    try:
        _build_run_progressive(run_id, target, agent_count, mode)
    except Exception as exc:
        _mark_run_failed(run_id, exc)


def _build_run_progressive(run_id: str, target: str, agent_count: int, mode: str) -> dict[str, Any]:
    started = time.perf_counter()
    phase_started = started
    run = read_run(run_id) or _create_running_run(run_id, target, agent_count, mode)
    use_llm = _use_llm(mode)

    def save(phase_id: str, percent: int, message: str, *, text: str | None = None,
             payload: dict[str, Any] | None = None, completed: bool = False) -> None:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        run['status'] = 'completed' if completed else 'running'
        run['pipeline']['status'] = run['status']
        run['pipeline_phases'] = _phase_states(phase_id, percent, completed=completed)
        run['progress'] = {
            'completed_phases': _completed_phase_count(phase_id, completed),
            'total_phases': len(PIPELINE_PHASES),
            'percent': percent,
            'current_phase': phase_id,
            'current_label': _phase_label(phase_id),
            'started_at': run.get('started_at') or run.get('created_at'),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'elapsed_ms': elapsed_ms,
        }
        graph = _build_graph(run)
        event = _append_run_event(run_id, 'info', phase_id, message, text=text, progress=percent, elapsed_ms=elapsed_ms, payload=payload)
        run.setdefault('logs', []).append(_event_to_log(event, text))
        run['performance'] = {
            **(run.get('performance') or {}),
            'elapsed_ms': elapsed_ms,
            'events_count': len(run.get('logs') or []) + 1,
            'graph_nodes': len(graph.get('nodes') or []),
            'graph_edges': len(graph.get('edges') or []),
        }
        write_json_atomic(os.path.join(_run_dir(run_id), 'run.json'), run, sort_keys=False)
        write_json_atomic(os.path.join(_run_dir(run_id), 'graph.json'), graph, sort_keys=False)

    save('intake', 8, f'Started live target intake for {target}.', text=f'대상 입력: {target}')
    context = live_data.build_context(target)
    resolved = context['resolved']
    price = context.get('price') or {}
    final_target = resolved.get('display_name') or target
    run.update({
        'target': final_target,
        'display_name': final_target,
        'symbol': resolved.get('symbol'),
        'market': resolved.get('market'),
        'price': price.get('price'),
        'change_pct': price.get('change_pct', 0),
        'price_snapshot': price,
        'data_context': {
            'source_files': context.get('source_files', []),
            'source_packets': context.get('source_packets', []),
            'hybrid_context': context.get('hybrid_context'),
            'signals': context.get('signals', {}),
            'briefing_count': len(context.get('briefings') or []),
            'dart_available': bool(context.get('dart')),
            'kis': context.get('kis'),
            'built_at': context.get('built_at'),
        },
    })
    _record_phase_duration(run, 'intake', phase_started)
    phase_started = time.perf_counter()
    save(
        'intake',
        16,
        f"Resolved {len(context.get('source_files', []))} source files and {len(context.get('source_packets') or [])} source packets.",
        text=f"실데이터 소스 {len(context.get('source_files', []))}개, source packet {len(context.get('source_packets') or [])}개 연결",
        payload={
            'source_files': context.get('source_files', []),
            'source_packet_count': len(context.get('source_packets') or []),
            'hybrid_context': context.get('hybrid_context'),
            'symbol': resolved.get('symbol'),
        },
    )
    kis = context.get('kis') or {}
    if kis.get('enabled'):
        save(
            'intake',
            20,
            f"KIS API live source found={bool(kis.get('found'))}.",
            text='KIS API 실시간 데이터 연결' if kis.get('found') else 'KIS API 실시간 데이터 대기',
            payload={'kis_found': bool(kis.get('found')), 'sources': kis.get('sources', [])},
        )

    brain = _brain_summary(final_target)
    run['brain_summary'] = brain
    run['brain'] = _frontend_brain(brain)
    _record_phase_duration(run, 'brain_snapshot', phase_started)
    phase_started = time.perf_counter()
    save(
        'brain_snapshot',
        32,
        'Loaded Brain 13D snapshot.',
        text=f"Brain 13D 실데이터 스냅샷 적재: {run['brain'].get('score')}점",
        payload={'brain': run.get('brain')},
    )

    save(
        'graph_build',
        40,
        'GraphRAG extraction started.',
        text='GraphRAG 추출 시작',
        payload={'method': 'llm' if use_llm else 'rule'},
    )
    extracted = graphrag_extractor.extract_graph(context.get('corpus', ''), use_llm=use_llm)
    merge_stats = graphrag_extractor.merge_into_ekg(extracted)
    graph_nodes = _graph_nodes_from_extraction(extracted, resolved)
    run['graph_extraction'] = extracted
    run['graph_merge'] = merge_stats
    run['graph_nodes'] = graph_nodes
    run['pipeline'].update({
        'graph_links': merge_stats.get('total_relations', len(extracted.get('relations', []))),
        'similar_events': len(context.get('briefings') or []),
        'graph_method': extracted.get('method'),
    })
    run['layers'] = _layers(len(graph_nodes), 0, 0, False)
    _record_phase_duration(run, 'graph_build', phase_started)
    phase_started = time.perf_counter()
    save(
        'graph_build',
        54,
        f"GraphRAG extracted {len(extracted.get('entities', []))} entities and {len(extracted.get('relations', []))} relations.",
        text=f"GraphRAG 인과 {merge_stats.get('total_relations', 0)}개 연결",
        payload={'entities': len(extracted.get('entities', [])), 'relations': len(extracted.get('relations', []))},
    )

    save(
        'analyst_mesh',
        62,
        'Agent debate started.',
        text=f'에이전트 토론 시작: {agent_count}명',
        payload={'agent_count': agent_count},
    )
    debate = agent_debate.run_debate(final_target, brain, rounds=2, use_llm=use_llm)
    analysts = _analysts_from_debate(debate, agent_count, brain)
    prediction_nodes = _prediction_nodes(analysts)
    run['debate'] = debate
    run['analysts'] = analysts
    run['prediction_nodes'] = prediction_nodes
    run['pipeline']['agent_count'] = len(analysts)
    run['pipeline']['debate_method'] = debate.get('method')
    run['layers'] = _layers(len(graph_nodes), len(analysts), len(prediction_nodes), False)
    _record_phase_duration(run, 'analyst_mesh', phase_started)
    phase_started = time.perf_counter()
    save(
        'analyst_mesh',
        74,
        f"Agent debate completed with {len(analysts)} analysts.",
        text=f"에이전트 토론 완료: {len(analysts)}명",
        payload={'agent_count': len(analysts), 'method': debate.get('method')},
    )

    save(
        'verdict',
        82,
        'CIO verdict synthesis started.',
        text='CIO 판정 합성 시작',
        payload={'method': 'llm' if use_llm else 'rule'},
    )
    cio = cio_react.run_cio(
        final_target, brain, debate, use_llm=use_llm, run_id=run_id,
        symbol=resolved.get('symbol'), market=resolved.get('market'),
    )
    # P0 #4: verdict 에 종목 식별 + 분석 기준일 명시 전달
    verdict_reference_date = (
        (price.get('date') if isinstance(price, dict) else None)
        or run.get('created_at')
        or datetime.now(timezone.utc).isoformat()
    )
    verdict = _verdict_from_cio(
        cio,
        debate,
        analysts,
        final_target,
        symbol=resolved.get('symbol'),
        market=resolved.get('market'),
        reference_date=verdict_reference_date,
    )
    run['cio'] = cio
    run['verdict'] = verdict
    run['pipeline']['cio_method'] = cio.get('method')
    run['layers'] = _layers(len(graph_nodes), len(analysts), len(prediction_nodes), True)
    _record_phase_duration(run, 'verdict', phase_started)
    phase_started = time.perf_counter()
    save(
        'verdict',
        90,
        f"CIO verdict={verdict.get('action')} confidence={verdict.get('confidence_pct')}%.",
        text=f"최종 판정: {verdict.get('action')} {verdict.get('confidence_pct')}%",
        payload={'verdict': verdict},
    )

    graph = _build_graph(run)
    report = _build_report(run, graph)
    _write_text_atomic(os.path.join(_run_dir(run_id), 'report.md'), report)
    run['completed_at'] = datetime.now(timezone.utc).isoformat()
    _record_phase_duration(run, 'report', phase_started)
    run['progress'] = {
        'completed_phases': len(PIPELINE_PHASES),
        'total_phases': len(PIPELINE_PHASES),
        'percent': 100,
        'current_phase': 'report',
        'current_label': 'Markdown Report',
        'started_at': run.get('started_at') or run.get('created_at'),
        'updated_at': run['completed_at'],
        'elapsed_ms': int((time.perf_counter() - started) * 1000),
    }
    save(
        'report',
        100,
        'Report and artifacts completed.',
        text=f"리포트 생성 완료: {len(graph.get('nodes', []))} nodes / {len(graph.get('edges', []))} edges",
        payload={'report_chars': len(report), 'nodes': len(graph.get('nodes', [])), 'edges': len(graph.get('edges', []))},
        completed=True,
    )
    write_json_atomic(os.path.join(_run_dir(run_id), 'graph.json'), graph, sort_keys=False)
    return run


def _build_run(run_id: str, target: str, agent_count: int, mode: str) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
    context = live_data.build_context(target)
    resolved = context['resolved']
    price = context.get('price') or {}
    use_llm = _use_llm(mode)

    final_target = resolved.get('display_name') or target
    brain = _brain_summary(final_target)
    extracted = graphrag_extractor.extract_graph(context.get('corpus', ''), use_llm=use_llm)
    merge_stats = graphrag_extractor.merge_into_ekg(extracted)
    debate = agent_debate.run_debate(final_target, brain, rounds=2, use_llm=use_llm)
    cio = cio_react.run_cio(
        final_target, brain, debate, use_llm=use_llm, run_id=run_id,
        symbol=resolved.get('symbol'), market=resolved.get('market'),
    )

    analysts = _analysts_from_debate(debate, agent_count, brain)
    # P0 #4: verdict 에 종목 식별 + 분석 기준일 명시 전달
    verdict_reference_date = (
        (price.get('date') if isinstance(price, dict) else None)
        or created_at
    )
    verdict = _verdict_from_cio(
        cio,
        debate,
        analysts,
        final_target,
        symbol=resolved.get('symbol'),
        market=resolved.get('market'),
        reference_date=verdict_reference_date,
    )
    graph_nodes = _graph_nodes_from_extraction(extracted, resolved)
    prediction_nodes = _prediction_nodes(analysts)
    layers = [
        {'label': 'TARGET', 'count': 1, 'color': 'bg-red-500'},
        {'label': 'CAUSAL HISTORY', 'count': len(graph_nodes), 'color': 'bg-blue-500'},
        {'label': 'AI ANALYSTS', 'count': len(analysts), 'color': 'bg-violet-500'},
        {'label': 'PREDICTIONS', 'count': len(prediction_nodes), 'color': 'bg-orange-400'},
        {'label': 'VERDICT', 'count': 1, 'color': 'bg-emerald-400'},
    ]

    logs = _logs(final_target, context, extracted, merge_stats, debate, cio, verdict)
    pipeline = {
        'status': 'completed',
        'graph_links': merge_stats.get('total_relations', len(extracted.get('relations', []))),
        'similar_events': len(context.get('briefings') or []),
        'agent_count': len(analysts),
        'graph_method': extracted.get('method'),
        'debate_method': debate.get('method'),
        'cio_method': cio.get('method'),
    }

    return {
        'id': run_id,
        'target': final_target,
        'display_name': final_target,
        'symbol': resolved.get('symbol'),
        'market': resolved.get('market'),
        'mode': mode,
        'source': 'live_file_artifacts',
        'status': 'completed',
        'created_at': created_at,
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'deterministic': False,
        'price': price.get('price'),
        'change_pct': price.get('change_pct', 0),
        'price_snapshot': price,
        'brain_summary': brain,
        'brain': _frontend_brain(brain),
        'graph_extraction': extracted,
        'graph_merge': merge_stats,
        'debate': debate,
        'cio': cio,
        'pipeline': pipeline,
        'pipeline_phases': [{**phase, 'status': 'completed', 'progress': 1.0} for phase in PIPELINE_PHASES],
        'progress': {'completed_phases': len(PIPELINE_PHASES), 'total_phases': len(PIPELINE_PHASES), 'percent': 100},
        'layers': layers,
        'logs': logs,
        'analysts': analysts,
        'graph_nodes': graph_nodes,
        'prediction_nodes': prediction_nodes,
        'verdict': verdict,
        'data_context': {
            'source_files': context.get('source_files', []),
            'source_packets': context.get('source_packets', []),
            'hybrid_context': context.get('hybrid_context'),
            'signals': context.get('signals', {}),
            'briefing_count': len(context.get('briefings') or []),
            'dart_available': bool(context.get('dart')),
            'kis': context.get('kis'),
            'built_at': context.get('built_at'),
        },
        'artifacts': {
            'run': f'/api/admin/mirofish/runs/{run_id}',
            'graph': f'/api/admin/mirofish/runs/{run_id}/graph',
            'report': f'/api/admin/mirofish/runs/{run_id}/report',
            'events': f'/api/admin/mirofish/runs/{run_id}/events',
        },
    }


def _build_graph(run: dict[str, Any]) -> dict[str, Any]:
    target = run['target']
    run_id = run['id']
    brain = run.get('brain_summary', {})
    extracted = run.get('graph_extraction') or {}
    verdict = run.get('verdict') or {}

    layers = [
        {'id': 'blue', 'label': 'Existing Knowledge (EKG + Brain)', 'color': '#3b82f6', 'order': 1},
        {'id': 'red', 'label': 'Run-Inferred Causal Chains', 'color': '#ef4444', 'order': 2},
        {'id': 'gold', 'label': 'Final Verdict Convergence', 'color': '#f59e0b', 'order': 3},
    ]
    nodes: list[dict[str, Any]] = [
        {'id': 'target', 'layer': 'blue', 'label': target, 'type': 'target', 'score': 1.0},
        {'id': 'brain13d', 'layer': 'blue', 'label': 'Brain 13D', 'type': 'brain', 'score': brain.get('alignment_score', 0)},
    ]
    edges: list[dict[str, Any]] = [
        {'source': 'target', 'target': 'brain13d', 'weight': 0.9, 'label': 'framed_by', 'layer': 'blue'},
    ]

    dim_scores = brain.get('dimension_scores', {}) if isinstance(brain.get('dimension_scores'), dict) else {}
    visible_dims = sorted(
        ((k, v) for k, v in dim_scores.items() if isinstance(v, dict) and v.get('score') is not None),
        key=lambda item: item[1].get('confidence', 0),
        reverse=True,
    )[:6]
    for dim_name, dim_data in visible_dims:
        dim_id = f'dim_{_slug(dim_name)}'
        nodes.append({
            'id': dim_id,
            'layer': 'blue',
            'label': dim_name.replace('_', ' ').title(),
            'type': 'dimension',
            'score': round((dim_data.get('score') or 0) / 100, 3),
            'evidence': str(dim_data.get('evidence', ''))[:160],
        })
        edges.append({'source': 'brain13d', 'target': dim_id, 'weight': dim_data.get('confidence', 0.5), 'label': 'measures', 'layer': 'blue'})

    for entity in (extracted.get('entities') or [])[:30]:
        ent_id = f"ent_{_slug(entity.get('id') or entity.get('name') or 'node')}"
        nodes.append({
            'id': ent_id,
            'layer': 'red',
            'label': entity.get('name') or entity.get('id'),
            'type': entity.get('type', 'entity'),
            'score': 0.6,
        })
        edges.append({'source': 'target', 'target': ent_id, 'weight': 0.45, 'label': 'mentions', 'layer': 'red'})

    for relation in (extracted.get('relations') or [])[:40]:
        src = f"ent_{_slug(relation.get('source_id') or '')}"
        dst = f"ent_{_slug(relation.get('target_id') or '')}"
        if src == 'ent_' or dst == 'ent_':
            continue
        edges.append({
            'source': src,
            'target': dst,
            'weight': relation.get('strength', 0.5),
            'label': relation.get('relation_type', 'related_to'),
            'layer': 'red',
            'evidence': str(relation.get('evidence', ''))[:160],
        })

    for analyst in run.get('analysts', [])[:MAX_AGENT_COUNT]:
        aid = f"agent_{_slug(analyst.get('id') or analyst.get('name'))}"
        nodes.append({'id': aid, 'layer': 'red', 'label': analyst.get('name'), 'type': 'analyst', 'score': analyst.get('confidence', 0.5), 'stance': analyst.get('stance') or analyst.get('verdict')})
        edges.append({'source': aid, 'target': 'verdict', 'weight': analyst.get('confidence', 0.5), 'label': str(analyst.get('stance') or analyst.get('verdict') or 'votes').lower(), 'layer': 'red'})

    nodes.append({
        'id': 'verdict',
        'layer': 'gold',
        'label': f"{verdict.get('action') or verdict.get('label', 'HOLD')} {int((verdict.get('confidence') or 0) * 100)}%",
        'type': 'verdict',
        'score': verdict.get('confidence', 0.5),
        'action': verdict.get('action') or verdict.get('label', 'HOLD'),
    })
    edges.append({'source': 'brain13d', 'target': 'verdict', 'weight': brain.get('alignment_score', 0.5), 'label': 'aligns_with', 'layer': 'blue'})

    return {
        'run_id': run_id,
        'target': target,
        'layers': layers,
        'nodes': nodes,
        'edges': edges,
        'layout': 'layered',
        'schema_version': 2,
        'source': 'live_file_artifacts',
    }


def _build_report(run: dict[str, Any], graph: dict[str, Any]) -> str:
    verdict = run.get('verdict') or {}
    price = run.get('price_snapshot') or {}
    data_context = run.get('data_context') or {}
    source_lines = '\n'.join(f"- `{src}`" for src in data_context.get('source_files', [])[:20]) or '- No dedicated source file found'
    packets = data_context.get('source_packets') or []
    packet_lines = '\n'.join(
        f"- {p.get('source_type')}/{p.get('source')}: {p.get('title')} "
        f"(freshness={p.get('freshness')}, confidence={p.get('confidence')})"
        for p in packets[:12]
    ) or '- No source packets built'
    analyst_lines = '\n'.join(
        f"- {a.get('name')}: {a.get('stance') or a.get('verdict')} ({int((a.get('confidence') or 0) * 100)}%) - {a.get('role', '')}"
        for a in run.get('analysts', [])
    )
    return (
        f"# MiroFish Live Report: {run['target']}\n\n"
        f"- Run ID: `{run['id']}`\n"
        f"- Source: `{run.get('source')}`\n"
        f"- Symbol: `{run.get('symbol') or 'N/A'}`\n"
        f"- Price: `{price.get('price')}` KRW ({price.get('change_pct', 0)}%) as of `{price.get('date')}`\n"
        f"- Verdict: **{verdict.get('action') or verdict.get('label')} {int((verdict.get('confidence') or 0) * 100)}%**\n"
        f"- Graph nodes/edges: {len(graph.get('nodes', []))}/{len(graph.get('edges', []))}\n\n"
        "## Data Sources\n\n"
        f"{source_lines}\n\n"
        "## Hybrid RAG Source Packets\n\n"
        f"{packet_lines}\n\n"
        "## Brain 13D\n\n"
        f"- Alignment: {run.get('brain_summary', {}).get('alignment_score')}\n"
        f"- Regime: {run.get('brain_summary', {}).get('regime')}\n"
        f"- Memory Window: {run.get('brain_summary', {}).get('memory_window')}\n\n"
        "## Analysts\n\n"
        f"{analyst_lines}\n\n"
        "## CIO Reasoning\n\n"
        f"{(run.get('cio') or {}).get('final_answer', {}).get('reasoning', '')}\n\n"
        "## Summary\n\n"
        f"{verdict.get('summary', '')}\n"
    )


def _brain_summary(target: str) -> dict[str, Any]:
    try:
        from app.services.mirofish.brain_loader import load_brain_13d_snapshot
        snapshot = load_brain_13d_snapshot(target)
        return {
            'name': snapshot['name'],
            'target': snapshot['target'],
            'dimensions': list(snapshot['dimensions'].keys()),
            'dimension_scores': {
                k: {'score': v.get('score'), 'confidence': v.get('confidence'), 'evidence': v.get('evidence'), 'source': v.get('source')}
                for k, v in snapshot['dimensions'].items()
            },
            'alignment_score': snapshot['alignment_score'],
            'regime': snapshot['regime'],
            'memory_window': snapshot['memory_window'],
            'snapshot_at': snapshot['snapshot_at'],
            'sources': snapshot['sources'],
            'notes': snapshot['notes'],
        }
    except Exception as exc:
        return {
            'name': 'MiroFish Brain 13D',
            'target': target,
            'dimensions': [],
            'dimension_scores': {},
            'alignment_score': 0.0,
            'regime': 'data_unavailable',
            'memory_window': 'unavailable',
            'notes': f'Brain loader unavailable ({type(exc).__name__}).',
        }


def _frontend_brain(brain: dict[str, Any]) -> dict[str, Any]:
    alignment = brain.get('alignment_score', 0)
    score = int(round(float(alignment or 0) * 100)) if float(alignment or 0) <= 1 else int(round(float(alignment or 0)))
    return {'score': score, 'regime': brain.get('regime', 'neutral'), 'crisis': _crisis_label(score)}


def _crisis_label(score: int) -> str:
    if score >= 70:
        return 'Lv.1'
    if score >= 45:
        return 'Lv.2'
    if score >= 25:
        return 'Lv.3'
    return 'Lv.4'


def _analysts_from_debate(debate: dict[str, Any], agent_count: int, brain: dict[str, Any]) -> list[dict[str, Any]]:
    messages = []
    for round_item in reversed(debate.get('rounds', []) or []):
        messages = round_item.get('messages', []) or []
        if messages:
            break

    analysts: list[dict[str, Any]] = []
    icons = ['fa-shield-halved', 'fa-chart-line', 'fa-calculator', 'fa-bolt', 'fa-briefcase', 'fa-brain', 'fa-coins', 'fa-water', 'fa-compass', 'fa-link']
    for idx, msg in enumerate(messages[:agent_count]):
        stance = msg.get('stance', 'HOLD')
        analysts.append({
            'id': msg.get('agent_id') or f'agent_{idx + 1:02d}',
            'name': msg.get('agent_name') or f'Agent {idx + 1}',
            'role': msg.get('role') or 'MiroFish analyst',
            'stance': stance,
            'verdict': _display_verdict(stance),
            'confidence': _clamp_float(msg.get('confidence', 0.5)),
            'message': msg.get('message', ''),
            'cited_dimensions': msg.get('cited_dimensions', []),
            'icon': icons[idx % len(icons)],
        })

    dim_items = [
        (name, dim) for name, dim in (brain.get('dimension_scores') or {}).items()
        if isinstance(dim, dict) and dim.get('score') is not None
    ]
    dim_items.sort(key=lambda item: item[1].get('confidence', 0), reverse=True)
    i = 0
    while len(analysts) < agent_count and dim_items:
        dim_name, dim = dim_items[i % len(dim_items)]
        score = float(dim.get('score') or 50)
        stance = 'BUY' if score >= 60 else 'SELL' if score <= 35 else 'HOLD'
        analysts.append({
            'id': f'dim_{_slug(dim_name)}',
            'name': dim_name.replace('_', ' ').title(),
            'role': f"Brain dimension reader - {dim.get('source', 'MarketFlow')}",
            'stance': stance,
            'verdict': _display_verdict(stance),
            'confidence': _clamp_float(dim.get('confidence', 0.55)),
            'message': str(dim.get('evidence', '')),
            'cited_dimensions': [dim_name],
            'icon': icons[len(analysts) % len(icons)],
        })
        i += 1
    return analysts[:agent_count]


def _verdict_from_cio(
    cio: dict[str, Any],
    debate: dict[str, Any],
    analysts: list[dict[str, Any]],
    target: str | None = None,
    *,
    symbol: str | None = None,
    market: str | None = None,
    reference_date: str | None = None,
) -> dict[str, Any]:
    """CIO final_answer + agent 합의를 운영 표준 verdict 객체로 변환.

    P0 #4: symbol/market/reference_date/target_display 4개 필드를 필수화한다.
    호출자는 candidate 또는 run 의 created_at 에서 명시적으로 넘긴다.
    누락 시 sentinel 값 + 경고 로깅 (KeyError 던지지 않음 — 하위 호환).
    """
    final = cio.get('final_answer') or {}
    analysis_status = str(cio.get('analysis_status') or 'SUCCESS_PRIMARY')
    action = str(final.get('action') or debate.get('final_consensus', {}).get('action') or 'HOLD').upper()
    if analysis_status == 'HOLD_REVIEW':
        action = 'HOLD_REVIEW'
    elif action not in {'BUY', 'SELL', 'HOLD'}:
        action = 'HOLD'
    confidence = _clamp_float(final.get('confidence', debate.get('final_consensus', {}).get('confidence', 0.5)))
    bullish = sum(1 for a in analysts if a.get('stance') == 'BUY')
    bearish = sum(1 for a in analysts if a.get('stance') == 'SELL')
    neutral = max(0, len(analysts) - bullish - bearish)
    target_label = str(target or '').strip()
    summary_subject = f" for {target_label}" if target_label else ''

    # P0 #4: 종목 식별 + 분석 기준일 필수화
    symbol_clean = str(symbol or '').strip()
    market_clean = str(market or '').strip()
    ref_date_clean = str(reference_date or '').strip()
    if not symbol_clean or not market_clean or not ref_date_clean or not target_label:
        # 4개 필드 누락 → 경고만 로깅, verdict 생성 자체는 진행 (하위 호환)
        missing_fields = [
            name for name, val in (
                ('symbol', symbol_clean),
                ('market', market_clean),
                ('reference_date', ref_date_clean),
                ('target', target_label),
            ) if not val
        ]
        _log.warning(
            'mirofish._verdict_from_cio missing identity fields: %s '
            '(target=%s symbol=%s market=%s reference_date=%s)',
            missing_fields, target_label, symbol_clean, market_clean, ref_date_clean,
        )

    # target_display: UI/Telegram 표시 — "이름 (CODE MARKET)" 패턴
    if symbol_clean and market_clean and target_label:
        target_display = f"{target_label} ({symbol_clean} {market_clean})"
    elif symbol_clean and target_label:
        target_display = f"{target_label} ({symbol_clean})"
    else:
        target_display = target_label or symbol_clean or '(unknown target)'

    return {
        'action': action,
        'label': action,
        'target': target_label or None,
        'confidence': confidence,
        'confidence_pct': int(round(confidence * 100)),
        'bullish': bullish,
        'bearish': bearish,
        'neutral': neutral,
        'horizon': '1M',
        'allocation_pct': final.get('allocation_pct', 0),
        'summary': (
            f"Live CIO verdict{summary_subject}: {action} with {int(round(confidence * 100))}% confidence. "
            f"Agent split: bull {bullish}, neutral {neutral}, bear {bearish}."
        ),
        'reasoning': final.get('reasoning', ''),
        'opposing_scenario': final.get('opposing_scenario', ''),
        # ── P0 #4 추가 필드 (하위 호환 — 기존 키는 모두 유지) ───────────────
        'symbol': symbol_clean or None,
        'market': market_clean or None,
        'reference_date': ref_date_clean or None,
        'target_display': target_display,
        'analysis_status': analysis_status,
        'rule_candidate_verdict': cio.get('rule_candidate_verdict'),
    }


def _logs(target: str, context: dict[str, Any], extracted: dict[str, Any], merge_stats: dict[str, Any],
          debate: dict[str, Any], cio: dict[str, Any], verdict: dict[str, Any]) -> list[dict[str, Any]]:
    now = datetime.now().strftime('%H:%M:%S')
    price = context.get('price') or {}
    kis = context.get('kis') or {}
    kis_text = 'KIS API 연결' if kis.get('found') else 'KIS API 대기'
    return [
        {'level': 'info', 'phase': 'intake', 'time': now, 'message': f"Accepted live target {target}.", 'text': f"대상 입력: {target}"},
        {'level': 'info', 'phase': 'intake', 'time': now, 'message': f"Resolved sources: {len(context.get('source_files', []))}.", 'text': f"실데이터 소스 {len(context.get('source_files', []))}개 연결"},
        {'level': 'info', 'phase': 'intake', 'time': now, 'message': f"KIS source found={bool(kis.get('found'))}.", 'text': kis_text},
        {'level': 'info', 'phase': 'brain_snapshot', 'time': now, 'message': 'Loaded Brain 13D from MarketFlow artifacts.', 'text': 'Brain 13D 실데이터 스냅샷 적재'},
        {'level': 'info', 'phase': 'graph_build', 'time': now, 'message': f"GraphRAG extracted {len(extracted.get('entities', []))} entities and {len(extracted.get('relations', []))} relations.", 'text': f"GraphRAG 인과 {merge_stats.get('total_relations', 0)}개 연결"},
        {'level': 'info', 'phase': 'analyst_mesh', 'time': now, 'message': f"Debate method={debate.get('method')}.", 'text': f"에이전트 토론 완료: {debate.get('method')}"},
        {'level': 'info', 'phase': 'verdict', 'time': now, 'message': f"CIO verdict={verdict.get('action')} confidence={verdict.get('confidence_pct')}%.", 'text': f"최종 판정: {verdict.get('action')} {verdict.get('confidence_pct')}%"},
        {'level': 'info', 'phase': 'report', 'time': now, 'message': f"Price snapshot {price.get('price')} ({price.get('date')}).", 'text': f"가격 스냅샷: {price.get('price')} KRW / {price.get('date')}"},
    ]


def _layers(graph_count: int, analyst_count: int, prediction_count: int, verdict_ready: bool) -> list[dict[str, Any]]:
    return [
        {'label': 'TARGET', 'count': 1, 'color': 'bg-red-500'},
        {'label': 'CAUSAL HISTORY', 'count': graph_count, 'color': 'bg-blue-500'},
        {'label': 'AI ANALYSTS', 'count': analyst_count, 'color': 'bg-violet-500'},
        {'label': 'PREDICTIONS', 'count': prediction_count, 'color': 'bg-orange-400'},
        {'label': 'VERDICT', 'count': 1 if verdict_ready else 0, 'color': 'bg-emerald-400'},
    ]


def _phase_states(current_phase: str, percent: int, *, completed: bool = False) -> list[dict[str, Any]]:
    current_index = _phase_index(current_phase)
    states = []
    for idx, phase in enumerate(PIPELINE_PHASES):
        if completed or idx < current_index:
            status = 'completed'
            progress = 1.0
        elif idx == current_index:
            status = 'completed' if completed else 'running'
            progress = 1.0 if completed else max(0.05, min(0.98, percent / 100))
        else:
            status = 'pending'
            progress = 0.0
        states.append({**phase, 'status': status, 'progress': progress})
    return states


def _phase_index(phase_id: str) -> int:
    for idx, phase in enumerate(PIPELINE_PHASES):
        if phase['id'] == phase_id:
            return idx
    return 0


def _phase_label(phase_id: str) -> str:
    for phase in PIPELINE_PHASES:
        if phase['id'] == phase_id:
            return phase['label']
    return phase_id


def _completed_phase_count(phase_id: str, completed: bool) -> int:
    if completed:
        return len(PIPELINE_PHASES)
    return max(0, _phase_index(phase_id))


def _artifact_links(run_id: str) -> dict[str, str]:
    return {
        'run': f'/api/admin/mirofish/runs/{run_id}',
        'graph': f'/api/admin/mirofish/runs/{run_id}/graph',
        'report': f'/api/admin/mirofish/runs/{run_id}/report',
        'events': f'/api/admin/mirofish/runs/{run_id}/events',
    }


def _running_report(run: dict[str, Any]) -> str:
    return (
        f"# MiroFish Run In Progress: {run.get('target')}\n\n"
        f"- Run ID: `{run.get('id')}`\n"
        f"- Status: `{run.get('status')}`\n"
        f"- Progress: `{(run.get('progress') or {}).get('percent', 0)}%`\n"
    )


def _append_run_event(run_id: str, level: str, phase: str, message: str, *,
                      text: str | None = None, progress: int | None = None,
                      elapsed_ms: int | None = None,
                      payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.services.mirofish import events as mf_events
    event_payload = dict(payload or {})
    if text is not None:
        event_payload['text'] = text
    if progress is not None:
        event_payload['progress'] = progress
    if elapsed_ms is not None:
        event_payload['elapsed_ms'] = elapsed_ms
    event_payload['time'] = datetime.now().strftime('%H:%M:%S')
    return mf_events.append_event(run_id, level, phase, message, payload=event_payload)


def _event_to_log(event: dict[str, Any], text: str | None = None) -> dict[str, Any]:
    payload = event.get('payload') or {}
    return {
        'level': event.get('level', 'info'),
        'phase': event.get('phase', 'run'),
        'time': payload.get('time') or datetime.now().strftime('%H:%M:%S'),
        'message': event.get('message', ''),
        'text': text or payload.get('text') or event.get('message', ''),
    }


def _record_phase_duration(run: dict[str, Any], phase_id: str, phase_started: float) -> None:
    perf = run.setdefault('performance', {})
    durations = perf.setdefault('phase_durations_ms', {})
    durations[phase_id] = int((time.perf_counter() - phase_started) * 1000)


def _mark_run_failed(run_id: str, exc: Exception) -> None:
    try:
        run = read_run(run_id) or {'id': run_id, 'target': 'unknown', 'created_at': datetime.now(timezone.utc).isoformat()}
        now = datetime.now(timezone.utc).isoformat()
        run['status'] = 'failed'
        run['completed_at'] = now
        run['pipeline'] = {**(run.get('pipeline') or {}), 'status': 'failed'}
        run['progress'] = {
            **(run.get('progress') or {}),
            'percent': (run.get('progress') or {}).get('percent', 0),
            'updated_at': now,
            'error': f'{type(exc).__name__}: {exc}',
        }
        event = _append_run_event(
            run_id,
            'error',
            str((run.get('progress') or {}).get('current_phase') or 'run'),
            f'MiroFish run failed: {type(exc).__name__}: {exc}',
            text=f'실행 실패: {type(exc).__name__}',
            payload={'error': str(exc)},
        )
        run.setdefault('logs', []).append(_event_to_log(event))
        write_json_atomic(os.path.join(_run_dir(run_id), 'run.json'), run, sort_keys=False)
    except Exception:
        return


def _graph_nodes_from_extraction(extracted: dict[str, Any], resolved: dict[str, Any]) -> list[dict[str, Any]]:
    entities = extracted.get('entities') or []
    if not entities:
        return [{'label': resolved.get('display_name') or 'target', 'x': 30, 'y': 38, 'kind': 'history'}]
    coords = [
        (35, 42), (42, 38), (50, 40), (58, 37), (66, 43), (72, 48), (62, 54), (53, 57),
        (44, 55), (36, 59), (29, 50), (77, 56), (69, 62), (48, 64), (40, 68),
    ]
    nodes = []
    for idx, entity in enumerate(entities[:24]):
        x, y = coords[idx % len(coords)]
        if idx >= len(coords):
            y = min(72, y + 8)
        nodes.append({'label': str(entity.get('name') or entity.get('id')), 'x': x, 'y': y, 'kind': 'history'})
    return nodes


def _prediction_nodes(analysts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    xs = [38, 44, 50, 56, 62, 68, 74, 34, 80, 46, 58, 70, 82, 30, 52]
    nodes = []
    for idx, analyst in enumerate(analysts[:MAX_AGENT_COUNT]):
        stance = analyst.get('stance', 'HOLD')
        nodes.append({
            'label': f"{analyst.get('name')} {stance}",
            'x': xs[idx % len(xs)],
            'y': 67 + ((idx % 3) * 5),
            'kind': 'prediction',
            'verdict': 'bull' if stance == 'BUY' else 'bear' if stance == 'SELL' else 'neutral',
        })
    return nodes


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': run.get('id'),
        'target': run.get('target'),
        'display_name': run.get('display_name'),
        'symbol': run.get('symbol'),
        'mode': run.get('mode'),
        'source': run.get('source'),
        'status': run.get('status'),
        'created_at': run.get('created_at'),
        'agent_count': len(run.get('analysts', [])),
        'price': run.get('price'),
        'change_pct': run.get('change_pct'),
        'verdict': run.get('verdict'),
    }


def _write_events(run_id: str, logs: list[dict[str, Any]]) -> None:
    try:
        from app.services.mirofish import events as mf_events
        for log in logs:
            mf_events.append_event(
                run_id,
                str(log.get('level', 'info')),
                str(log.get('phase', 'run')),
                str(log.get('message') or log.get('text') or ''),
                payload={'text': log.get('text'), 'time': log.get('time')},
            )
    except Exception:
        return


def _clean_target(value: Any) -> str:
    target = str(value or '').strip()
    if not target:
        raise ValueError('target is required')
    if len(target) > 80:
        raise ValueError('target must be 80 characters or fewer')
    return target


def _async_requested(payload: dict[str, Any]) -> bool:
    value = payload.get('async', payload.get('background', payload.get('stream')))
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def _clean_agent_count(value: Any) -> int:
    if value in (None, ''):
        return 10
    try:
        agent_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('agent_count must be an integer') from exc
    if agent_count < 1 or agent_count > MAX_AGENT_COUNT:
        raise ValueError(f'agent_count must be between 1 and {MAX_AGENT_COUNT}')
    return agent_count


def _clean_mode(value: Any) -> str:
    mode = str(value or 'full').strip().lower()
    if not re.fullmatch(r'[a-z0-9_-]{1,32}', mode):
        raise ValueError('mode must contain only letters, numbers, underscores, or hyphens')
    return mode


def _use_llm(mode: str) -> bool:
    if mode in {'fast', 'rule', 'local', 'no-llm'}:
        return False
    flag = os.getenv('MIROFISH_USE_LLM', '1').strip().lower()
    return flag not in {'0', 'false', 'no', 'off'}


def _run_id(target: str, agent_count: int, mode: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', target.lower()).strip('-')[:32] or 'target'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    digest = hashlib.sha256(f'{target}|{agent_count}|{mode}|{stamp}|{os.getpid()}'.encode('utf-8')).hexdigest()[:8]
    return f'mf_{slug}_{stamp}_{digest}'


def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,140}', run_id or ''):
        raise ValueError('invalid run_id')
    return run_id


def _run_dir(run_id: str) -> str:
    root = os.path.abspath(RUNS_ROOT)
    path = os.path.abspath(os.path.join(root, run_id))
    if os.path.commonpath([root, path]) != root:
        raise ValueError('invalid run_id')
    return path


def _read_json(path: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(5):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (PermissionError, OSError, json.JSONDecodeError) as exc:
            last_exc = exc
            if attempt == 4:
                break
            time.sleep(0.02 * (attempt + 1))
    if last_exc:
        raise last_exc
    raise FileNotFoundError(path)


def _write_text_atomic(path: str, content: str) -> None:
    tmp_path = f'{path}.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)


def _display_verdict(stance: str) -> str:
    if stance == 'BUY':
        return 'BULLISH'
    if stance == 'SELL':
        return 'BEARISH'
    return 'NEUTRAL'


def _clamp_float(value: Any, fallback: float = 0.5) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = fallback
    return max(0.0, min(1.0, number))


def _slug(value: Any) -> str:
    return re.sub(r'[^a-zA-Z0-9가-힣_]+', '_', str(value or '').strip()).strip('_').lower()
