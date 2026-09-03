# -*- coding: utf-8 -*-
"""종목 허브 API — GET /api/kr/stock/<code>/hub (Pro).

읽기 전용. 스케줄러 산출물과 로컬 시세 원장만 읽고, KIS·yfinance·LLM 을 호출하지
않는다. AI Brain 전용 소스는 싣지 않는다 (app/services/stock_hub.py 참고).
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from app.auth.decorators import pro_required

logger = logging.getLogger(__name__)

kr_stock_hub_bp = Blueprint('kr_stock_hub', __name__)


@kr_stock_hub_bp.route('/<code>/hub', methods=['GET'])
@pro_required
def stock_hub(code):
    from app.services import stock_hub as svc

    if not svc.is_valid_code(svc.normalize_code(code)):
        return jsonify({'error': 'invalid_symbol', 'detail': '종목코드는 6자리여야 합니다.'}), 400
    try:
        payload = svc.build_stock_hub(code)
    except ValueError as exc:
        return jsonify({'error': 'invalid_symbol', 'detail': str(exc)}), 400
    except Exception as exc:  # noqa: BLE001
        logger.exception('stock hub failed: %s', code)
        return jsonify({'error': 'stock_hub_failed', 'detail': f'{type(exc).__name__}: {exc}'}), 500
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = 'private, max-age=60'
    return resp
