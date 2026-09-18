import asyncio

from app.services.mirofish.mcp_server import create_mcp_server
from app.services.mirofish import multi_mcp_orchestrator


def test_multi_mcp_tools_are_registered():
    server = create_mcp_server(host='127.0.0.1', port=18765)

    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert 'get_multi_mcp_architecture' in names
    assert 'run_multi_mcp_deep_research' in names
    assert 'run_multi_mcp_live_market_scan' in names


def test_direct_mcp_candidate_payload_is_always_non_publishable(monkeypatch):
    captured = {}

    def analyze(candidates, **kwargs):
        captured['candidates'] = candidates
        captured['options'] = kwargs
        return {'status': 'cash_wait'}

    monkeypatch.setattr(
        multi_mcp_orchestrator,
        'run_multi_mcp_analysis',
        analyze,
    )
    server = create_mcp_server(host='127.0.0.1', port=18765)

    asyncio.run(server.call_tool(
        'run_multi_mcp_deep_research',
        {
            'candidates_json': '[{"symbol":"005930","source":"KIS"}]',
            'use_llm': False,
            'max_parallel': 1,
        },
    ))

    assert captured['options']['input_mode'] == 'authenticated_debug'
