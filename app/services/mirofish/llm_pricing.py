"""LLM 토큰 단가표 + 비용 추정 (운영 가시성용, 청구 기준이 아님).

리뷰(2026-09-02): llm_client 메타데이터에 provider/model/latency 만 있고 토큰·비용이
없어 실제 LLM 지출을 어디서도 집계할 수 없었다 (auto_runner 는 고정 $0.07 추정치).
이 모듈은 provider 응답의 usage 를 USD 로 환산한다.

단가는 USD / 1M tokens (input, output). 기본값은 공개 가격표 기준 근사치이며
`MIROFISH_LLM_PRICE_JSON` 환경변수(JSON: {"model": [input, output]})로 덮어쓴다.
모르는 모델은 None 을 돌려주고 비용을 지어내지 않는다.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# (input_usd_per_1m, output_usd_per_1m) — 운영자가 검증·갱신하는 기본값
DEFAULT_PRICE_TABLE: dict[str, tuple[float, float]] = {
    'gpt-4o': (2.50, 10.00),
    'gpt-4o-mini': (0.15, 0.60),
    'gemini-2.5-flash': (0.30, 2.50),
    'gemini-2.0-flash': (0.10, 0.40),
    'claude-haiku-4-5-20251001': (1.00, 5.00),
    'deepseek-chat': (0.27, 1.10),
}

_override_cache: dict[str, tuple[float, float]] | None = None


def price_table() -> dict[str, tuple[float, float]]:
    global _override_cache
    if _override_cache is not None:
        return _override_cache
    table = dict(DEFAULT_PRICE_TABLE)
    raw = os.getenv('MIROFISH_LLM_PRICE_JSON', '').strip()
    if raw:
        try:
            loaded = json.loads(raw)
            for model, pair in (loaded or {}).items():
                table[str(model)] = (float(pair[0]), float(pair[1]))
        except Exception as exc:  # noqa: BLE001 — 잘못된 오버라이드는 기본표로 계속
            logger.warning('[llm_pricing] MIROFISH_LLM_PRICE_JSON ignored: %s', type(exc).__name__)
    _override_cache = table
    return table


def reset_price_cache() -> None:
    global _override_cache
    _override_cache = None


def lookup_price(model: str | None) -> tuple[float, float] | None:
    """정확 일치 → 접두 일치(버전 접미사 무시) 순으로 찾는다."""
    if not model:
        return None
    table = price_table()
    if model in table:
        return table[model]
    best = None
    for key, pair in table.items():
        if model.startswith(key) and (best is None or len(key) > len(best[0])):
            best = (key, pair)
    return best[1] if best else None


def estimate_cost_usd(model: str | None, usage: dict[str, Any] | None) -> float | None:
    if not usage:
        return None
    price = lookup_price(model)
    if price is None:
        return None
    prompt = float(usage.get('prompt_tokens') or 0)
    completion = float(usage.get('completion_tokens') or 0)
    return round((prompt * price[0] + completion * price[1]) / 1_000_000, 6)


def normalize_usage(prompt_tokens: Any, completion_tokens: Any) -> dict[str, int] | None:
    try:
        p = int(prompt_tokens or 0)
        c = int(completion_tokens or 0)
    except (TypeError, ValueError):
        return None
    if p <= 0 and c <= 0:
        return None
    return {'prompt_tokens': p, 'completion_tokens': c, 'total_tokens': p + c}
