"""운영 관제 센터 API — 관리자 전용, 읽기 전용.

감시 자체는 별도 프로세스(`python -m app.services.control_center run`)가 한다.
여기서는 그 결과(latest.json · SQLite)를 읽어 보여 주고, 엔드포인트 목록만 현재 앱에서 직접 계산한다.
"""
from __future__ import annotations

import math
import time

from flask import Blueprint, current_app, jsonify, request

from app.auth.decorators import admin_required

control_center_bp = Blueprint('control_center', __name__)

@control_center_bp.after_request
def _no_store(resp):
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@control_center_bp.route('/summary', methods=['GET'])
@admin_required
def summary():
    from app.services.control_center.runner import read_snapshot

    return jsonify(read_snapshot())


@control_center_bp.route('/incidents', methods=['GET'])
@admin_required
def incidents():
    from app.services.control_center import store

    state = request.args.get('state', 'open')
    if state not in ('open', 'recent'):
        return jsonify({'error': 'state must be open or recent'}), 400
    try:
        limit = max(1, min(int(request.args.get('limit', '50')), 200))
    except ValueError:
        return jsonify({'error': 'limit must be an integer'}), 400
    with store.connect(read_only=True) as conn:
        rows = []
        if conn is not None:
            rows = store.open_incidents(conn, limit) if state == 'open' else store.recent_incidents(conn, limit)
    return jsonify({'state': state, 'incidents': rows})


@control_center_bp.route('/checks/<path:check_id>/history', methods=['GET'])
@admin_required
def check_history(check_id: str):
    from app.services.control_center import store

    try:
        hours = float(request.args.get('hours', '24'))
        if not math.isfinite(hours):
            raise ValueError
    except ValueError:
        return jsonify({'error': 'hours must be a finite number'}), 400
    hours = max(1.0, min(hours, 24 * store.RETENTION_DAYS))
    with store.connect(read_only=True) as conn:
        rows = store.history(conn, check_id, hours=hours) if conn is not None else []
        state = store.get_state(conn, check_id) if conn is not None else None
    return jsonify({'check_id': check_id, 'state': state, 'history': rows})


@control_center_bp.route('/routes', methods=['GET'])
@admin_required
def routes():
    """실행 중인 앱의 url_map 기준 엔드포인트 전수와 감시 방식 (60초 캐시)."""
    from app.services.control_center import contracts
    from app.services.control_center.inventory import build_inventory, coverage

    now = time.monotonic()
    cached_at, data = current_app.extensions.get('control_center_routes', (0, None))
    if data is None or now - cached_at > 60:
        data = coverage(build_inventory(current_app), contracts.load())
        current_app.extensions['control_center_routes'] = (now, data)
    return jsonify(data)
