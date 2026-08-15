# -*- coding: utf-8 -*-
"""main_kr.py 의 STOCKS 목록을 현재 KRX 상장 기준으로 재생성한다.

배경: 목록이 하드코딩이라 시간이 지나며 썩는다. 2026-08-15 점검에서 상장폐지된
쌍용C&E(003410) 가 매 회차 yfinance 조회를 실패시키고 ETF(KODEX 200) 까지
섞여 있었다. 분기에 한 번 정도 이 스크립트로 갱신하면 된다.

구성: 코스피 시총 상위 75 + 코스닥 시총 상위 25 (기존 비율 유지).
우선주·스팩·ETF 는 제외한다 — 종목코드 끝자리 0 이 보통주 규칙.

    python scripts/refresh_kr_chart_universe.py          # 미리보기 (변경 없음)
    python scripts/refresh_kr_chart_universe.py --write  # main_kr.py 갱신
"""
from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TARGET = BASE_DIR / "main_kr.py"

KOSPI_COUNT = 75
KOSDAQ_COUNT = 25
_BLOCK_START = "# ── 종목 리스트"
_BLOCK_END = "\n}\n"


def fetch_universe():
    import FinanceDataReader as fdr

    krx = fdr.StockListing("KRX")
    krx = krx[krx["Market"].isin(["KOSPI", "KOSDAQ", "KOSDAQ GLOBAL"])]
    common = krx[
        krx["Code"].str.fullmatch(r"\d{6}")
        & krx["Code"].str.endswith("0")          # 보통주 (우선주 배제)
        & ~krx["Name"].str.contains("스팩")
    ]
    kospi = common[common["Market"] == "KOSPI"].nlargest(KOSPI_COUNT, "Marcap")
    kosdaq = common[common["Market"] != "KOSPI"].nlargest(KOSDAQ_COUNT, "Marcap")
    return kospi, kosdaq


def render_block(kospi, kosdaq) -> str:
    def rows(sub, suffix):
        cells = [f'"{r.Code}.{suffix}": "{r.Name}"' for r in sub.itertuples()]
        return [f"    {', '.join(cells[i:i + 3])}," for i in range(0, len(cells), 3)]

    lines = [f"    # 코스피 (시총 상위 {KOSPI_COUNT})"]
    lines += rows(kospi, "KS")
    lines.append(f"    # 코스닥 (시총 상위 {KOSDAQ_COUNT})")
    lines += rows(kosdaq, "KQ")
    header = (
        f"# ── 종목 리스트 (코스피 상위 {KOSPI_COUNT} + 코스닥 상위 {KOSDAQ_COUNT}) ──\n"
        f"# {datetime.date.today().isoformat()} KRX 상장 기준으로 재생성.\n"
        "# 갱신: scripts/refresh_kr_chart_universe.py --write\n"
    )
    return header + "STOCKS = {\n" + "\n".join(lines) + "\n}\n"


def current_codes(text: str) -> set[str]:
    body = text.split("STOCKS = {", 1)[1].split("\n}", 1)[0]
    return {m.group(1) for m in re.finditer(r'"(\d{6})\.[KQS]{2}"', body)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="main_kr.py 를 실제로 갱신")
    args = parser.parse_args()

    src = TARGET.read_text(encoding="utf-8")
    kospi, kosdaq = fetch_universe()
    if len(kospi) < KOSPI_COUNT or len(kosdaq) < KOSDAQ_COUNT:
        print(f"[abort] 상장 목록이 부족합니다 (KOSPI {len(kospi)}, KOSDAQ {len(kosdaq)})")
        return 1

    block = render_block(kospi, kosdaq)
    new_codes = current_codes(block)
    old_codes = current_codes(src)
    print(f"신규 편입 {len(new_codes - old_codes)}종목 / 제외 {len(old_codes - new_codes)}종목")

    if not args.write:
        print("(미리보기 — 적용하려면 --write)")
        return 0

    start = src.index(_BLOCK_START)
    end = src.index(_BLOCK_END, start) + len(_BLOCK_END)
    TARGET.write_text(src[:start] + block + src[end:], encoding="utf-8")
    print(f"갱신 완료: {TARGET} ({len(new_codes)}종목)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
