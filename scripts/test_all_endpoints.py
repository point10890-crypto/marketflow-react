"""Endpoint sweep tester — tests ALL registered routes via public URL."""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv()

BASE = "https://marketflow-api.bit-man.net"
TOKEN = Path("/tmp/admin_token.txt").read_text().strip()
HEADERS = {"Authorization": f"Bearer {TOKEN}", "User-Agent": "Mozilla/5.0"}

# Param substitution map
SUBS = {
    "stock_code": "005930", "symbol": "BTCUSDT", "pair": "BTC-USDT",
    "ticker": "AAPL", "date": "2026-04-14", "slug": "free",
    "post_id": "25", "comment_id": "25", "board_id": "1",
    "user_id": "3", "id": "1", "filename": "test.jpg",
    "code": "005930", "market": "kospi", "group": "free",
}

def substitute_path(path: str) -> str:
    def repl(m):
        name = m.group(1)
        # handle <int:foo> style
        if ":" in name: name = name.split(":")[1]
        return SUBS.get(name, "1")
    return re.sub(r"<([^>]+)>", repl, path)

def test_endpoint(method: str, path: str):
    url = BASE + substitute_path(path)
    try:
        req = urllib.request.Request(url, headers=HEADERS, method=method)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read()
            return {"status": r.status, "bytes": len(body), "ms": int((time.time()-t0)*1000), "err": None}
    except urllib.error.HTTPError as e:
        body = b""
        try: body = e.read()[:300]
        except: pass
        return {"status": e.code, "bytes": len(body), "ms": int((time.time()-t0)*1000), "err": body.decode(errors='ignore')[:200]}
    except Exception as e:
        return {"status": 0, "bytes": 0, "ms": int((time.time()-t0)*1000), "err": str(e)[:200]}

def main():
    eps_file = Path("/tmp/all_eps.txt")
    lines = eps_file.read_text().strip().split("\n")
    results = []
    for i, line in enumerate(lines):
        parts = line.split(None, 1)
        if len(parts) != 2: continue
        methods_str, path = parts
        methods = [m.strip() for m in methods_str.split(",")]
        # Only test GET for safety; note others as SKIPPED
        if "GET" not in methods:
            results.append({"method": methods_str, "path": path, "status": "SKIP", "bytes": 0, "ms": 0, "err": "write-op"})
            continue
        r = test_endpoint("GET", path)
        r["method"] = "GET"
        r["path"] = path
        results.append(r)
        print(f"[{i+1:3d}/{len(lines)}] {r['status']:>4} {r['bytes']:>7}b {r['ms']:>5}ms  GET {path}", flush=True)
    # Summary
    Path("/tmp/test_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    tot = [r for r in results if r.get("status") != "SKIP"]
    by_status = {}
    for r in tot:
        k = r["status"]
        by_status[k] = by_status.get(k, 0) + 1
    print("\n=== SUMMARY ===")
    print(f"Total tested: {len(tot)}  Skipped (write-op): {len(results)-len(tot)}")
    for k in sorted(by_status, key=str):
        print(f"  {k}: {by_status[k]}")
    fails = [r for r in tot if r.get("status") not in (200, 401, 403)]
    print(f"\n=== CRITICAL FAILS ({len(fails)}) ===")
    for r in fails:
        err_snip = (r.get("err") or "")[:120].replace("\n", " ")
        print(f"  [{r['status']}] GET {r['path']}  err={err_snip}")

if __name__ == "__main__":
    main()
