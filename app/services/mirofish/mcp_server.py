"""FastMCP adapter for the MiroFish autonomous control-plane."""

from __future__ import annotations

import json
import os
from typing import Any

import app.services.mirofish.alpha_scanner as alpha_scanner
import app.services.mirofish.autonomous_mcp as autonomous_mcp
import app.services.mirofish.workflow as workflow

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    FastMCP = None  # type: ignore[assignment]


def create_mcp_server(
    *,
    host: str | None = None,
    port: int | None = None,
    streamable_http_path: str | None = None,
) -> Any:
    """Create a FastMCP server exposing MiroFish autonomous tools."""
    if FastMCP is None:
        raise RuntimeError('mcp package is not installed. Install requirements.txt first.')
    clean_host = host or os.getenv('MIROFISH_MCP_HOST', '127.0.0.1')
    clean_port = int(port or os.getenv('MIROFISH_MCP_PORT', '8765'))
    clean_path = streamable_http_path or os.getenv('MIROFISH_MCP_PATH', '/mcp')

    mcp = FastMCP(
        'MarketFlow MiroFish Autonomous MCP',
        host=clean_host,
        port=clean_port,
        streamable_http_path=clean_path,
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def get_autonomous_status() -> dict[str, Any]:
        """Return redacted scanner/workflow/learning/Telegram MCP status."""
        return autonomous_mcp.get_autonomous_status()

    @mcp.tool()
    def get_mcp_security_policy() -> dict[str, Any]:
        """Return the redacted MCP security policy and allowlist."""
        return autonomous_mcp.get_mcp_security_policy()

    @mcp.tool()
    def get_market_clock() -> dict[str, Any]:
        """Return KST market-session and scanner schedule status."""
        return autonomous_mcp.get_market_clock()

    @mcp.tool()
    def get_repository_state() -> dict[str, Any]:
        """Return a read-only git branch/head/dirty summary."""
        return autonomous_mcp.get_repository_state()

    @mcp.tool()
    def list_recent_scanner_runs(limit: int = 20) -> dict[str, Any]:
        """List recent deterministic alpha scanner runs."""
        return autonomous_mcp.list_recent_scanner_runs(limit=limit)

    @mcp.tool()
    def list_recent_workflows(limit: int = 20) -> dict[str, Any]:
        """List recent scanner-to-analysis workflow runs."""
        return autonomous_mcp.list_recent_workflows(limit=limit)

    @mcp.tool()
    def list_safe_artifacts(kind: str = 'all', limit: int = 50) -> dict[str, Any]:
        """List small read-only MiroFish artifacts from the safe allowlist."""
        return autonomous_mcp.list_safe_artifacts(kind=kind, limit=limit)

    @mcp.tool()
    def read_safe_artifact(path: str) -> dict[str, Any]:
        """Read one allowlisted MiroFish artifact by relative path or resource link."""
        return autonomous_mcp.read_safe_artifact(path)

    @mcp.tool()
    def run_candidate_detection_alert(
        dry_run: bool = True,
        send_telegram: bool = False,
        confirmation: str = '',
        api_key: str = '',
        limit: int = 20,
        min_alpha: float = 70,
        max_risk: float = 45,
        max_events: int = 8,
        symbols: str = '',
        allow_stale_sources: bool = False,
        channel: bool = False,
        commit_state: bool = True,
    ) -> dict[str, Any]:
        """Detect new alpha candidates and optionally send Telegram alerts."""
        return autonomous_mcp.run_candidate_detection_alert({
            'dry_run': dry_run,
            'send_telegram': send_telegram,
            'confirmation': confirmation,
            'api_key': api_key,
            'limit': limit,
            'min_alpha': min_alpha,
            'max_risk': max_risk,
            'max_events': max_events,
            'symbols': symbols,
            'allow_stale_sources': allow_stale_sources,
            'channel': channel,
            'commit_state': commit_state,
        })

    @mcp.tool()
    def run_autonomous_scan_analysis(
        dry_run: bool = True,
        sync: bool = False,
        send_telegram: bool = False,
        confirmation: str = '',
        api_key: str = '',
        limit: int = 20,
        min_alpha: float = 50,
        max_risk: float = 65,
        max_events: int = 5,
        agent_count: int = 10,
        top_n: int = 3,
        max_parallel: int = 3,
        symbols: str = '',
        actions: str = '',
        mode: str = 'full',
        force: bool = False,
        allow_stale_sources: bool = False,
        channel: bool = False,
        commit_event_state: bool = True,
        refresh_learning: bool = True,
    ) -> dict[str, Any]:
        """Run scan -> GraphRAG analysis -> outcome learning -> optional Telegram."""
        return autonomous_mcp.run_autonomous_scan_analysis({
            'dry_run': dry_run,
            'sync': sync,
            'send_telegram': send_telegram,
            'confirmation': confirmation,
            'api_key': api_key,
            'limit': limit,
            'min_alpha': min_alpha,
            'max_risk': max_risk,
            'max_events': max_events,
            'agent_count': agent_count,
            'top_n': top_n,
            'max_parallel': max_parallel,
            'symbols': symbols,
            'actions': actions,
            'mode': mode,
            'force': force,
            'allow_stale_sources': allow_stale_sources,
            'channel': channel,
            'commit_event_state': commit_event_state,
            'refresh_learning': refresh_learning,
        })

    @mcp.tool()
    def refresh_learning_feedback(
        api_key: str = '',
        limit: int = 20,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Refresh look-ahead-safe outcome feedback without mutating live weights."""
        return autonomous_mcp.refresh_learning_feedback({
            'api_key': api_key,
            'limit': limit,
            'commit': commit,
        })

    @mcp.tool()
    def send_latest_workflow_telegram(
        confirmation: str,
        api_key: str = '',
        workflow_id: str = '',
        channel: bool = False,
        commit_event_state: bool = True,
    ) -> dict[str, Any]:
        """Send the latest or selected completed workflow Top-N message to Telegram."""
        return autonomous_mcp.send_latest_workflow_telegram({
            'confirmation': confirmation,
            'api_key': api_key,
            'workflow_id': workflow_id,
            'channel': channel,
            'commit_event_state': commit_event_state,
        })

    @mcp.tool()
    def get_workflow_share_payload(
        workflow_id: str = '',
        rank: int | None = None,
    ) -> dict[str, Any]:
        """KakaoTalk 공유용 풍부한 페이로드 (5인 페르소나 인용 + CIO reasoning).

        Args:
            workflow_id: 빈 문자열이면 최신 workflow 사용.
            rank: 1|2|3 단일 종목, None 이면 TOP 3 전체.

        Returns:
            {'title', 'description', 'image_url', 'link_url',
             'top_items', 'list_contents', 'kakao_buttons',
             'analyst_quote', 'cio_reasoning', 'cio_opposing'}
        """
        wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
        if wf is None:
            return {'error': 'workflow not found', 'workflow_id': workflow_id or 'latest'}
        try:
            payload = workflow.build_share_payload(wf, rank=rank)
            return payload
        except ValueError as exc:
            return {'error': str(exc)}

    @mcp.tool()
    def get_top3_summary(workflow_id: str = '') -> dict[str, Any]:
        """현재 또는 지정 workflow 의 TOP 3 핵심 요약 — Claude 가 즉시 응답 가능한 형태.

        AI 애널리스트 (5인 페르소나) 의 핵심 인용 + CIO reasoning + 검증 결과를 포함.
        Claude Desktop 에서 "이번 주 TOP 3 알려줘" 같은 자연어 질의에 답하기 위해 사용.

        Args:
            workflow_id: 빈 문자열이면 최신 workflow.

        Returns:
            {'workflow_id', 'completed_at', 'top_count', 'top_items': [{...}], 'one_liner'}
        """
        wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
        if wf is None:
            return {'error': 'workflow not found'}
        payload = workflow.build_share_payload(wf, rank=None)
        top_items = payload.get('top_items', [])
        one_liner = ' / '.join(
            f"#{it['rank']} {it['name']} {it['action']} {it['confidence_pct']}%"
            for it in top_items
        )
        return {
            'workflow_id': payload.get('workflow_id'),
            'completed_at': payload.get('completed_at'),
            'top_count': len(top_items),
            'top_items': top_items,
            'one_liner': one_liner,
            'description': payload.get('description'),
        }

    @mcp.resource('mirofish://workflows/share')
    def latest_share_resource() -> str:
        """최신 workflow 의 카카오톡 공유 페이로드 (5인 인용 + CIO 포함)."""
        wf = workflow.read_latest_workflow()
        if wf is None:
            return _json({'error': 'workflow not found'})
        try:
            return _json(workflow.build_share_payload(wf, rank=None))
        except Exception as exc:
            return _json({'error': str(exc)})

    @mcp.resource('mirofish://autonomous/status')
    def autonomous_status_resource() -> str:
        """Redacted autonomous MCP status."""
        return _json(autonomous_mcp.get_autonomous_status())

    @mcp.resource('mirofish://autonomous/security')
    def autonomous_security_resource() -> str:
        """Redacted autonomous MCP security policy."""
        return _json(autonomous_mcp.get_mcp_security_policy())

    @mcp.resource('mirofish://autonomous/learning')
    def autonomous_learning_resource() -> str:
        """Latest advisory learning feedback artifact."""
        return _json(autonomous_mcp.read_learning_feedback() or {'available': False})

    @mcp.resource('mirofish://market/clock')
    def market_clock_resource() -> str:
        """KST market-session and scanner schedule status."""
        return _json(autonomous_mcp.get_market_clock())

    @mcp.resource('mirofish://scanner/latest')
    def latest_scanner_resource() -> str:
        """Latest deterministic alpha scanner run."""
        return _json(alpha_scanner.read_latest_scanner_run() or {'error': 'scanner run not found'})

    @mcp.resource('mirofish://workflows/latest')
    def latest_workflow_resource() -> str:
        """Latest scanner-to-analysis workflow run."""
        return _json(workflow.read_latest_workflow() or {'error': 'workflow not found'})

    return mcp


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
