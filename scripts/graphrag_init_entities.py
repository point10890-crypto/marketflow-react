"""GraphRAG entities.db 초기 적재 스크립트.

Phase B 시작 시점 또는 ticker_to_yahoo_map.csv / dart_corp_codes.json 갱신 후
재실행. 멱등.

사용법::

    PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe scripts/graphrag_init_entities.py
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.services.mirofish.graphrag.resolver import populate_from_sources  # noqa: E402


def main() -> int:
    print("[graphrag] populating entities.db from sources …")
    stats = populate_from_sources()
    print("[graphrag] done")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
