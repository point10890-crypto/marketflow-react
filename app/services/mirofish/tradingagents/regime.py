"""Brain 13D → TradingAgents 레짐 컨텍스트 정규화.

`regime_context(brain)` 는 Brain 13D 스냅샷을 다음으로 축약한다:
    {regime, alignment, direction('bull'|'bear'|'neutral'), adjustment(float),
     line(str, 프롬프트 주입용 1줄 — 브레인 없으면 '')}
env 는 import 시점에 읽어 상수화(테스트는 reload 로 검증).
"""
from __future__ import annotations

import os
from typing import Any

_BULL = {'constructive_bullish', 'constructive_accumulation'}
_BEAR = {'defensive_caution', 'risk_off'}
_LABEL_KO = {
    'constructive_bullish': '강세',
    'constructive_accumulation': '완만 강세(매집)',
    'neutral_balanced': '중립',
    'defensive_caution': '방어',
    'risk_off': '위험회피',
    'unknown': '불명',
    'data_unavailable': '데이터없음',
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(os.getenv(name, default)).strip())
    except (TypeError, ValueError):
        return default


_BOOST = _env_float('MIROFISH_TA_REGIME_BOOST', 5.0)
_PENALTY = _env_float('MIROFISH_TA_REGIME_PENALTY', 5.0)
_ALIGN_MIN = _env_float('MIROFISH_TA_REGIME_ALIGN_MIN', 0.55)


def regime_context(brain: dict[str, Any] | None) -> dict[str, Any]:
    if not brain:
        return {'regime': 'unknown', 'alignment': None, 'direction': 'neutral',
                'adjustment': 0.0, 'line': ''}
    regime = str(brain.get('regime') or 'unknown')
    alignment = _safe_float(brain.get('alignment_score'))
    if regime in _BULL:
        direction = 'bull'
    elif regime in _BEAR:
        direction = 'bear'
    else:
        direction = 'neutral'

    if direction == 'bull' and alignment is not None and alignment >= _ALIGN_MIN:
        adjustment = _BOOST
    elif direction == 'bear':
        adjustment = -_PENALTY
    else:
        adjustment = 0.0

    return {'regime': regime, 'alignment': alignment, 'direction': direction,
            'adjustment': float(adjustment), 'line': _line(regime, alignment)}


def _line(regime: str, alignment: float | None) -> str:
    ko = _LABEL_KO.get(regime, regime)
    al = f'{alignment:.2f}' if alignment is not None else 'N/A'
    return f'시장 레짐: {ko}({regime}, 정렬 {al}). 종목 근거를 우선하되 레짐을 감안하라.'


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ''):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
