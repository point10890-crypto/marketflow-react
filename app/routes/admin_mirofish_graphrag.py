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

from flask import Blueprint, jsonify

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
