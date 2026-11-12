"""채점 지표. 입출력만 있는 순수 함수."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Callable, Sequence


def brier(pairs: Sequence[tuple[float, int]]) -> float:
    return sum((probability - outcome) ** 2 for probability, outcome in pairs) / len(pairs)


def log_loss(pairs: Sequence[tuple[float, int]]) -> float:
    total = sum(math.log(probability) if outcome else math.log(1 - probability) for probability, outcome in pairs)
    return -total / len(pairs)


def calibration(pairs: Sequence[tuple[float, int]], bins: int = 10) -> list[dict[str, Any]]:
    """확률 구간별 표본 수, 평균 확률, 실제 적중률. 표본이 없는 구간은 내지 않는다."""
    grouped: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for probability, outcome in pairs:
        grouped[min(int(probability * bins), bins - 1)].append((probability, outcome))
    return [{'lo': index / bins, 'hi': (index + 1) / bins, 'n': len(items),
             'mean_probability': sum(p for p, _ in items) / len(items),
             'hit_rate': sum(o for _, o in items) / len(items)}
            for index, items in sorted(grouped.items())]


def top_k_precision(rows: Sequence[dict[str, Any]], k: int = 3) -> float | None:
    """기준 시각별로 확률 상위 k개를 골랐을 때의 적중률."""
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row['asof_ts']].append(row)
    picks = [row for day in by_day.values()
             for row in sorted(day, key=lambda item: (-item['probability'], item['stock_code']))[:k]]
    return sum(row['outcome'] for row in picks) / len(picks) if picks else None


def block_bootstrap_ci(rows: Sequence[dict[str, Any]], stat: Callable[[list[dict[str, Any]]], float], *,
                       block_key: str = 'entry_date', n_boot: int = 1000, seed: int = 7,
                       alpha: float = 0.05) -> tuple[float, float]:
    """진입일 단위로 묶어 다시 뽑은 신뢰 구간. 같은 날 진입한 예측은 서로 독립이 아니다."""
    blocks: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        blocks[row[block_key]].append(row)
    groups = [blocks[key] for key in sorted(blocks)]
    rng = random.Random(seed)
    values = sorted(stat([row for _ in groups for row in rng.choice(groups)]) for _ in range(n_boot))
    low = values[int((alpha / 2) * (n_boot - 1))]
    high = values[int((1 - alpha / 2) * (n_boot - 1))]
    return low, high
