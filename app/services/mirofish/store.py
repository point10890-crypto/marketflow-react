"""File-backed deterministic mock runs for the admin MiroFish MVP."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'runs')
MAX_AGENT_COUNT = 13


PIPELINE_PHASES = [
    {'id': 'intake', 'label': 'Target Intake', 'status': 'ready'},
    {'id': 'brain_snapshot', 'label': 'Brain 13D Snapshot', 'status': 'ready'},
    {'id': 'analyst_mesh', 'label': 'Analyst Mesh', 'status': 'ready'},
    {'id': 'graph_build', 'label': 'Graph Build', 'status': 'ready'},
    {'id': 'verdict', 'label': 'Verdict Synthesis', 'status': 'ready'},
    {'id': 'report', 'label': 'Markdown Report', 'status': 'ready'},
]


def get_status() -> dict[str, Any]:
    os.makedirs(RUNS_ROOT, exist_ok=True)
    return {
        'service': 'admin-mirofish',
        'ready': True,
        'mode': 'deterministic_mock',
        'storage': {
            'type': 'filesystem',
            'path': os.path.relpath(RUNS_ROOT, REPO_ROOT).replace('\\', '/'),
        },
        'brain_summary': _brain_summary('MiroFish'),
        'pipeline_phases': PIPELINE_PHASES,
        'limits': {
            'max_agent_count': MAX_AGENT_COUNT,
            'external_llm_required': False,
        },
    }


def create_run(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload or {}
    target = _clean_target(payload.get('target'))
    mode = _clean_mode(payload.get('mode'))
    agent_count = _clean_agent_count(payload.get('agent_count'))
    run_id = _run_id(target, agent_count, mode)

    run_dir = _run_dir(run_id)
    os.makedirs(run_dir, exist_ok=True)

    run = _build_run(run_id, target, agent_count, mode)
    graph = _build_graph(run)
    report = _build_report(run)

    write_json_atomic(os.path.join(run_dir, 'run.json'), run, sort_keys=True)
    write_json_atomic(os.path.join(run_dir, 'graph.json'), graph, sort_keys=True)
    _write_text_atomic(os.path.join(run_dir, 'report.md'), report)
    return run


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not os.path.isdir(RUNS_ROOT):
        return []

    runs: list[dict[str, Any]] = []
    for name in os.listdir(RUNS_ROOT):
        run_file = os.path.join(RUNS_ROOT, name, 'run.json')
        if not os.path.isfile(run_file):
            continue
        try:
            run = _read_json(run_file)
        except (OSError, json.JSONDecodeError):
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
    return {
        'run_id': safe_id,
        'format': 'markdown',
        'markdown': markdown,
    }


def _build_run(run_id: str, target: str, agent_count: int, mode: str) -> dict[str, Any]:
    seed = _seed(target, agent_count, mode)
    created_at = _deterministic_timestamp(seed)
    analysts = _analysts(agent_count)
    completed = len(PIPELINE_PHASES)
    return {
        'id': run_id,
        'target': target,
        'mode': mode,
        'status': 'completed',
        'created_at': created_at,
        'completed_at': created_at,
        'deterministic': True,
        'seed': seed[:16],
        'brain_summary': _brain_summary(target),
        'pipeline_phases': [
            {**phase, 'status': 'completed', 'progress': 1.0}
            for phase in PIPELINE_PHASES
        ],
        'progress': {
            'completed_phases': completed,
            'total_phases': completed,
            'percent': 100,
        },
        'analysts': analysts,
        'verdict': {
            'action': 'BUY',
            'confidence': 0.64,
            'confidence_label': '64%',
            'risk': 'moderate',
            'time_horizon': 'swing',
            'summary': 'BUY 64%: mock consensus favors accumulation while keeping risk checks active.',
        },
        'logs': _logs(target, analysts),
        'artifacts': {
            'run': f'/api/admin/mirofish/runs/{run_id}',
            'graph': f'/api/admin/mirofish/runs/{run_id}/graph',
            'report': f'/api/admin/mirofish/runs/{run_id}/report',
        },
    }


def _build_graph(run: dict[str, Any]) -> dict[str, Any]:
    """3-Layer Knowledge Graph: Blue(EKG) / Red(LLM 추론) / Gold(최종 verdict).

    Layer scheme (MD 명세):
    - Blue (existing_ekg): 기존 사전 지식 — Brain 13D snapshot, target identity, signal categories
    - Red (llm_inferred): 본 run 에서 LLM(또는 mock)이 추론한 새 인과 관계 — analyst stances
    - Gold (verdict): 수렴된 최종 결론 — BUY/HOLD/SELL 판정 노드
    """
    target = run['target']
    run_id = run['id']
    brain = run.get('brain_summary', {})
    verdict = run.get('verdict', {})
    verdict_action = verdict.get('action', 'HOLD')
    verdict_conf = verdict.get('confidence', 0.5)

    layers = [
        {'id': 'blue', 'label': 'Existing Knowledge (EKG)', 'color': '#3b82f6',
         'order': 1, 'description': '사전 지식 — Brain 13D + target identity'},
        {'id': 'red', 'label': 'LLM-Inferred Causal Chains', 'color': '#ef4444',
         'order': 2, 'description': '본 run 에서 추론한 새 관계'},
        {'id': 'gold', 'label': 'Final Verdict Convergence', 'color': '#f59e0b',
         'order': 3, 'description': '수렴된 최종 결론'},
    ]

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # ─── Blue Layer (EKG) ─────────────────────────────────
    nodes.append({
        'id': 'target', 'layer': 'blue', 'label': target,
        'type': 'target', 'score': 1.0,
    })
    nodes.append({
        'id': 'brain13d', 'layer': 'blue', 'label': 'Brain 13D',
        'type': 'brain', 'score': brain.get('alignment_score', 0.5),
    })
    # 13개 dimension 각각 노드 — score 있는 것만 (clutter 방지: top 6)
    dim_scores = brain.get('dimension_scores', {}) if isinstance(brain.get('dimension_scores'), dict) else {}
    all_valid_dims = [(k, v) for k, v in dim_scores.items()
                      if isinstance(v, dict) and v.get('score') is not None]
    all_valid_dims.sort(key=lambda x: x[1].get('confidence', 0), reverse=True)
    visible_dims = all_valid_dims[:6]
    for dim_name, dim_data in visible_dims:
        score_norm = (dim_data.get('score') or 0) / 100.0
        nodes.append({
            'id': f'dim_{dim_name}', 'layer': 'blue',
            'label': dim_name.replace('_', ' ').title(),
            'type': 'dimension', 'score': round(score_norm, 2),
            'evidence': dim_data.get('evidence', '')[:80],
        })
        edges.append({
            'source': 'brain13d', 'target': f'dim_{dim_name}',
            'weight': dim_data.get('confidence', 0.5),
            'label': 'measures', 'layer': 'blue',
        })
    edges.append({
        'source': 'target', 'target': 'brain13d',
        'weight': 0.9, 'label': 'framed_by', 'layer': 'blue',
    })

    # ─── Red Layer (LLM-Inferred — analyst views as causal chains) ───
    for analyst in run.get('analysts', [])[:6]:
        analyst_id = analyst['id']
        nodes.append({
            'id': analyst_id, 'layer': 'red',
            'label': analyst['name'],
            'type': 'analyst', 'score': analyst.get('confidence', 0.5),
            'stance': analyst.get('stance', 'NEUTRAL'),
        })
        # 각 analyst → 가장 관련된 dimension 으로 edge (visible_dims 만 참조)
        if visible_dims:
            target_dim = visible_dims[hash(analyst_id) % len(visible_dims)][0]
            edges.append({
                'source': analyst_id, 'target': f'dim_{target_dim}',
                'weight': analyst.get('confidence', 0.5),
                'label': analyst.get('stance', 'evaluates').lower(),
                'layer': 'red',
            })

    # ─── Gold Layer (Final Verdict) ──────────────────────────
    verdict_id = 'verdict'
    nodes.append({
        'id': verdict_id, 'layer': 'gold',
        'label': f'{verdict_action} {int(verdict_conf * 100)}%',
        'type': 'verdict', 'score': verdict_conf,
        'action': verdict_action,
    })
    # Gold 는 모든 analyst 의견을 수렴
    for analyst in run.get('analysts', [])[:6]:
        edges.append({
            'source': analyst['id'], 'target': verdict_id,
            'weight': analyst.get('confidence', 0.5),
            'label': analyst.get('stance', 'votes').lower(),
            'layer': 'red',  # analyst → verdict 도 추론 관계
        })
    # Brain 도 verdict 직접 영향 (Blue → Gold)
    edges.append({
        'source': 'brain13d', 'target': verdict_id,
        'weight': brain.get('alignment_score', 0.5),
        'label': 'aligns_with', 'layer': 'blue',
    })

    return {
        'run_id': run_id,
        'target': target,
        'layers': layers,
        'nodes': nodes,
        'edges': edges,
        'layout': 'layered',
        'schema_version': 2,  # Phase 2B
    }


def _build_report(run: dict[str, Any]) -> str:
    analyst_lines = '\n'.join(
        f"- {a['name']}: {a['stance']} ({int(a['confidence'] * 100)}%) - {a['note']}"
        for a in run['analysts']
    )
    phase_lines = '\n'.join(
        f"- {phase['label']}: {phase['status']}"
        for phase in run['pipeline_phases']
    )
    brain = run['brain_summary']
    return (
        f"# MiroFish Mock Report: {run['target']}\n\n"
        f"- Run ID: `{run['id']}`\n"
        f"- Mode: `{run['mode']}`\n"
        f"- Verdict: **{run['verdict']['action']} {run['verdict']['confidence_label']}**\n"
        f"- Risk: {run['verdict']['risk']}\n\n"
        "## Brain 13D Snapshot\n\n"
        f"- Dimensions: {brain['dimensions']}\n"
        f"- Alignment: {brain['alignment_score']}\n"
        f"- Regime: {brain['regime']}\n"
        f"- Memory Window: {brain['memory_window']}\n\n"
        "## Pipeline\n\n"
        f"{phase_lines}\n\n"
        "## Analysts\n\n"
        f"{analyst_lines}\n\n"
        "## Summary\n\n"
        "Deterministic local mock output. No external LLM, broker, or market data key was used.\n"
    )


def _brain_summary(target: str) -> dict[str, Any]:
    """Brain 13D 스냅샷 — 실데이터 우선, 실패 시 결정론적 fallback."""
    try:
        from app.services.mirofish.brain_loader import load_brain_13d_snapshot
        snapshot = load_brain_13d_snapshot(target)
        # 핵심 필드만 유지 (run.json 크기 통제)
        return {
            'name': snapshot['name'],
            'target': snapshot['target'],
            'dimensions': list(snapshot['dimensions'].keys()),
            'dimension_scores': {
                k: {'score': v.get('score'), 'confidence': v.get('confidence'),
                    'evidence': v.get('evidence')}
                for k, v in snapshot['dimensions'].items()
            },
            'alignment_score': snapshot['alignment_score'],
            'regime': snapshot['regime'],
            'memory_window': snapshot['memory_window'],
            'snapshot_at': snapshot['snapshot_at'],
            'sources': snapshot['sources'],
            'notes': snapshot['notes'],
        }
    except Exception as e:
        # Fail-safe: 결정론적 fallback (테스트 + 데이터 누락 시)
        return {
            'name': 'MiroFish Brain 13D',
            'target': target,
            'dimensions': [
                'sector_momentum', 'macro_regime', 'options_flow', 'earnings_catalyst',
                'event_risk', 'ml_prediction', 'reversal_signal', 'crypto_sentiment',
                'correlation_stability', 'liquidity', 'volatility', 'memory_window',
                'narrative',
            ],
            'alignment_score': 0.64,
            'regime': 'constructive_accumulation',
            'memory_window': 'fallback_mock',
            'notes': f'Brain loader unavailable ({type(e).__name__}); using deterministic fallback.',
        }


def _analysts(agent_count: int) -> list[dict[str, Any]]:
    base = [
        ('agent_01', 'Trend Cartographer', 'BUY', 0.68, 'Higher-low structure remains intact.'),
        ('agent_02', 'Volume Diver', 'BUY', 0.63, 'Accumulation flow is positive but not euphoric.'),
        ('agent_03', 'Risk Sentinel', 'HOLD', 0.55, 'Position sizing should respect moderate drawdown risk.'),
        ('agent_04', 'Momentum Scout', 'BUY', 0.66, 'Momentum is improving from a controlled base.'),
        ('agent_05', 'Macro Lens', 'HOLD', 0.52, 'Macro backdrop is neutral enough for selective exposure.'),
        ('agent_06', 'Sentiment Reader', 'BUY', 0.61, 'Sentiment is constructive without crowding.'),
        ('agent_07', 'Liquidity Mapper', 'BUY', 0.65, 'Liquidity supports clean entry and exit paths.'),
        ('agent_08', 'Correlation Guard', 'HOLD', 0.57, 'Correlation pressure is manageable.'),
        ('agent_09', 'Quality Auditor', 'BUY', 0.64, 'Quality checks pass the mock threshold.'),
        ('agent_10', 'Timing Weaver', 'BUY', 0.67, 'Timing favors staged accumulation.'),
        ('agent_11', 'Volatility Reader', 'HOLD', 0.56, 'Volatility needs a defined stop.'),
        ('agent_12', 'Sector Compass', 'BUY', 0.62, 'Sector context supports the idea.'),
        ('agent_13', 'Memory Keeper', 'BUY', 0.66, 'Historical analogs lean bullish.'),
    ]
    return [
        {
            'id': analyst_id,
            'name': name,
            'stance': stance,
            'confidence': confidence,
            'note': note,
        }
        for analyst_id, name, stance, confidence, note in base[:agent_count]
    ]


def _logs(target: str, analysts: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {'level': 'info', 'phase': 'intake', 'message': f'Accepted target {target}.'},
        {'level': 'info', 'phase': 'brain_snapshot', 'message': 'Loaded Brain 13D-ish deterministic snapshot.'},
        {'level': 'info', 'phase': 'analyst_mesh', 'message': f'Activated {len(analysts)} mock analysts.'},
        {'level': 'info', 'phase': 'graph_build', 'message': 'Built layered graph payload.'},
        {'level': 'info', 'phase': 'verdict', 'message': 'Synthesized BUY 64% verdict.'},
        {'level': 'info', 'phase': 'report', 'message': 'Rendered markdown report artifact.'},
    ]


def _summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': run.get('id'),
        'target': run.get('target'),
        'mode': run.get('mode'),
        'status': run.get('status'),
        'created_at': run.get('created_at'),
        'agent_count': len(run.get('analysts', [])),
        'verdict': run.get('verdict'),
    }


def _clean_target(value: Any) -> str:
    target = str(value or '').strip()
    if not target:
        raise ValueError('target is required')
    if len(target) > 80:
        raise ValueError('target must be 80 characters or fewer')
    return target


def _clean_agent_count(value: Any) -> int:
    if value in (None, ''):
        return MAX_AGENT_COUNT
    try:
        agent_count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('agent_count must be an integer') from exc
    if agent_count < 1 or agent_count > MAX_AGENT_COUNT:
        raise ValueError(f'agent_count must be between 1 and {MAX_AGENT_COUNT}')
    return agent_count


def _clean_mode(value: Any) -> str:
    mode = str(value or 'mock').strip().lower()
    if not re.fullmatch(r'[a-z0-9_-]{1,32}', mode):
        raise ValueError('mode must contain only letters, numbers, underscores, or hyphens')
    return mode


def _run_id(target: str, agent_count: int, mode: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', target.lower()).strip('-')[:32] or 'target'
    digest = _seed(target, agent_count, mode)[:12]
    return f'mf_{slug}_{digest}'


def _seed(target: str, agent_count: int, mode: str) -> str:
    raw = f'{target}|{agent_count}|{mode}'.encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def _deterministic_timestamp(seed: str) -> str:
    offset = int(seed[:8], 16) % (86400 * 120)
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return dt.isoformat().replace('+00:00', 'Z')


def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', run_id or ''):
        raise ValueError('invalid run_id')
    return run_id


def _run_dir(run_id: str) -> str:
    root = os.path.abspath(RUNS_ROOT)
    path = os.path.abspath(os.path.join(root, run_id))
    if os.path.commonpath([root, path]) != root:
        raise ValueError('invalid run_id')
    return path


def _read_json(path: str) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_text_atomic(path: str, content: str) -> None:
    tmp_path = f'{path}.tmp'
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp_path, 'w', encoding='utf-8') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, path)
