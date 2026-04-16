import sys, os, asyncio
ROOT = r"C:\bitman_marketfloww"
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)
from engine.generator import run_screener
print("[START] V2 analysis", flush=True)
try:
    result = asyncio.run(run_screener(capital=50_000_000))
    print(f"[DONE] filtered={getattr(result,'filtered_count', '?')}", flush=True)
except Exception as e:
    import traceback
    print(f"[FAIL] {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
