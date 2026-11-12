"""표준 사건 판정. 정의는 바꾸지 않는다 — 새 사건은 새 event_id 로 추가한다 (설계서 §5.2).

E1: 기준일 다음 거래일 시가에 진입해 8거래일 안에 +8% 에 닿으면 적중.
    -7% 에 먼저 닿거나, 같은 날 둘 다 닿거나, 8거래일째 종가까지 닿지 못하면 실패.
"""
from __future__ import annotations

from typing import Any

E1_TARGET_PCT = 8.0
E1_STOP_PCT = 7.0
E1_MAX_SESSIONS = 8


def evaluate_e1(bars: list[dict[str, Any]], *, cost_pct: float) -> dict[str, Any] | None:
    """bars: 진입일부터 날짜 오름차순으로 빠짐없이 이어진 봉. 아직 판정할 수 없으면 None."""
    if not bars:
        return None
    entry = float(bars[0]['open'])
    if entry <= 0:
        raise ValueError('entry open must be positive')
    # 가상 매매 엔진(paper_positions)과 같은 자리수로 반올림한다. 안 하면 정확히 닿은 가격에서 판정이 갈린다.
    target = round(entry * (1 + E1_TARGET_PCT / 100.0), 4)
    stop = round(entry * (1 - E1_STOP_PCT / 100.0), 4)

    def done(outcome: int, reason: str, exit_price: float, bar: dict[str, Any]) -> dict[str, Any]:
        gross = (exit_price / entry - 1) * 100.0
        return {'outcome': outcome, 'entry_date': str(bars[0]['date']), 'entry_price': entry,
                'exit_date': str(bar['date']), 'exit_price': exit_price, 'exit_reason': reason,
                'gross_return_pct': gross, 'net_return_pct': gross - float(cost_pct)}

    for held, bar in enumerate(bars[:E1_MAX_SESSIONS], start=1):
        if float(bar['low']) <= stop:
            return done(0, 'stop', stop, bar)
        if float(bar['high']) >= target:
            return done(1, 'target', target, bar)
        if held >= E1_MAX_SESSIONS:
            return done(0, 'expiry', float(bar['close']), bar)
    return None
