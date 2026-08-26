"""레짐 분류 + HALT 판정.

HALT 는 '주도주 소스가 죽었고 레짐 입력도 없다' 또는 '소스가 오류' 일 때.
HALT 중에는 reporter 가 방향성 문구를 만들 수 없다.
"""
from __future__ import annotations

from typing import Any

GATE_TO_REGIME = {'GREEN': 'RISK_ON', 'YELLOW': 'NEUTRAL', 'RED': 'RISK_OFF'}
LEADERS_STALE_SECONDS = 300
GATE_STALE_HOURS = 24 * 3


def evaluate(snapshot: dict[str, Any], gate: dict[str, Any], *, market_open: bool) -> dict[str, Any]:
    reasons: list[str] = []
    regime = GATE_TO_REGIME.get((gate or {}).get('status') or '', 'UNKNOWN')
    gate_stale = not gate.get('available') or (gate.get('age_hours') or 0) > GATE_STALE_HOURS
    if gate_stale:
        reasons.append('market_gate stale/missing')

    src_error = bool(snapshot.get('error'))
    src_stale = market_open and (snapshot.get('file_age_s') or 0) > LEADERS_STALE_SECONDS
    if src_error:
        reasons.append(f"leaders source error: {snapshot.get('error')}")
    if src_stale:
        reasons.append(f"leaders file stale {snapshot.get('file_age_s')}s")

    rows = [r for r in (snapshot.get('rows') or []) if not r.get('detection_unknown')]
    leaders = [r for r in rows if r.get('grade') in ('S', 'A')]
    up = sum(1 for r in rows if (r.get('chg') or 0) > 0)
    breadth = round(100 * up / len(rows)) if rows else None

    halt = src_error or (src_stale and gate_stale)
    return {
        'regime': regime,
        'gate_status': gate.get('status'),
        'gate_score': gate.get('score'),
        'gate_age_hours': gate.get('age_hours'),
        'kospi_close': gate.get('kospi_close'),
        'breadth_pct': breadth,
        'leader_count': len(leaders),
        'halt': bool(halt),
        'reasons': reasons,
    }
