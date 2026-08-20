"""Read-only aggregation for the five-stage Alpha Service Clock."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import math
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.services.mirofish import alpha_scanner, paper_orchestrator, pipeline_overview


KST = ZoneInfo('Asia/Seoul')
SCHEMA_VERSION = 'mirofish.alpha_service_dashboard.v1'
STALE_AFTER_CALENDAR_DAYS = 3
logger = logging.getLogger(__name__)


def _current_kst(now: datetime | None) -> datetime:
    current = now or datetime.now(KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST)


def _point_schedule(current: datetime, hour: int, minute: int, label: str) -> dict[str, Any]:
    start = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    phase = 'upcoming' if current < start else 'due' if current < start + timedelta(minutes=15) else 'elapsed'
    return {
        'label': label,
        'time_kst': f'{hour:02d}:{minute:02d}',
        'phase': phase,
        'calendar_status': 'unverified',
    }


def _intraday_schedule(current: datetime) -> dict[str, Any]:
    start = current.replace(hour=9, minute=0, second=0, microsecond=0)
    end = current.replace(hour=15, minute=30, second=0, microsecond=0)
    phase = 'upcoming' if current < start else 'due' if current < end else 'elapsed'
    return {
        'label': '장중',
        'time_kst': None,
        'phase': phase,
        'calendar_status': 'unverified',
    }


def _source(
    source: str,
    *,
    run_id: str | None = None,
    as_of: str | None = None,
    freshness: str = 'fresh',
    fallback: bool = False,
) -> dict[str, Any]:
    return {
        'source': source,
        'run_id': run_id,
        'as_of': as_of,
        'freshness': freshness,
        'fallback': fallback,
    }


def _is_stale_as_of(value: Any, current: datetime) -> bool:
    as_of = _as_kst_date(value)
    if as_of is None:
        return True
    return (current.date() - as_of).days > STALE_AFTER_CALENDAR_DAYS


def _as_kst_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        if len(text) == 10:
            return date.fromisoformat(text)
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).date()


def _is_current_kst_day(value: Any, current: datetime) -> bool:
    return _as_kst_date(value) == current.date()


def _safe_read(
    name: str,
    reader: Callable[[], Any],
    warnings: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        return {'ok': True, 'data': reader(), 'error': None}
    except Exception as exc:
        logger.exception('alpha dashboard source read failed: %s', name)
        warnings.append({
            'section': name,
            'code': 'source_read_failed',
            'message': f'{name} 데이터를 읽지 못했습니다.',
            'severity': 'error',
        })
        return {'ok': False, 'data': None, 'error': type(exc).__name__}


def _source_warnings(
    warnings: list[dict[str, Any]],
    source_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    return [
        dict(warning)
        for warning in warnings
        if warning.get('section') in source_names
    ]


def _mapping_source_data(
    name: str,
    read: dict[str, Any],
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
    *,
    allow_none: bool = False,
) -> dict[str, Any] | None:
    data = read.get('data')
    if not read.get('ok'):
        return None if allow_none else {}
    if data is None and allow_none:
        return None
    if isinstance(data, dict):
        return data
    degraded_sources.add(name)
    warnings.append({
        'section': name,
        'code': 'source_data_invalid',
        'message': f'{name} 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    })
    return None if allow_none else {}


def _mark_source_invalid(
    name: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> None:
    degraded_sources.add(name)
    if any(
        warning.get('section') == name and warning.get('code') == 'source_data_invalid'
        for warning in warnings
    ):
        return
    warnings.append({
        'section': name,
        'code': 'source_data_invalid',
        'message': f'{name} 데이터 형식이 올바르지 않습니다.',
        'severity': 'error',
    })


def _append_source_warning(
    source: str,
    code: str,
    message: str,
    severity: str,
    warnings: list[dict[str, Any]],
) -> None:
    if any(
        warning.get('section') == source and warning.get('code') == code
        for warning in warnings
    ):
        return
    warnings.append({
        'section': source,
        'code': code,
        'message': message,
        'severity': severity,
    })


def _safe_float(
    value: Any,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> float | None:
    if isinstance(value, bool):
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    if not math.isfinite(parsed):
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    return parsed


def _safe_number(
    value: Any,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> int | float | None:
    if isinstance(value, dict):
        value = value.get('value')
    if value is None:
        return None
    if isinstance(value, bool):
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    parsed = _safe_float(value, source, warnings, degraded_sources)
    return parsed


def _safe_count(
    value: Any,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
    *,
    default: int | None = 0,
) -> int | None:
    if value is None:
        return default
    parsed = _safe_number(value, source, warnings, degraded_sources)
    if parsed is None:
        return None
    if float(parsed).is_integer() and parsed >= 0:
        return int(parsed)
    _mark_source_invalid(source, warnings, degraded_sources)
    return None


def _safe_date_string(
    value: Any,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    normalized = _as_kst_date(value)
    if normalized is None:
        _mark_source_invalid(source, warnings, degraded_sources)
        return None
    return normalized.isoformat()


def _mapping_field(
    payload: dict[str, Any],
    key: str,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
) -> dict[str, Any]:
    value = payload.get(key)
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    _mark_source_invalid(source, warnings, degraded_sources)
    return {}


def _list_field(
    payload: dict[str, Any],
    key: str,
    source: str,
    warnings: list[dict[str, Any]],
    degraded_sources: set[str],
    *,
    mapping_items: bool = False,
) -> list[Any]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        _mark_source_invalid(source, warnings, degraded_sources)
        return []
    if not mapping_items:
        return value
    mappings = [item for item in value if isinstance(item, dict)]
    if len(mappings) != len(value):
        _mark_source_invalid(source, warnings, degraded_sources)
    return mappings


def _build_services(
    current: datetime,
    phase: dict[str, Any],
    schedule: dict[str, Any],
    leaders: dict[str, Any] | None,
    paper: dict[str, Any],
    pipeline: dict[str, Any],
    outcomes: dict[str, Any],
    failed_sources: set[str],
    source_warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    phase_as_of = phase.get('as_of')
    phase_stale = _is_stale_as_of(phase_as_of, current)
    regime = phase.get('regime')
    market_metrics = [{
        'key': 'regime', 'label': '시장 레짐', 'value': regime,
        'unit': None,
        'tone': (
            'positive' if regime == 'RISK_ON'
            else 'negative' if regime == 'RISK_OFF'
            else 'neutral' if regime == 'NEUTRAL'
            else 'warning'
        ),
    }]
    if phase.get('breadth') is not None:
        breadth = _safe_float(
            phase.get('breadth'), 'market_phase', source_warnings, failed_sources,
        )
        market_metrics.append({
            'key': 'breadth', 'label': '시장 폭',
            'value': round(breadth * 100, 1) if breadth is not None else None,
            'unit': '%', 'tone': 'neutral',
        })
    if phase.get('breadth_change_5d') is not None:
        breadth_change = _safe_float(
            phase.get('breadth_change_5d'),
            'market_phase',
            source_warnings,
            failed_sources,
        )
        market_metrics.append({
            'key': 'breadth_change_5d', 'label': '5일 시장 폭 변화',
            'value': round(breadth_change * 100, 1) if breadth_change is not None else None,
            'unit': '%p', 'tone': 'neutral',
        })
    market = {
        'id': 'market_brief', 'order': 1, 'title': '전일 시장 정리',
        'description': '시장 국면과 시장 폭을 확인합니다.',
        'schedule': _point_schedule(current, 8, 0, '오전 8시'),
        'data_status': (
            'partial' if 'market_phase' in failed_sources
            else 'stale' if phase_stale else 'ready'
        ),
        'as_of': phase_as_of,
        'summary': phase.get('phase_label') or phase.get('phase') or '시장 국면 데이터 없음',
        'metrics': market_metrics, 'items': [],
        'warnings': _source_warnings(source_warnings, ('market_phase',)) + [{
            'section': 'market_brief', 'code': 'leading_sectors_unavailable',
            'message': '검증된 업종 분류 데이터가 없어 주도 업종을 표시하지 않습니다.',
            'severity': 'info',
        }],
        'provenance': {'sources': [_source(
            'market_phase',
            as_of=phase_as_of,
            freshness='unknown' if not phase_as_of else 'stale' if phase_stale else 'fresh',
            fallback=not bool(phase_as_of),
        )]},
    }

    leader_payload = leaders or {}
    raw_candidates = _list_field(
        leader_payload,
        'candidates',
        'latest_nonempty_run',
        source_warnings,
        failed_sources,
        mapping_items=True,
    )
    candidate_items = []
    for candidate in raw_candidates:
        candidate_items.append({
            'rank': _safe_number(
                candidate.get('rank'),
                'latest_nonempty_run',
                source_warnings,
                failed_sources,
            ),
            'symbol': candidate.get('symbol'),
            'name': candidate.get('name') or candidate.get('display_name'),
            'market': candidate.get('market'),
            'alpha_score': _safe_number(
                candidate.get('alpha_score'),
                'latest_nonempty_run',
                source_warnings,
                failed_sources,
            ),
            'risk_score': _safe_number(
                candidate.get('risk_score'),
                'latest_nonempty_run',
                source_warnings,
                failed_sources,
            ),
            'action': candidate.get('action'),
            'horizon': candidate.get('horizon'),
            'price': _safe_number(
                candidate.get('price'),
                'latest_nonempty_run',
                source_warnings,
                failed_sources,
            ),
        })
    leader_generated_at = leader_payload.get('generated_at')
    leader_freshness_payload = _mapping_field(
        leader_payload,
        'freshness',
        'latest_nonempty_run',
        source_warnings,
        failed_sources,
    )
    leader_freshness = leader_freshness_payload.get('status') or 'unknown'
    effective_leader_freshness = (
        'stale' if _is_stale_as_of(leader_generated_at, current)
        else leader_freshness
    )
    score_leaders = {
        'id': 'score_leaders', 'order': 2, 'title': '알파스코어 상위 종목',
        'description': '최근 비어 있지 않은 스캔 후보입니다.',
        'schedule': _point_schedule(current, 8, 30, '오전 8시 30분'),
        'data_status': (
            'partial' if {'latest_nonempty_run', 'scanner_schedule'} & failed_sources
            else 'stale' if candidate_items and effective_leader_freshness not in {'fresh', 'ready', 'ok'}
            else 'ready' if candidate_items else 'empty'
        ),
        'as_of': leader_generated_at,
        'summary': f'{len(candidate_items)}개 후보' if candidate_items else '후보 데이터 없음',
        'metrics': [], 'items': candidate_items,
        'warnings': _source_warnings(
            source_warnings, ('scanner_schedule', 'latest_nonempty_run'),
        ),
        'provenance': {'sources': [
            _source(
                leader_payload.get('source') or 'latest_nonempty_run',
                run_id=leader_payload.get('run_id'),
                as_of=leader_generated_at,
                freshness=effective_leader_freshness,
            ),
            _source(
                'scanner_schedule',
                as_of=schedule.get('checked_at'),
                freshness=schedule.get('freshness_status') or 'unknown',
            ),
        ]},
    }

    paper_positions = _list_field(
        paper,
        'open_positions',
        'paper_overview',
        source_warnings,
        failed_sources,
        mapping_items=True,
    )
    paper_pending = _list_field(
        paper,
        'pending',
        'paper_overview',
        source_warnings,
        failed_sources,
        mapping_items=True,
    )
    performance = _mapping_field(
        paper,
        'performance',
        'paper_overview',
        source_warnings,
        failed_sources,
    )
    positions = []
    for position in paper_positions:
        last_close_date = _safe_date_string(
            position.get('last_close_date'),
            'paper_overview',
            source_warnings,
            failed_sources,
        )
        close_is_stale = _is_stale_as_of(last_close_date, current)
        positions.append({
            'symbol': position.get('symbol'), 'name': position.get('name'),
            'entry_price': _safe_number(
                position.get('entry_price'),
                'paper_overview',
                source_warnings,
                failed_sources,
            ),
            'last_close': _safe_number(
                position.get('last_close'),
                'paper_overview',
                source_warnings,
                failed_sources,
            ),
            'last_close_date': last_close_date,
            'unrealized_pct': (
                None if close_is_stale
                else _safe_number(
                    position.get('unrealized_pct'),
                    'paper_overview',
                    source_warnings,
                    failed_sources,
                )
            ),
            'held_trading_days': _safe_count(
                position.get('held_trading_days'),
                'paper_overview',
                source_warnings,
                failed_sources,
                default=None,
            ),
            'target_price': _safe_number(
                position.get('target_price'),
                'paper_overview',
                source_warnings,
                failed_sources,
            ),
            'stop_price': _safe_number(
                position.get('stop_price'),
                'paper_overview',
                source_warnings,
                failed_sources,
            ),
        })
    positions_stale = bool(positions) and any(
        _is_stale_as_of(item.get('last_close_date'), current) for item in positions
    )
    intraday = {
        'id': 'intraday_flow', 'order': 3, 'title': '장중 종목 흐름 체크',
        'description': '마지막 저장 종가 기준 포지션입니다.',
        'schedule': _intraday_schedule(current),
        'data_status': (
            'partial' if 'paper_overview' in failed_sources
            else 'stale' if positions_stale
            else 'ready' if positions else 'empty'
        ),
        'as_of': max((item.get('last_close_date') or '' for item in positions), default='') or None,
        'summary': f'{len(positions)}개 포지션' if positions else '보유 포지션 없음',
        'metrics': [], 'items': positions,
        'warnings': _source_warnings(source_warnings, ('paper_overview',)),
        'provenance': {'sources': [_source(
            'paper_overview',
            as_of=paper.get('generated_at'),
            freshness='stale' if positions_stale else 'fresh',
        )]},
    }

    pipeline_stages = _list_field(
        pipeline,
        'stages',
        'pipeline_operating_snapshot',
        source_warnings,
        failed_sources,
        mapping_items=True,
    )
    top_stage = next((stage for stage in pipeline_stages if stage.get('id') == 'top3'), None)
    if top_stage is None:
        if 'pipeline_operating_snapshot' not in failed_sources:
            _mark_source_invalid(
                'pipeline_operating_snapshot', source_warnings, failed_sources,
            )
        top_stage = {}
    top_stage_updated_at = top_stage.get('updated_at')
    top_stage_freshness = (
        'fresh' if _is_current_kst_day(top_stage_updated_at, current)
        else 'stale' if top_stage_updated_at else 'unknown'
    )
    paper_count = _safe_count(
        performance.get('trades'),
        'paper_overview',
        source_warnings,
        failed_sources,
    )
    paper_window_days = _safe_count(
        performance.get('window_days'),
        'paper_overview',
        source_warnings,
        failed_sources,
        default=None,
    )
    pipeline_top_count = _safe_count(
        top_stage.get('count'),
        'pipeline_operating_snapshot',
        source_warnings,
        failed_sources,
    )
    undated_nonzero_top3 = bool(pipeline_top_count and not top_stage_updated_at)
    if undated_nonzero_top3:
        _append_source_warning(
            'pipeline_operating_snapshot',
            'source_freshness_unknown',
            'pipeline TOP3 기준 시각을 확인할 수 없습니다.',
            'warning',
            source_warnings,
        )
    trade_items = [
        {'key': 'pending', 'label': '진입 대기', 'count': len(paper_pending), 'window_days': None, 'status': 'waiting'},
        {'key': 'open', 'label': '보유 중', 'count': len(paper_positions), 'window_days': None, 'status': 'active'},
        {'key': 'paper_30d_closed', 'label': '30일 완결 매매', 'count': paper_count, 'window_days': paper_window_days, 'status': 'complete'},
        {'key': 'pipeline_top3', 'label': '파이프라인 TOP3', 'count': pipeline_top_count, 'window_days': None, 'status': top_stage.get('status') or 'unknown'},
    ]
    trade_signals = {
        'id': 'trade_signals', 'order': 4, 'title': '당일 매매 신호',
        'description': '가상 매매와 파이프라인 상태입니다.',
        'schedule': _point_schedule(current, 15, 0, '오후 3시'),
        'data_status': (
            'partial'
            if {'paper_overview', 'pipeline_operating_snapshot'} & failed_sources
            else 'stale'
            if top_stage_freshness == 'stale' or undated_nonzero_top3
            else 'ready'
        ),
        'as_of': top_stage_updated_at,
        'summary': f"대기 {trade_items[0]['count']}건",
        'metrics': [], 'items': trade_items,
        'warnings': _source_warnings(
            source_warnings, ('paper_overview', 'pipeline_operating_snapshot'),
        ),
        'provenance': {'sources': [
            _source('paper_overview', as_of=paper.get('generated_at')),
            _source(
                'pipeline_operating_snapshot',
                run_id=pipeline.get('workflow_id'),
                as_of=top_stage_updated_at,
                freshness=top_stage_freshness,
            ),
        ]},
    }

    outcome_summary = _mapping_field(
        outcomes,
        'summary',
        'workflow_outcomes',
        source_warnings,
        failed_sources,
    )
    outcome_count = _safe_count(
        outcome_summary.get('evaluated_count'),
        'workflow_outcomes',
        source_warnings,
        failed_sources,
    )
    outcome_window_days = _safe_count(
        outcomes.get('window_days'),
        'workflow_outcomes',
        source_warnings,
        failed_sources,
        default=None,
    )
    performance_items = [
        {
            'source': 'paper_30d', 'sample_count': paper_count,
            'window_days': paper_window_days,
            'win_rate': _safe_number(
                performance.get('win_rate_pct'), 'paper_overview', source_warnings, failed_sources,
            ) if paper_count else None,
            'average_return_pct': _safe_number(
                performance.get('avg_return_pct'), 'paper_overview', source_warnings, failed_sources,
            ) if paper_count else None,
            'cumulative_return_pct': _safe_number(
                performance.get('cumulative_return_pct'),
                'paper_overview',
                source_warnings,
                failed_sources,
            ) if paper_count else None,
            'hit_count': None, 'miss_count': None,
        },
        {
            'source': 'workflow_outcomes', 'sample_count': outcome_count,
            'window_days': outcome_window_days,
            'win_rate': _safe_number(
                outcome_summary.get('hit_rate_pct'),
                'workflow_outcomes',
                source_warnings,
                failed_sources,
            ) if outcome_count else None,
            'average_return_pct': _safe_number(
                outcome_summary.get('avg_forward_return_pct'),
                'workflow_outcomes',
                source_warnings,
                failed_sources,
            ) if outcome_count else None,
            'cumulative_return_pct': None,
            'hit_count': _safe_count(
                outcome_summary.get('hit_count'),
                'workflow_outcomes',
                source_warnings,
                failed_sources,
                default=None,
            ),
            'miss_count': _safe_count(
                outcome_summary.get('miss_count'),
                'workflow_outcomes',
                source_warnings,
                failed_sources,
                default=None,
            ),
        },
    ]
    performance_sample_count = (paper_count or 0) + (outcome_count or 0)
    performance_brief = {
        'id': 'performance_brief', 'order': 5, 'title': '최근 성과 브리핑',
        'description': '두 성과 표본을 분리해 봅니다.',
        'schedule': _point_schedule(current, 18, 0, '오후 6시'),
        'data_status': (
            'partial' if {'paper_overview', 'workflow_outcomes'} & failed_sources
            else 'ready' if performance_sample_count else 'empty'
        ),
        'as_of': outcomes.get('generated_at') or paper.get('generated_at'),
        'summary': (
            f'성과 표본 {performance_sample_count}건'
            if performance_sample_count else '성과 표본 없음'
        ),
        'metrics': [], 'items': performance_items,
        'warnings': _source_warnings(
            source_warnings, ('paper_overview', 'workflow_outcomes'),
        ),
        'provenance': {'sources': [
            _source('paper_30d', as_of=paper.get('generated_at')),
            _source('workflow_outcomes', as_of=outcomes.get('generated_at')),
        ]},
    }
    return [market, score_leaders, intraday, trade_signals, performance_brief]


def get_alpha_service_dashboard(
    candidate_limit: int = 5,
    outcome_days: int = 30,
    outcome_limit: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Combine existing stored-data readers without triggering scans or writes."""
    current = _current_kst(now)
    warnings: list[dict[str, Any]] = []
    reads = {
        'market_phase': _safe_read('market_phase', paper_orchestrator.market_phase, warnings),
        'scanner_schedule': _safe_read(
            'scanner_schedule',
            lambda: alpha_scanner.get_scanner_schedule_status(now=current),
            warnings,
        ),
        'latest_nonempty_run': _safe_read(
            'latest_nonempty_run',
            lambda: alpha_scanner.read_latest_scanner_candidates(limit=candidate_limit),
            warnings,
        ),
        'paper_overview': _safe_read('paper_overview', paper_orchestrator.paper_overview, warnings),
        'pipeline_operating_snapshot': _safe_read(
            'pipeline_operating_snapshot',
            lambda: pipeline_overview.get_pipeline_operating_snapshot(now=current),
            warnings,
        ),
        'workflow_outcomes': _safe_read(
            'workflow_outcomes',
            lambda: pipeline_overview.get_outcomes_board(days=outcome_days, limit=outcome_limit),
            warnings,
        ),
    }
    failed_sources = {name for name, result in reads.items() if not result['ok']}
    phase = _mapping_source_data('market_phase', reads['market_phase'], warnings, failed_sources) or {}
    schedule = _mapping_source_data(
        'scanner_schedule', reads['scanner_schedule'], warnings, failed_sources,
    ) or {}
    leaders = _mapping_source_data(
        'latest_nonempty_run',
        reads['latest_nonempty_run'],
        warnings,
        failed_sources,
        allow_none=True,
    )
    paper = _mapping_source_data(
        'paper_overview', reads['paper_overview'], warnings, failed_sources,
    ) or {}
    pipeline = _mapping_source_data(
        'pipeline_operating_snapshot',
        reads['pipeline_operating_snapshot'],
        warnings,
        failed_sources,
    ) or {}
    outcomes = _mapping_source_data(
        'workflow_outcomes', reads['workflow_outcomes'], warnings, failed_sources,
    ) or {}
    services = _build_services(
        current,
        phase,
        schedule,
        leaders,
        paper,
        pipeline,
        outcomes,
        failed_sources,
        warnings,
    )
    has_core_data = bool(
        services[1]['items']
        or services[2]['items']
        or services[3]['items'][0]['count']
        or any(item['sample_count'] for item in services[4]['items'])
    )
    if failed_sources:
        status = 'partial'
    elif not has_core_data:
        status = 'empty'
    elif any(service['data_status'] == 'partial' for service in services):
        status = 'partial'
    elif any(service['data_status'] == 'stale' for service in services):
        status = 'stale'
    else:
        status = 'ready'
    return {
        'schema_version': SCHEMA_VERSION,
        'generated_at': current.isoformat(),
        'timezone': 'Asia/Seoul',
        'date_kst': current.date().isoformat(),
        'status': status,
        'services': services,
        'warnings': warnings,
        'links': {
            'scanner_latest': '/api/admin/mirofish/scanner/runs/latest',
            'outcomes_board': '/api/admin/mirofish/outcomes/board',
            'paper_overview': '/api/admin/mirofish/paper/overview',
            'pipeline_today': '/api/admin/mirofish/pipeline/today',
        },
    }
