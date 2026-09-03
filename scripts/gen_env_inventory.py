#!/usr/bin/env python3
"""코드가 참조하는 환경변수 인벤토리를 출력한다 (.env.example 4절 재생성용).

사용: python scripts/gen_env_inventory.py            # 누락 변수만 stdout
      python scripts/gen_env_inventory.py --all      # 전체
리뷰(2026-09-02): .env.example 7개 vs 코드 참조 256개 — 새 환경 재구축이 불가능했다.
"""
from __future__ import annotations

import collections
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCAN_DIRS = ['app', 'engine', 'us_market', 'marketflow_claw', 'multi_agent',
             'integrations', 'scripts', 'tools', 'econ_indicators']
PATTERN = re.compile(r"os\.(?:getenv|environ\.get|environ)\[?\(?['\"]([A-Z][A-Z0-9_]+)['\"]")


def collect() -> dict[str, set[str]]:
    files = [os.path.join(ROOT, f) for f in os.listdir(ROOT) if f.endswith('.py')]
    for d in SCAN_DIRS:
        for dp, _, fs in os.walk(os.path.join(ROOT, d)):
            files += [os.path.join(dp, f) for f in fs if f.endswith('.py')]
    refs: dict[str, set[str]] = collections.defaultdict(set)
    for path in files:
        try:
            text = open(path, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
        for var in PATTERN.findall(text):
            refs[var].add(rel)
    return refs


def existing_keys() -> set[str]:
    try:
        text = open(os.path.join(ROOT, '.env.example'), encoding='utf-8').read()
    except OSError:
        return set()
    return set(re.findall(r'^#?\s?([A-Z][A-Z0-9_]+)=', text, re.M))


def main() -> int:
    refs = collect()
    known = existing_keys()
    show_all = '--all' in sys.argv
    for var in sorted(refs):
        if not show_all and var in known:
            continue
        files = sorted(refs[var])
        hint = ', '.join(files[:2]) + (f' +{len(files) - 2}' if len(files) > 2 else '')
        print(f'# {var}=    # {hint}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
