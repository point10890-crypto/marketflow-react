"""채점 지표. 입출력만 있는 순수 함수."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any, Callable, Hashable, Sequence

MIN_BLOCKS = 20


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


def closed_cohorts(rows: Sequence[dict[str, Any]], key: Callable[[dict[str, Any]], Hashable]
                   ) -> list[list[dict[str, Any]]]:
    """key 가 같은 행을 한 코호트로 묶어, 미청산(status 가 None) 행이 하나도 없는 코호트만 돌려준다.

    조기 청산분만 먼저 집계하면 적중률이 부풀므로, 코호트는 전원이 청산(또는 void)된 뒤에만 쓴다.
    """
    cohorts: dict[Hashable, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cohorts[key(row)].append(row)
    return [members for members in cohorts.values() if all(row['status'] is not None for row in members)]


def _rank_key(row: dict[str, Any]) -> tuple[float, bool, float]:
    raw_score = row.get('raw_score')
    return -row['probability'], raw_score is None, -(raw_score or 0.0)


def top_k_precision(rows: Sequence[dict[str, Any]], k: int = 3) -> float | None:
    """day 별로 확률(같으면 raw_score, 없으면 맨 뒤) 상위 k개를 골랐을 때의 적중률.

    k개 이하인 날은 전부 쓴다. k번째와 k+1번째가 동률이면 고를 근거가 없으므로 그날은 뺀다.
    """
    by_day: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_day[row['day']].append(row)
    picks: list[dict[str, Any]] = []
    for day in by_day.values():
        ranked = sorted(day, key=_rank_key)
        if len(ranked) > k and _rank_key(ranked[k - 1]) == _rank_key(ranked[k]):
            continue
        picks.extend(ranked[:k])
    return sum(row['outcome'] for row in picks) / len(picks) if picks else None


def block_bootstrap_ci(rows: Sequence[dict[str, Any]], stat: Callable[[list[dict[str, Any]]], float], *,
                       block_key: str = 'entry_date', n_boot: int = 1000, seed: int = 7,
                       alpha: float = 0.05) -> tuple[float, float] | None:
    """진입일 단위로 묶어 다시 뽑은 신뢰 구간. 같은 날 진입한 예측은 서로 독립이 아니다.

    서로 다른 블록이 MIN_BLOCKS 개보다 적으면 None. 인접한 진입일은 최대 8거래일 동안 보유 구간이
    겹치므로, 이 구간은 불확실성을 낙관적으로(좁게) 잡은 하한이다.
    """
    blocks: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        blocks[row[block_key]].append(row)
    if len(blocks) < MIN_BLOCKS:
        return None
    groups = [blocks[key] for key in sorted(blocks)]
    rng = random.Random(seed)
    values = sorted(stat([row for _ in groups for row in rng.choice(groups)]) for _ in range(n_boot))
    low = values[int((alpha / 2) * (n_boot - 1))]
    high = values[int((1 - alpha / 2) * (n_boot - 1))]
    return low, high
