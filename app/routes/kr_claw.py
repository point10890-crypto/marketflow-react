"""Claw LIVE 읽기전용 API — /api/kr/claw/*

대시보드가 5초 폴링하므로 캐시 금지. mutation 엔드포인트는 두지 않는다
(발송·스캔은 CLI/스케줄 전용).
"""
from flask import Blueprint, jsonify

from app.auth.decorators import pro_required

kr_claw_bp = Blueprint('kr_claw', __name__)


@kr_claw_bp.route('/overview')
@pro_required
def claw_overview():
    from marketflow_claw.overview import build_overview

    payload = build_overview()
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp
