"""Claw LIVE 읽기전용 API — /api/kr/claw/*

대시보드의 5초 폴링은 bounded 서버 projection을 사용한다. HTTP 캐시는 금지한다.
mutation 엔드포인트는 두지 않는다
(발송·스캔은 CLI/스케줄 전용).
"""
from flask import Blueprint, current_app, jsonify, request

from app.auth.decorators import admin_or_aibain_required, pro_or_kongming_required

kr_claw_bp = Blueprint('kr_claw', __name__)


@kr_claw_bp.record_once
def _init_projection(state):
    from marketflow_claw.http_projection import BoundedProjectionCache

    state.app.extensions['claw_http_projection'] = BoundedProjectionCache()


def _no_store(payload):
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


def _project(key, builder):
    result = current_app.extensions['claw_http_projection'].read(key, builder)
    payload = result.payload
    if payload is None:
        payload = {'error': 'claw_projection_' + result.metadata['state']}
    payload['projection'] = result.metadata
    resp = _no_store(payload)
    if result.payload is None:
        resp.status_code = 503
        resp.headers['Retry-After'] = str(result.metadata['retry_after_seconds'])
    return resp


def _overview_projection():
    from marketflow_claw.http_projection import ProjectionUnavailable
    from marketflow_claw.overview import build_overview

    payload = build_overview()
    if (payload.get('errors') or {}).get('db'):
        raise ProjectionUnavailable()
    return payload


def _quality_projection():
    from marketflow_claw.http_projection import ProjectionUnavailable
    from marketflow_claw.observation import build_quality

    payload = build_quality()
    if payload.get('status') == 'unavailable' or (payload.get('integrity') or {}).get('status') == 'incomplete':
        raise ProjectionUnavailable()
    return payload


def _scorecards_projection(window_days):
    from marketflow_claw.http_projection import ProjectionUnavailable
    from marketflow_claw.observation import build_scorecards

    payload = build_scorecards(window_days=window_days)
    if payload.get('insufficient_reason') == 'ledger_unavailable':
        raise ProjectionUnavailable()
    return payload


@kr_claw_bp.route('/overview')
@pro_or_kongming_required
def claw_overview():
    return _project('overview', _overview_projection)


@kr_claw_bp.route('/close-leaders')
@pro_or_kongming_required
def claw_close_leaders():
    """마감 기준 주도주 (마스터 플랜 P3). ?day=YYYYMMDD 로 특정 세션 조회."""
    from flask import request

    from marketflow_claw.overview import build_close_leaders

    day = (request.args.get('day') or '').strip()
    if day and (len(day) != 8 or not day.isdigit()):
        return jsonify({'error': 'invalid_day'}), 400
    payload = build_close_leaders(day or None)
    return _no_store(payload)


@kr_claw_bp.route('/scorecards')
@admin_or_aibain_required
def claw_scorecards():
    """Shadow outcome projection; performs no scan, delivery, or mutation."""
    try:
        window_days = max(1, min(int(request.args.get('window_days', 30)), 365))
    except (TypeError, ValueError):
        window_days = 30
    return _project(f'scorecards:{window_days}', lambda: _scorecards_projection(window_days))


@kr_claw_bp.route('/quality')
@admin_or_aibain_required
def claw_quality():
    """Observation-ledger diagnostics; performs no scan or repair action."""
    return _project('quality', _quality_projection)
