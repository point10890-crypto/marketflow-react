"""키움 AI전략 테마 랭커 (주도주LIVE 보강)
- 7개 AI전략 조건식 순차 실행 → 중복 제거 → hit_count 기반 랭킹
- Rate limit: 조건식당 1분 1회 → seq당 10초 간격
- 장중만 동작. 장외/권한 미비 시 빈 결과 반환 (비파괴)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from engine.kiwoom_screener import (
    fetch_condition_candidates,
    KiwoomScreenerError,
)
from engine.kiwoom_client import get_token

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
OUTPUT_FILE = os.path.join(DATA_DIR, "kiwoom_ai_theme_latest.json")

# AI전략 7개 조건식 (seq, 이름)
AI_THEMES = [
    ("0", "AI전략(종가매매)"),
    ("1", "AI전략(종가매매2)"),
    ("2", "AI전략(BNF 강력매수)"),
    ("36", "AI가만든(노스트라다무스)"),
    ("86", "AI전략 스윙매매"),
    ("89", "AI전략(올라운드 단기)"),
    ("90", "AI전략(Super Agent)"),
]

SEQ_INTERVAL_SEC = 10  # rate limit 대응 (조건식당 1/분)


async def fetch_ai_theme_ranking(top_n: int = 15) -> dict:
    """7개 AI전략 조건식 순차 실행 → 중복 제거 → 랭킹.

    Returns:
        {
            "updated_at": ISO8601,
            "total_conditions": 7,
            "executed": N,
            "unique_stocks": N,
            "stocks": [
                {code, name, change_pct, price, volume,
                 hit_count, matched_conditions: [이름...]}
            ]
        }
    """
    token = get_token()
    if not token:
        return _empty_result("no token")

    # {code: {meta + hit 정보}}
    hits: dict[str, dict] = {}
    executed = 0

    for seq, theme_name in AI_THEMES:
        try:
            rows = await fetch_condition_candidates(seq=seq, token=token)
            executed += 1
            for r in rows:
                code = r.get("code")
                if not code:
                    continue
                if code not in hits:
                    hits[code] = {
                        "code": code,
                        "name": r.get("name") or "",
                        "price": r.get("price"),
                        "change_pct": r.get("change_pct"),
                        "volume": r.get("volume"),
                        "hit_count": 0,
                        "matched_conditions": [],
                    }
                hits[code]["hit_count"] += 1
                hits[code]["matched_conditions"].append(theme_name)
        except (asyncio.TimeoutError, KiwoomScreenerError, OSError) as e:
            logger.warning("[theme_ranker] seq=%s(%s) 실패: %s", seq, theme_name, e)
        except Exception as e:
            logger.warning("[theme_ranker] seq=%s(%s) 예외: %s", seq, theme_name, e)

        # rate limit
        if seq != AI_THEMES[-1][0]:
            await asyncio.sleep(SEQ_INTERVAL_SEC)

    # 정렬: hit_count desc, change_pct desc
    def _pct(v):
        try:
            return float(str(v or "0").replace("+", "").strip())
        except (ValueError, TypeError):
            return 0.0

    ranked = sorted(
        hits.values(),
        key=lambda s: (s["hit_count"], _pct(s["change_pct"])),
        reverse=True,
    )[:top_n]

    # change_pct를 float로 정규화
    for s in ranked:
        s["change_pct"] = _pct(s["change_pct"])

    result = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total_conditions": len(AI_THEMES),
        "executed": executed,
        "unique_stocks": len(hits),
        "stocks": ranked,
    }
    return result


def _empty_result(reason: str) -> dict:
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total_conditions": len(AI_THEMES),
        "executed": 0,
        "unique_stocks": 0,
        "stocks": [],
        "error": reason,
    }


async def update_ai_theme_ranking(top_n: int = 15) -> dict:
    """랭킹 실행 + JSON 저장 (비파괴)."""
    try:
        result = await fetch_ai_theme_ranking(top_n=top_n)
    except Exception as e:
        logger.exception("[theme_ranker] update 실패")
        result = _empty_result(f"{type(e).__name__}: {e}")

    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = OUTPUT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUTPUT_FILE)
    return result


def load_latest() -> Optional[dict]:
    """저장된 최신 랭킹 JSON 읽기."""
    if not os.path.exists(OUTPUT_FILE):
        return None
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ─── CLI ───
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _main():
        print("=== 키움 AI전략 테마 랭커 ===")
        t0 = time.time()
        result = await update_ai_theme_ranking(top_n=15)
        elapsed = time.time() - t0
        print(f"\n조건식 {result['executed']}/{result['total_conditions']} 실행  "
              f"unique={result['unique_stocks']}  elapsed={elapsed:.1f}s")
        if result.get("error"):
            print(f"  * error: {result['error']}")
        print(f"\nTop {len(result['stocks'])}:")
        for i, s in enumerate(result["stocks"], 1):
            conds = ",".join(c.replace("AI전략", "").replace("(", "").replace(")", "")[:8]
                             for c in s["matched_conditions"][:3])
            print(f"  {i:2d}. [{s['hit_count']}/7] {s['code']}  {s['name']:12}  "
                  f"{s['change_pct']:+6.2f}%  price={s['price']}  |  {conds}")
        print(f"\n저장: {OUTPUT_FILE}")

    asyncio.run(_main())
