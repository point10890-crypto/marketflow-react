# -*- coding: utf-8 -*-
"""거래 비용 공용 모듈 — 검출/페이퍼 성과의 net(비용 후) 지표 산출용.

왕복 기본 0.23% = 증권거래세(매도) + 양방향 위탁수수료 (goodrich_ledger 와 동일 가정).
슬리피지는 실체결 원장이 없어 실측 불가 — env `MIROFISH_SLIPPAGE_PCT` (왕복, %p)
상수로만 가산하며, 미설정 시 0. 실측 불가 항목임은 산출물 data_gaps 에 명시할 것.
"""
from __future__ import annotations

import os

ROUND_TRIP_COST_PCT = 0.23  # 거래세 + 왕복 수수료 (%)


def slippage_pct() -> float:
    raw = os.environ.get('MIROFISH_SLIPPAGE_PCT', '')
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return value if value >= 0 else 0.0


def round_trip_cost_pct() -> float:
    """왕복 총비용(%) = 거래세·수수료 + 슬리피지 상수."""
    return ROUND_TRIP_COST_PCT + slippage_pct()


def net_return_pct(gross_return_pct: float) -> float:
    """단일 왕복 거래의 비용 후 수익률(%)."""
    return float(gross_return_pct) - round_trip_cost_pct()
