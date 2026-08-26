"""Claw LIVE 읽기전용 API — /api/kr/claw/*

대시보드가 5초 폴링하므로 캐시 금지. mutation 엔드포인트는 두지 않는다
(발송·스캔은 CLI/스케줄 전용).
"""
from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_or_aibain_required, pro_required

kr_claw_bp = Blueprint('kr_claw', __name__)


def _no_store(payload):
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@kr_claw_bp.route('/overview')
@pro_required
def claw_overview():
    from marketflow_claw.overview import build_overview

    payload = build_overview()
    return _no_store(payload)


@kr_claw_bp.route('/close-leaders')
@pro_required
def claw_close_leaders():
    """마감 기준 주도주 (마스터 플랜 P3). ?day=YYYYMMDD 로 특정 세션 조회."""
    from flask import request

    from marketflow_claw.overview import build_close_leaders

    day = (request.args.get('day') or '').strip()
    if day and (len(day) != 8 or not day.isdigit()):
        return jsonify({'error': 'invalid_day'}), 400
    payload = build_close_leaders(day or None)
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'public, max-age=60'  # 마감 데이터 — 세션당 1회 확정
    return resp


@kr_claw_bp.route('/scorecards')
@admin_or_aibain_required
def claw_scorecards():
    """Shadow outcome projection; performs no scan, delivery, or mutation."""
    from marketflow_claw.observation import build_scorecards

    try:
        window_days = max(1, min(int(request.args.get('window_days', 30)), 365))
    except (TypeError, ValueError):
        window_days = 30
    return _no_store(build_scorecards(window_days=window_days))


@kr_claw_bp.route('/quality')
@admin_or_aibain_required
def claw_quality():
    """Observation-ledger diagnostics; performs no scan or repair action."""
    from marketflow_claw.observation import build_quality

    return _no_store(build_quality())
