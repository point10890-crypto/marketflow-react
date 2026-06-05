"""Verify that KEC is excluded from W/Bullish screener results."""

import json
import os
import time
import urllib.request


token = os.environ.get("MARKETFLOW_ADMIN_TOKEN")
if not token:
    raise SystemExit("MARKETFLOW_ADMIN_TOKEN environment variable is required")

print("=== screener/latest?pattern_class=W (limit=100) ===")
print("First call can take 20-30 seconds while the cache is built.")
t0 = time.time()
req = urllib.request.Request(
    "http://localhost:5001/api/wave/screener/latest?pattern_class=W&limit=100",
    headers={"Authorization": f"Bearer {token}"},
)
r = urllib.request.urlopen(req, timeout=180)
d = json.loads(r.read())
dt = time.time() - t0
print(f"response time: {dt:.1f}s")
print(f"total_before_filter: {d.get('total_before_filter')}")
print(f"signal_count (after filter): {d.get('signal_count')}")
tickers = [s["ticker"] for s in d.get("signals", [])]
print(f"KEC (092220) included: {'092220' in tickers}")

print()
print("TOP 5:")
for s in d.get("signals", [])[:5]:
    print(f"  {s['ticker']} {s['name']} conf={s['best_pattern']['confidence']}")
