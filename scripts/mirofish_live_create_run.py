"""create_run() 라이브 검증 — 실제 MarketFlow 데이터 + Gemini 호출.

flow:
1. live_data.build_context('삼성전자')
2. brain_13d snapshot
3. graphrag_extractor (LLM)
4. agent_debate (LLM)
5. cio_react (LLM)
6. run.json + graph.json + report.md 저장
"""
import json
import os
import sys
import time
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
                os.environ[k] = v


def banner(t: str):
    print('\n' + '=' * 70)
    print(f'  {t}')
    print('=' * 70)


def main():
    # Optional: rule mode (LLM 비용 절감) 또는 full (LLM 호출)
    mode = os.environ.get('SMOKE_MODE', 'full')

    banner(f'1. resolve_target_snapshot — 삼성전자')
    from app.services.mirofish import resolve_target_snapshot
    t0 = time.time()
    snap = resolve_target_snapshot('삼성전자')
    print(f'⏱️  {time.time() - t0:.2f}s')
    print(f"📌 resolved.symbol: {snap['resolved'].get('symbol')}")
    print(f"📌 resolved.market: {snap['resolved'].get('market')}")
    print(f"📌 price: {snap['price'].get('price')}")
    print(f"📌 change_pct: {snap['price'].get('change_pct')}%")
    print(f"📌 signal_count: {snap['signal_count']}")
    print(f"📌 source_files: {len(snap.get('source_files', []))}")
    for f in snap.get('source_files', [])[:5]:
        print(f"   - {f}")

    banner(f'2. get_data_sources')
    from app.services.mirofish import get_data_sources
    ds = get_data_sources()
    print(f'mode: {ds.get("mode")}')
    for f in ds.get('files', []):
        if f.get('exists'):
            print(f"  ✓ {f['file']} ({f.get('bytes', 0):,} bytes)")
        else:
            print(f"  ✗ {f['file']} (missing)")

    banner(f'3. get_status')
    from app.services.mirofish import get_status
    status = get_status()
    print(f"service: {status['service']}")
    print(f"ready: {status['ready']}")
    print(f"mode: {status['mode']}")
    print(f"brain.score: {status['brain'].get('score')}")
    print(f"brain.regime: {status['brain'].get('regime')}")
    print(f"pipeline.graph_links: {status['pipeline'].get('graph_links')}")

    banner(f'4. create_run (mode={mode}) — 전체 파이프라인')
    from app.services.mirofish import create_run
    t0 = time.time()
    try:
        run = create_run({'target': '삼성전자', 'agent_count': 7, 'mode': mode})
    except Exception as e:
        import traceback
        print(f'❌ ERROR: {type(e).__name__}: {e}')
        traceback.print_exc()
        sys.exit(1)
    elapsed = time.time() - t0
    print(f'⏱️  {elapsed:.2f}s')

    print(f"\n📦 run.id: {run.get('id')}")
    print(f"📦 target: {run.get('target')}")
    print(f"📦 symbol: {run.get('symbol')}")
    print(f"📦 mode: {run.get('mode')}")
    print(f"📦 source: {run.get('source')}")
    print(f"📦 status: {run.get('status')}")
    print(f"📦 price: {run.get('price')} ({run.get('change_pct')}%)")

    print(f"\n🧠 brain.score: {run['brain'].get('score')}")
    print(f"🧠 brain.regime: {run['brain'].get('regime')}")

    print(f"\n📊 layers ({len(run.get('layers', []))})")
    for layer in run.get('layers', []):
        print(f"   - {layer['label']}: {layer['count']}")

    print(f"\n👥 analysts ({len(run.get('analysts', []))})")
    for a in run['analysts'][:7]:
        print(f"   - {a.get('name')} [{a.get('stance')} → {a.get('verdict')}] "
              f"{int((a.get('confidence') or 0) * 100)}%")
        msg = (a.get('message') or '')[:100]
        if msg:
            print(f"     \"{msg}\"")

    print(f"\n🎯 verdict")
    v = run['verdict']
    print(f"   action: {v.get('action')} ({v.get('confidence_pct')}%)")
    print(f"   bull/neut/bear: {v.get('bullish')}/{v.get('neutral')}/{v.get('bearish')}")
    print(f"   summary: {v.get('summary', '')[:200]}")
    if v.get('reasoning'):
        print(f"   reasoning: {v['reasoning'][:200]}")

    print(f"\n📝 logs ({len(run.get('logs', []))})")
    for log in run.get('logs', [])[:7]:
        print(f"   [{log.get('phase')}] {log.get('text') or log.get('message')}")

    print(f"\n📁 graph_extraction.method: {run['graph_extraction'].get('method')}")
    print(f"📁 graph_extraction.entities: {len(run['graph_extraction'].get('entities', []))}")
    print(f"📁 graph_extraction.relations: {len(run['graph_extraction'].get('relations', []))}")
    print(f"📁 debate.method: {run['debate'].get('method')}")
    print(f"📁 cio.method: {run['cio'].get('method')}")
    print(f"📁 cio.loops_used: {run['cio'].get('loops_used')}")

    banner(f'5. get_graph(run_id)')
    from app.services.mirofish import get_graph
    graph = get_graph(run['id'])
    if graph is None:
        print('❌ graph.json not found')
        sys.exit(1)
    print(f"nodes: {len(graph.get('nodes', []))}")
    print(f"edges: {len(graph.get('edges', []))}")
    print(f"layers: {[l['id'] for l in graph.get('layers', [])]}")
    layer_counts = {}
    for n in graph.get('nodes', []):
        layer_counts[n.get('layer', '?')] = layer_counts.get(n.get('layer', '?'), 0) + 1
    print(f"layer node counts: {layer_counts}")

    banner(f'6. get_report(run_id)')
    from app.services.mirofish import get_report
    rep = get_report(run['id'])
    if rep is None:
        print('❌ report.md not found')
        sys.exit(1)
    md = rep.get('markdown', '')
    print(f"markdown length: {len(md)} chars")
    print(f"--- First 600 chars ---")
    print(md[:600])

    banner(f'Summary')
    print(f"⏱️  Total create_run: {elapsed:.2f}s")
    print(f"📁 Run dir: data/admin_mirofish/runs/{run['id']}/")
    print(f"✅ ALL PHASES OK")


if __name__ == '__main__':
    main()
