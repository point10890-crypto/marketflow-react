"""FastMCP tools for GraphRAG analysis (read-only).

청사진 docs/mirofish_graphrag_analysis_endpoint_implementation_blueprint_2026_05_14.md
§8 의 graphrag_* prefix 강제. 운영 변경 없는 read-only tools 만 노출.
admin_mirofish_graphrag.py 의 HTTP 엔드포인트 (status, entities/resolve, entities/{id}) 와 1:1 매칭.

§8.3 (Excluded from MCP):
    - POST /graphrag/events/ingest   — 내부 ETL admin-only write
    - POST /graphrag/eval/run        — 비용 큼 + 상태 변경 가능
이 둘은 이 모듈에서 등록하지 않는다.
"""
from __future__ import annotations

from typing import Any


def register_graphrag_tools(mcp: Any) -> int:
    """주어진 FastMCP 인스턴스에 ``graphrag_*`` read-only tools 를 등록한다.

    Args:
        mcp: ``FastMCP`` 인스턴스 (``app.services.mirofish.mcp_server`` 에서 생성).

    Returns:
        등록된 tool 개수.
    """
    from app.services.mirofish import graphrag as graphrag_service

    count = 0

    @mcp.tool()
    def graphrag_get_status() -> dict[str, Any]:
        """MiroFish GraphRAG subsystem status (phase progress, storage, flags).

        HTTP 대응: ``GET /api/admin/mirofish/graphrag/status``.

        Returns:
            state (ready/degraded/not_initialized), phase 진행도, storage inventory,
            entities count, feature flags, asof timestamp.
        """
        return graphrag_service.get_subsystem_status()
    count += 1

    @mcp.tool()
    def graphrag_resolve_entity(
        q: str,
        hint_market: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Resolve query string to canonical entity_id.

        HTTP 대응: ``GET /api/admin/mirofish/graphrag/entities/resolve``.

        Args:
            q: 입력 - 한글 정식명 / 약어 / 초성 / ticker (6자리) / yahoo (XXXXXX.KS) / corp_code (8자리).
            hint_market: optional ``'KR'`` / ``'US'`` / ``'CRYPTO'`` for tie-breaking.
            limit: max matches (1-20, default 5).

        Returns:
            ``{query, normalized, matches: [{entity_id, name, confidence, match_reason, ids}], asof}``.
        """
        try:
            limit_int = int(limit)
        except (TypeError, ValueError):
            limit_int = 5
        limit_int = max(1, min(limit_int, 20))
        return graphrag_service.resolve_entity(q, hint_market=hint_market, limit=limit_int)
    count += 1

    @mcp.tool()
    def graphrag_get_entity(entity_id: str) -> dict[str, Any] | None:
        """Get single entity by canonical id with external_ids + aliases.

        HTTP 대응: ``GET /api/admin/mirofish/graphrag/entities/<entity_id>``.

        Args:
            entity_id: canonical id (e.g. ``'kr:005930'``, ``'us:AAPL'``).

        Returns:
            entity dict (name_ko, symbol, market, ids, aliases) 또는 ``None`` (미존재).
        """
        return graphrag_service.get_entity(entity_id)
    count += 1

    @mcp.tool()
    def graphrag_get_scan_history(
        days: int = 30,
        limit_symbols: int = 100,
        min_alpha: float = 0.0,
    ) -> dict[str, Any]:
        """All scanner runs + workflow outcomes aggregated per symbol.

        HTTP 대응: ``GET /api/admin/mirofish/graphrag/scan-history``.

        Args:
            days: window in days (1-365).
            limit_symbols: top N symbols by scan_count (1-1000).
            min_alpha: filter symbols with alpha_avg < min_alpha.

        Returns:
            window_days, total_unique_symbols, total_scans, total_workflows,
            items[]: symbol/scan_count/alpha_avg/workflow_count/outcome,
            summary: evaluated_count/hit_rate/avg_return_pct.
        """
        return graphrag_service.get_scan_history(
            days=int(days or 30),
            limit_symbols=int(limit_symbols or 100),
            min_alpha=float(min_alpha or 0),
        )
    count += 1

    @mcp.tool()
    def graphrag_get_symbol_history(
        symbol: str,
        days: int = 180,
    ) -> dict[str, Any]:
        """Single-symbol scan + workflow + outcome history.

        HTTP 대응: ``GET /api/admin/mirofish/graphrag/scan-history/<symbol>``.

        Args:
            symbol: KR 6-digit code or US/Crypto ticker.
            days: window in days (1-730).

        Returns:
            symbol, display_name, market, scans[], workflows[],
            aggregate: total_scans/total_workflows/outcome_hit_rate/avg_forward_return_pct.

        Note:
            Performance summary (`graphrag_get_scan_performance`) is intentionally
            NOT exposed via MCP — it scans the full data window and can be expensive.
            Caller should use the HTTP endpoint directly when needed.
        """
        return graphrag_service.get_symbol_history(
            symbol,
            limit_days=int(days or 180),
        )
    count += 1

    return count
