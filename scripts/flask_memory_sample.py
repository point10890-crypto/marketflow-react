"""Flask 메모리 누수 진단용 5분 주기 샘플러.

매 호출:
1. /_debug/memory 응답 수집 (admin token)
2. data/admin_mirofish/graphrag/audit/memory_samples.jsonl 에 append
3. RSS 변동량 + GC 객체 변동량 콘솔 출력

miniPC 스케줄러로 5분마다 호출하거나, 수동 모니터링용으로 사용.

사용법::

    PYTHONIOENCODING=utf-8 .venv\\Scripts\\python.exe scripts\\flask_memory_sample.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request


SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'data', 'admin_mirofish', 'graphrag', 'audit', 'memory_samples.jsonl',
)
TOKEN = os.environ.get('GRAPHRAG_ADMIN_TOKEN', '3:1781219291:0e324300d1e528dd932d4c19ddec0792')
URL = os.environ.get('GRAPHRAG_DEBUG_URL', 'http://localhost:5001/api/admin/mirofish/_debug/memory')


def _fetch() -> dict:
    req = urllib.request.Request(URL, headers={
        'Authorization': f'Bearer {TOKEN}',
        'Accept': 'application/json',
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def _delta_summary(current: dict, previous: dict | None) -> str:
    if not previous:
        return '(baseline)'
    cur_rss = current.get('process', {}).get('rss_mb', 0) or 0
    prev_rss = previous.get('process', {}).get('rss_mb', 0) or 0
    cur_gc = current.get('gc', {}).get('objects_tracked', 0) or 0
    prev_gc = previous.get('gc', {}).get('objects_tracked', 0) or 0
    delta_rss = cur_rss - prev_rss
    delta_gc = cur_gc - prev_gc
    return f'ΔRSS={delta_rss:+.1f}MB Δgc_objects={delta_gc:+d}'


def _read_last_sample() -> dict | None:
    if not os.path.exists(SAMPLE_PATH):
        return None
    try:
        with open(SAMPLE_PATH, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            chunk = 8192
            f.seek(max(0, size - chunk))
            lines = f.read().decode('utf-8', errors='replace').splitlines()
            if not lines:
                return None
            return json.loads(lines[-1])
    except Exception:
        return None


def main() -> int:
    os.makedirs(os.path.dirname(SAMPLE_PATH), exist_ok=True)
    prev = _read_last_sample()
    try:
        sample = _fetch()
    except Exception as exc:
        print(f'[memory-sample] FAIL: {exc}')
        return 1

    rss = sample.get('process', {}).get('rss_mb')
    threads = sample.get('process', {}).get('threads')
    uptime = sample.get('process', {}).get('uptime_sec', 0)
    gc_objs = sample.get('gc', {}).get('objects_tracked')
    price_present = sample.get('caches', {}).get('price_history', {}).get('present')
    price_symbols = sample.get('caches', {}).get('price_history', {}).get('symbol_count', 0)
    halted = sample.get('caches', {}).get('halted', {}).get('entries', 0)
    us_preview = sample.get('caches', {}).get('us_preview', {}).get('entries', 0)
    delta = _delta_summary(sample, prev)

    # JSONL append
    with open(SAMPLE_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps({
            'ts': time.time(),
            'iso': sample.get('asof'),
            'rss_mb': rss,
            'threads': threads,
            'uptime_sec': uptime,
            'gc_objects': gc_objs,
            'price_cache_present': bool(price_present),
            'price_cache_symbols': price_symbols,
            'halted_cache_entries': halted,
            'us_preview_entries': us_preview,
            'pid': sample.get('process', {}).get('pid'),
        }, ensure_ascii=False) + '\n')

    print(
        f"[memory-sample] PID={sample.get('process', {}).get('pid')} "
        f"RSS={rss}MB threads={threads} uptime={uptime}s "
        f"gc_objs={gc_objs} price_cache={'Y' if price_present else 'N'} "
        f"halted={halted} us_preview={us_preview} | {delta}"
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
