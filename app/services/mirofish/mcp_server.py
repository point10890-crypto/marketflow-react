"""FastMCP adapter for the MiroFish autonomous control-plane."""

from __future__ import annotations

import json
from typing import Any

import app.services.mirofish.alpha_scanner as alpha_scanner
import app.services.mirofish.autonomous_mcp as autonomous_mcp
import app.services.mirofish.workflow as workflow

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised only when dependency is absent.
    FastMCP = None  # type: ignore[assignment]


def create_mcp_server() -> Any:
    """Create a FastMCP server exposing MiroFish autonomous tools."""
    if FastMCP is None:
        raise RuntimeError('mcp package is not installed. Install requirements.txt first.')

    mcp = FastMCP(
        'MarketFlow MiroFish Autonomous MCP',
        stateless_http=True,
        json_response=True,
    )

    @mcp.tool()
    def get_autonomous_status() -> dict[str, Any]:
        """Return redacted scanner/workflow/learning/Telegram MCP status."""
        return autonomous_mcp.get_autonomous_status()

    @mcp.tool()
    def list_recent_scanner_runs(limit: int = 20) -> dict[str, Any]:
        """List recent deterministic alpha scanner runs."""
        return autonomous_mcp.list_recent_scanner_runs(limit=limit)

    @mcp.tool()
    def list_recent_workflows(limit: int = 20) -> dict[str, Any]:
        """List recent scanner-to-analysis workflow runs."""
        return autonomous_mcp.list_recent_workflows(limit=limit)

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

    @mcp.resource('mirofish://autonomous/status')
    def autonomous_status_resource() -> str:
        """Redacted autonomous MCP status."""
        return _json(autonomous_mcp.get_autonomous_status())

    @mcp.resource('mirofish://autonomous/learning')
    def autonomous_learning_resource() -> str:
        """Latest advisory learning feedback artifact."""
        return _json(autonomous_mcp.read_learning_feedback() or {'available': False})

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
