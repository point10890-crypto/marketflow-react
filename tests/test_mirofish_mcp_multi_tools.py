import asyncio

from app.services.mirofish.mcp_server import create_mcp_server


def test_multi_mcp_tools_are_registered():
    server = create_mcp_server(host='127.0.0.1', port=18765)

    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}

    assert 'get_multi_mcp_architecture' in names
    assert 'run_multi_mcp_deep_research' in names
    assert 'run_multi_mcp_live_market_scan' in names
