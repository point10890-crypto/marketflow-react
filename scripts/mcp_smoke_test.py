"""MiroFish MCP server stdio 클라이언트 smoke test.

실행:
    python scripts/mcp_smoke_test.py

확인:
1. server 가 stdio 로 부팅되는지
2. tool list 정상 응답
3. 가벼운 tool 1-2개 실제 호출 (get_market_clock, get_autonomous_status)
4. resource 1개 읽기
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env 강제 로드
env_path = ROOT / '.env'
if env_path.exists():
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ.setdefault(k, v)


async def run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    print('=' * 70)
    print(' MiroFish MCP Server — stdio smoke test')
    print('=' * 70)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / 'mirofish_mcp_server.py'), '--transport', 'stdio'],
        env={**os.environ, 'PYTHONIOENCODING': 'utf-8'},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1) initialize
            print('\n[1] initialize...')
            init_result = await session.initialize()
            print(f'  server: {init_result.serverInfo.name} v{init_result.serverInfo.version}')

            # 2) list tools
            print('\n[2] list_tools()')
            tools_response = await session.list_tools()
            tools = tools_response.tools
            print(f'  총 {len(tools)} tools:')
            for t in tools:
                desc = (t.description or '')[:60]
                print(f'    - {t.name}: {desc}')

            # 3) list resources
            print('\n[3] list_resources()')
            res_response = await session.list_resources()
            resources = res_response.resources
            print(f'  총 {len(resources)} resources:')
            for r in resources:
                print(f'    - {r.uri}')

            # 4) call gentle tool — get_market_clock
            print('\n[4] call_tool(get_market_clock)')
            try:
                result = await session.call_tool('get_market_clock', arguments={})
                content = result.content[0] if result.content else None
                if content and hasattr(content, 'text'):
                    import json
                    try:
                        data = json.loads(content.text)
                        keys = list(data.keys())[:6] if isinstance(data, dict) else 'list'
                        print(f'  ✅ tool 응답 keys: {keys}')
                        if isinstance(data, dict):
                            for k in ['market_session', 'is_market_open', 'kst_now', 'next_scanner_at']:
                                if k in data:
                                    print(f'     {k}: {data[k]}')
                    except json.JSONDecodeError:
                        print(f'  ✅ 응답 (raw, 200자):')
                        print(f'     {content.text[:200]}')
                else:
                    print(f'  응답: {result}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

            # 5) call get_autonomous_status
            print('\n[5] call_tool(get_autonomous_status)')
            try:
                result = await session.call_tool('get_autonomous_status', arguments={})
                content = result.content[0] if result.content else None
                if content and hasattr(content, 'text'):
                    import json
                    try:
                        data = json.loads(content.text)
                        if isinstance(data, dict):
                            print(f'  ✅ keys: {list(data.keys())[:8]}')
                            for k in ['mode', 'ready', 'last_scanner_run_id', 'last_workflow_id']:
                                if k in data:
                                    print(f'     {k}: {data[k]}')
                    except json.JSONDecodeError:
                        print(f'  ✅ raw: {content.text[:200]}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

            # 6) read resource mirofish://market/clock
            print('\n[6] read_resource(mirofish://market/clock)')
            try:
                from pydantic import AnyUrl
                result = await session.read_resource(AnyUrl('mirofish://market/clock'))
                contents = result.contents[0] if result.contents else None
                if contents and hasattr(contents, 'text'):
                    print(f'  ✅ first 200 chars:')
                    print(f'     {contents.text[:200]}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

            # 7) 신규 도구 — get_top3_summary
            print('\n[7] call_tool(get_top3_summary)  ← 신규')
            try:
                result = await session.call_tool('get_top3_summary', arguments={})
                content = result.content[0] if result.content else None
                if content and hasattr(content, 'text'):
                    import json
                    data = json.loads(content.text)
                    print(f'  ✅ workflow_id: {data.get("workflow_id", "")[:40]}')
                    print(f'  ✅ top_count: {data.get("top_count")}')
                    print(f'  ✅ one_liner: {data.get("one_liner")}')
                    print(f'  ✅ first item analyst_quote: {(data.get("top_items", [{}])[0].get("analyst_quote") or "")[:100]}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

            # 8) 신규 도구 — get_workflow_share_payload(rank=1)
            print('\n[8] call_tool(get_workflow_share_payload rank=1)  ← 신규')
            try:
                result = await session.call_tool('get_workflow_share_payload', arguments={'rank': 1})
                content = result.content[0] if result.content else None
                if content and hasattr(content, 'text'):
                    import json
                    data = json.loads(content.text)
                    print(f'  ✅ title: {data.get("title")}')
                    desc = (data.get("description") or "")[:140]
                    print(f'  ✅ desc: {desc}')
                    print(f'  ✅ cio_reasoning: {(data.get("cio_reasoning") or "")[:80]}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

            # 9) 신규 resource — mirofish://workflows/share
            print('\n[9] read_resource(mirofish://workflows/share)  ← 신규')
            try:
                from pydantic import AnyUrl
                result = await session.read_resource(AnyUrl('mirofish://workflows/share'))
                contents = result.contents[0] if result.contents else None
                if contents and hasattr(contents, 'text'):
                    import json
                    data = json.loads(contents.text)
                    print(f'  ✅ title: {data.get("title")}')
                    print(f'  ✅ list_contents: {len(data.get("list_contents", []))}')
            except Exception as e:
                print(f'  ❌ {type(e).__name__}: {e}')

    print('\n' + '=' * 70)
    print(' ✅ MCP smoke test 완료')
    print('=' * 70)


if __name__ == '__main__':
    asyncio.run(run())
