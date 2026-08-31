# -*- coding: utf-8 -*-
"""AI Brain 서비스 가드 관리 API — 읽기전용.

/api/admin/mirofish/service-guard        최신 가드 결과 (없으면 즉석 1회 실행)
/api/admin/mirofish/service-guard/run    즉석 재점검 (POST, admin 전용 — 프로브 실행 비용)
"""
from flask import Blueprint, jsonify

from app.auth.decorators import admin_or_aibain_required, admin_required

admin_mirofish_guard_bp = Blueprint('admin_mirofish_guard', __name__)


def _no_cache(payload):
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@admin_mirofish_guard_bp.route('/service-guard', methods=['GET'])
@admin_or_aibain_required
def service_guard_latest():
    from app.services.mirofish import service_guard

    latest = service_guard.read_latest()
    if latest is None:
        latest = service_guard.run_guard(send_fn=None)
    return _no_cache(latest)


@admin_mirofish_guard_bp.route('/service-guard/run', methods=['POST'])
@admin_required
def service_guard_run_now():
    from app.services.mirofish import service_guard

    return _no_cache(service_guard.run_guard(send_fn=None))
