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
    args = parser.parse_args()
    mcp = create_mcp_server()
    mcp.run(transport=args.transport)


if __name__ == '__main__':
    main()
