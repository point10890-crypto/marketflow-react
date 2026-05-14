"""Admin-only MiroFish GraphRAG analysis endpoints.

URL prefix: ``/api/admin/mirofish/graphrag``
청사진 ``docs/mirofish_graphrag_analysis_endpoint_implementation_blueprint_2026_05_14.md``
Phase A–F 를 단계적으로 노출한다.

이 Blueprint 의 책임:
- subsystem status / health
- entity resolve / lookup (Phase B 이후)
- search / subgraph / events (Phase B+)
- community summary (Phase C+)
- research run (Phase D+)
- metrics (Phase F+)

모든 route 는 ``@admin_required`` 적용.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_required
from app.services.mirofish import graphrag as graphrag_service


admin_mirofish_graphrag_bp = Blueprint('admin_mirofish_graphrag', __name__)


# ── Phase A: status ──────────────────────────────────────────────────

@admin_mirofish_graphrag_bp.route('/status', methods=['GET'])
@admin_required
def graphrag_status():
    """GraphRAG subsystem 상태 조회.

    Response 예시::

        {
          "service": "mirofish-graphrag",
          "state": "not_initialized" | "degraded" | "ready",
          "ready": false,
          "phase": {"A_skeleton": true, "B_resolver": false, ...},
          "storage": {...},
          "entities": {"present": false, "entity_count": 0, ...},
          "flags": {"shadow_mode": true, "cache_ttl_sec": 3600, ...},
          "asof": "2026-05-14T..."
        }
    """
    try:
        return jsonify(graphrag_service.get_subsystem_status()), 200
    except Exception as exc:  # pragma: no cover — defensive
        return jsonify({
            'service': 'mirofish-graphrag',
            'state': 'error',
            'ready': False,
            'error': str(exc),
        }), 500


# ── Phase B: entity resolver ──────────────────────────────────────────

@admin_mirofish_graphrag_bp.route('/entities/resolve', methods=['GET'])
@admin_required
def graphrag_resolve_entity():
    """엔티티 resolve.

    Query params:
      - q (required): 입력 (한글명, 약어, 초성, ticker, yahoo, corp_code)
      - hint_market (optional): KR / US / CRYPTO — 동점일 때 가산점
      - limit (optional): 기본 5, 최대 20

    Response::

        {"query": "두산", "matches": [{...}], "asof": "...", "source": "..."}
    """
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'error': 'query parameter "q" required', 'matches': []}), 400
    hint = request.args.get('hint_market')
    try:
        limit = int(request.args.get('limit', '5'))
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 20))
    try:
        return jsonify(graphrag_service.resolve_entity(q, hint_market=hint, limit=limit)), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'matches': []}), 500


@admin_mirofish_graphrag_bp.route('/entities/<path:entity_id>', methods=['GET'])
@admin_required
def graphrag_get_entity(entity_id: str):
    """단일 entity 상세 조회.

    ``entity_id`` 는 ``kr:005930`` 같은 표준 형식.
    """
    if not entity_id:
        return jsonify({'error': 'entity_id required'}), 400
    try:
        data = graphrag_service.get_entity(entity_id)
        if not data:
            return jsonify({'error': 'entity not found', 'entity_id': entity_id}), 404
        return jsonify(data), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'entity_id': entity_id}), 500
