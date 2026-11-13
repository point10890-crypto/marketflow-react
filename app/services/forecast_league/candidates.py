"""1단계 후보 종목 — 그날 종가베팅 V2 가 신호를 낸 종목. 결과 파일은 읽기만 한다.

2단계에서 다른 예측자가 예측한 종목의 합집합으로 넓힌다.
"""
from __future__ import annotations

import json
import os
import re

from app.utils.paths import DATA_DIR

_STOCK_CODE = re.compile(r'[0-9]{6}')


class CandidateSourceUnavailable(RuntimeError):
    """A source error must retry, never become a successful empty scan."""


def jongga_candidates(asof_date: str, data_dir: str | None = None) -> list[str]:
    path = os.path.join(data_dir or DATA_DIR, f"jongga_v2_results_{asof_date.replace('-', '')}.json")
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        raise CandidateSourceUnavailable('candidate_file_unavailable') from None
    signals = payload.get('signals') if isinstance(payload, dict) else None
    if not isinstance(signals, list):
        raise CandidateSourceUnavailable('candidate_schema_invalid')
    codes = {str(item.get('stock_code') or '') for item in signals if isinstance(item, dict)}
    return sorted(code for code in codes if _STOCK_CODE.fullmatch(code))
