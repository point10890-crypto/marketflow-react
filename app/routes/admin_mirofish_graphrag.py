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

대부분 route 는 ``@admin_required`` 적용.
일부 read-only 분석 데이터 (status, scan-history, scan-history-performance) 는
``@admin_or_aibain_required`` — AI Bain 알파 스캐너 구독자도 조회 가능.
"""
from __future__ import annotations

import time

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_required, admin_or_aibain_required
from app.services.mirofish import graphrag as graphrag_service


admin_mirofish_graphrag_bp = Blueprint('admin_mirofish_graphrag', __name__)


# ── Phase A: status ──────────────────────────────────────────────────

@admin_mirofish_graphrag_bp.route('/status', methods=['GET'])
@admin_or_aibain_required
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


# ── Phase F: eval + metrics ───────────────────────────────────────────

@admin_mirofish_graphrag_bp.route('/eval/run', methods=['POST'])
@admin_required
def graphrag_eval_run():
    """Run replay-safe evaluation (현재는 jongga_v2_replay 지원).

    Body 예시::

        {
          "benchmark": "jongga_v2_replay",
          "from_date": "2026-03-01",  // null OK
          "to_date": "2026-04-01",    // null OK
          "horizon_days": 5,
          "configs": [
            {"name": "S_only", "min_grade": "S"},
            {"name": "score_ge_10", "min_score": 10}
          ]
        }

    응답에는 metrics (config 별 hit_rate / IC / 평균 수익률) 포함.
    결과는 ``data/admin_mirofish/graphrag/eval/eval_<ts>.json`` 에 저장됨.
    """
    payload = request.get_json(silent=True) or {}
    benchmark = str(payload.get('benchmark') or 'jongga_v2_replay').strip()
    if benchmark != 'jongga_v2_replay':
        return jsonify({
            'error': 'unsupported benchmark — only "jongga_v2_replay" is implemented',
            'benchmark': benchmark,
        }), 400
    try:
        horizon_days = int(payload.get('horizon_days') or 5)
    except (TypeError, ValueError):
        horizon_days = 5
    try:
        result = graphrag_service.run_jongga_v2_replay(
            from_date=payload.get('from_date'),
            to_date=payload.get('to_date'),
            horizon_days=horizon_days,
            configs=payload.get('configs'),
        )
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'benchmark': benchmark}), 500


@admin_mirofish_graphrag_bp.route('/metrics', methods=['GET'])
@admin_required
def graphrag_metrics():
    """Graph quality metrics + recent eval summary + advisory feedback.

    Response::

        {
          "service": "mirofish-graphrag-metrics",
          "graph_quality": {"entity_count": int, "alias_count": int, ...},
          "eval_history": [{run_id, ..., metrics}],
          "advisory_feedback": {evaluated_count, hit_rate_recent, ...},
          "asof": "..."
        }
    """
    try:
        status = graphrag_service.get_subsystem_status()
    except Exception as exc:
        status = {'entities': {}, 'phase': {}, 'state': 'error', 'error': str(exc)}

    try:
        eval_history = graphrag_service.get_eval_history(limit=5)
    except Exception as exc:
        eval_history = [{'error': str(exc)}]

    try:
        from app.services.mirofish.outcome_tracker import get_advisory_feedback
        advisory = get_advisory_feedback()
    except Exception as exc:
        advisory = {'error': str(exc)}

    entities = status.get('entities') or {}
    return jsonify({
        'service': 'mirofish-graphrag-metrics',
        'graph_quality': {
            'entity_count': entities.get('entity_count', 0),
            'alias_count': entities.get('alias_count', 0),
            'external_id_count': entities.get('external_id_count', 0),
            'present': entities.get('present', False),
        },
        'phase': status.get('phase', {}),
        'eval_history': eval_history,
        'advisory_feedback': advisory,
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }), 200


# ── Phase G: MCP scan history + performance ───────────────────────────

@admin_mirofish_graphrag_bp.route('/scan-history', methods=['GET'])
@admin_or_aibain_required
def graphrag_scan_history():
    """모든 scanner runs + workflow outcomes 를 symbol 단위로 집계.

    Query params:
      - days (int, default 30, max 365): 조회 윈도우.
      - limit (int, default 100, max 1000): 상위 N 종목.
      - min_alpha (float, default 0): alpha_avg 필터.

    Response 핵심 필드:
      window_days, total_unique_symbols, total_scans, total_workflows,
      items: [{symbol, display_name, scan_count, alpha_avg, workflow_count,
               outcome: {hit_count, miss_count, hit_rate, avg_forward_return_pct}}],
      summary: {evaluated_count, hit_rate, avg_return_pct}.
    """
    try:
        days = int(request.args.get('days', '30'))
    except (TypeError, ValueError):
        days = 30
    try:
        limit = int(request.args.get('limit', '100'))
    except (TypeError, ValueError):
        limit = 100
    try:
        min_alpha = float(request.args.get('min_alpha', '0'))
    except (TypeError, ValueError):
        min_alpha = 0.0
    try:
        return jsonify(graphrag_service.get_scan_history(
            days=days,
            limit_symbols=limit,
            min_alpha=min_alpha,
        )), 200
    except Exception as exc:  # pragma: no cover — defensive
        return jsonify({
            'error': str(exc),
            'items': [],
            'summary': {},
        }), 500


@admin_mirofish_graphrag_bp.route('/scan-history-performance', methods=['GET'])
@admin_or_aibain_required
def graphrag_scan_performance():
    """전체 통계 + 그룹별 breakdown (KPI/IC/by_market/by_tag/top_performers).

    별도 path (``/scan-history-performance``) 로 분리한 이유:
      `/scan-history/<symbol>` 의 path converter 와 충돌 회피.

    Query params:
      - days (int, default 60, max 365): 조회 윈도우.
    """
    try:
        days = int(request.args.get('days', '60'))
    except (TypeError, ValueError):
        days = 60
    try:
        return jsonify(graphrag_service.get_performance_summary(days=days)), 200
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@admin_mirofish_graphrag_bp.route('/scan-history/<path:symbol>', methods=['GET'])
@admin_required
def graphrag_symbol_history(symbol: str):
    """단일 종목 history (모든 scanner 등장 + workflow top3 진입 + outcome).

    Query params:
      - days (int, default 180, max 730).
    """
    try:
        days = int(request.args.get('days', '180'))
    except (TypeError, ValueError):
        days = 180
    if not symbol:
        return jsonify({'error': 'symbol required'}), 400
    try:
        data = graphrag_service.get_symbol_history(symbol, limit_days=days)
        return jsonify(data), 200
    except Exception as exc:
        return jsonify({'error': str(exc), 'symbol': symbol}), 500
