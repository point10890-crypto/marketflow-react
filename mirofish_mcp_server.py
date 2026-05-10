"""Entrypoint for the MarketFlow MiroFish Autonomous MCP server."""

from __future__ import annotations

import argparse
import os

try:
    from dotenv import load_dotenv

    load_dotenv(override=False)
except ImportError:
    pass

from app.services.mirofish.mcp_server import create_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the MiroFish Autonomous MCP server.')
    parser.add_argument(
        '--transport',
        choices=('stdio', 'streamable-http'),
        default=os.getenv('MIROFISH_MCP_TRANSPORT', 'stdio'),
        help='MCP transport to use. Use streamable-http for remote clients.',
    )
    parser.add_argument('--host', default=os.getenv('MIROFISH_MCP_HOST', '127.0.0.1'))
    parser.add_argument('--port', type=int, default=int(os.getenv('MIROFISH_MCP_PORT', '8765')))
    parser.add_argument('--path', default=os.getenv('MIROFISH_MCP_PATH', '/mcp'))
    args = parser.parse_args()
    mcp = create_mcp_server(host=args.host, port=args.port, streamable_http_path=args.path)
    mcp.run(transport=args.transport)


if __name__ == '__main__':
    main()
