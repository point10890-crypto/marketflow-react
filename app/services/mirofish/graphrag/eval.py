"""GraphRAG benchmark harness (replay-safe).

청사진 §10.6 Phase F.

look-ahead bias 방지: signal_date 이후의 close 만 forward 수익률 계산에 사용.
외부 의존성 없음 (numpy/pandas 미사용 — 표준 라이브러리만).

평가 데이터셋 (구현 우선순위):
  1. jongga_v2_replay (기본, 자체 archive)
  2. financebench / finqa (향후, 외부 데이터 도입 시)

산출물: ``data/admin_mirofish/graphrag/eval/eval_<ts>.json``
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any

from app.services.mirofish.graphrag.storage import EVAL_DIR, ensure_dirs
from app.utils.atomic_json import write_json_atomic
from app.utils.paths import DATA_DIR


# ── 상수 ───────────────────────────────────────────────────────────────

PRICE_HISTORY_PATH = os.path.join(DATA_DIR, 'daily_prices.csv')
DEFAULT_HORIZON_DAYS = 5
HIT_THRESHOLD_PCT = 5.0        # 5% 이상 상승 → hit
MISS_THRESHOLD_PCT = -7.0      # -7% 이상 하락 → miss
DEFAULT_LOOKBACK_DAYS = 30     # from_date 미지정 시 사용
ARCHIVE_PATTERN = os.path.join(DATA_DIR, 'jongga_v2_results_*.json')
ARCHIVE_DATE_RE = re.compile(r'jongga_v2_results_(\d{8})\.json$')


# ── Public API ────────────────────────────────────────────────────────

def run_jongga_v2_replay(
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    configs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """jongga_v2 archive 를 evaluation set 으로 사용해 replay-safe 평가 수행.

    각 archive 의 signals[] 을 가져와서:
      1. signal_date 다음 거래일을 entry_date 로 간주 (daily_prices.csv 기반)
      2. entry_date + horizon_days 까지의 close 로 forward return 계산
      3. >= 5% → hit, <= -7% → miss, 그 외 → pending(중립) 처리

    look-ahead safe 규약:
      - signal_date 이후 (>= entry_date) 의 daily_prices 행만 forward 측정에 사용
      - signal 발생 시점에 알 수 없는 데이터 (예: 미래 가격) 는 score/feature 로 사용 X

    Args:
        from_date: 'YYYY-MM-DD' (포함). None 이면 (to_date 또는 오늘) - 30일.
        to_date: 'YYYY-MM-DD' (포함). None 이면 오늘 - horizon_days.
        horizon_days: forward window 길이 (거래일 단위).
        configs: 비교할 setup 들. 각 dict 는 {"name": str, "min_grade": "S"|"A"|"B",
                 "min_score": int} 형태. None 이면 단일 'jongga_v2_base' (모든 signal).

    Returns:
        run summary dict.
    """
    ensure_dirs()
    horizon_days = max(1, int(horizon_days or DEFAULT_HORIZON_DAYS))
    today = datetime.now().strftime('%Y-%m-%d')

    if not to_date:
        to_date = (datetime.now() - timedelta(days=horizon_days)).strftime('%Y-%m-%d')
    if not from_date:
        try:
            anchor = datetime.strptime(to_date, '%Y-%m-%d')
        except ValueError:
            anchor = datetime.now()
        from_date = (anchor - timedelta(days=DEFAULT_LOOKBACK_DAYS)).strftime('%Y-%m-%d')

    config_list = _normalize_configs(configs)
    signals = _load_signals_in_range(from_date, to_date)
    price_index = _load_price_history({_symbol(s.get('stock_code')) for s in signals})

    # config 별 metric 누적
    metrics: dict[str, dict[str, Any]] = {}
    per_signal_outcomes: list[dict[str, Any]] = []

    for cfg in config_list:
        bucket = {
            'config': cfg,
            'evaluated': 0,
            'hits': 0,
            'misses': 0,
            'pending': 0,
            'pairs': [],  # (signal_score, forward_return_pct) for IC
            'returns': [],
        }
        for sig in signals:
            if not _signal_passes_config(sig, cfg):
                continue
            outcome = _evaluate_signal(sig, price_index, horizon_days)
            if cfg.get('name') == config_list[0].get('name'):
                # 첫 config 의 outcome 만 sample 로 저장 (출력 용량 제어)
                per_signal_outcomes.append(outcome)
            status = outcome.get('status')
            if status == 'hit':
                bucket['hits'] += 1
                bucket['evaluated'] += 1
            elif status == 'miss':
                bucket['misses'] += 1
                bucket['evaluated'] += 1
            elif status == 'neutral':
                bucket['evaluated'] += 1  # evaluated 지만 hit/miss 아님
            else:
                bucket['pending'] += 1
            ret = outcome.get('forward_return_pct')
            if ret is not None:
                bucket['returns'].append(float(ret))
                score_total = _signal_score_total(sig)
                if score_total is not None:
                    bucket['pairs'].append((float(score_total), float(ret)))
        metrics[cfg['name']] = _compute_config_metrics(bucket)

    run_id = f"eval_{datetime.now().strftime('%Y%m%d%H%M%S')}"
    run_path = os.path.join(EVAL_DIR, f'{run_id}.json')
    payload = {
        'run_id': run_id,
        'benchmark': 'jongga_v2_replay',
        'from_date': from_date,
        'to_date': to_date,
        'horizon_days': horizon_days,
        'hit_threshold_pct': HIT_THRESHOLD_PCT,
        'miss_threshold_pct': MISS_THRESHOLD_PCT,
        'signal_count': len(signals),
        'configs': config_list,
        'metrics': metrics,
        'sample_outcomes': per_signal_outcomes[:50],
        'price_history_path': os.path.relpath(PRICE_HISTORY_PATH, DATA_DIR).replace('\\', '/'),
        'lookahead_safe': True,
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }
    try:
        write_json_atomic(run_path, payload, sort_keys=False)
        payload['written_to'] = run_path
    except Exception as exc:  # pragma: no cover
        payload['write_error'] = str(exc)
    return payload


def get_eval_history(limit: int = 20) -> list[dict[str, Any]]:
    """저장된 eval 결과 리스트 (최신 우선, 요약만)."""
    ensure_dirs()
    files = sorted(glob.glob(os.path.join(EVAL_DIR, 'eval_*.json')), reverse=True)
    out: list[dict[str, Any]] = []
    for path in files[: max(1, int(limit or 20))]:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            out.append({
                'run_id': data.get('run_id'),
                'benchmark': data.get('benchmark'),
                'from_date': data.get('from_date'),
                'to_date': data.get('to_date'),
                'horizon_days': data.get('horizon_days'),
                'signal_count': data.get('signal_count'),
                'metrics': data.get('metrics'),
                'asof': data.get('asof'),
                'path': path,
            })
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return out


# ── 통계 유틸 ──────────────────────────────────────────────────────────

def _compute_ic(pairs: list[tuple[float, float]]) -> float:
    """Pearson correlation. pairs 가 5개 미만이거나 분산 0 이면 0.0.

    NumPy 의존 회피 — 표준 라이브러리만 사용.
    """
    if not pairs or len(pairs) < 5:
        return 0.0
    n = len(pairs)
    xs = [float(p[0]) for p in pairs]
    ys = [float(p[1]) for p in pairs]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    dx = (sum((x - mx) ** 2 for x in xs)) ** 0.5
    dy = (sum((y - my) ** 2 for y in ys)) ** 0.5
    if dx == 0 or dy == 0:
        return 0.0
    return round(num / (dx * dy), 4)


def _compute_config_metrics(bucket: dict[str, Any]) -> dict[str, Any]:
    evaluated = int(bucket['evaluated'])
    hits = int(bucket['hits'])
    misses = int(bucket['misses'])
    pending = int(bucket['pending'])
    total = evaluated + pending
    returns = bucket['returns']
    avg_ret = round(sum(returns) / len(returns), 2) if returns else None
    return {
        'evaluated_count': evaluated,
        'hit_count': hits,
        'miss_count': misses,
        'pending_count': pending,
        'total_count': total,
        'hit_rate': round(hits / evaluated, 4) if evaluated else 0.0,
        'miss_rate': round(misses / evaluated, 4) if evaluated else 0.0,
        'pending_rate': round(pending / total, 4) if total else 0.0,
        'average_forward_return_pct': avg_ret,
        'ic': _compute_ic(bucket['pairs']),
    }


# ── 내부: signal/price 로딩 ────────────────────────────────────────────

def _normalize_configs(configs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not configs:
        return [{'name': 'jongga_v2_base', 'min_grade': None, 'min_score': None}]
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(configs):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get('name') or f'cfg_{i}').strip() or f'cfg_{i}'
        min_grade = raw.get('min_grade')
        if min_grade and str(min_grade).upper() not in ('S', 'A', 'B'):
            min_grade = None
        min_score = raw.get('min_score')
        try:
            min_score = int(min_score) if min_score is not None else None
        except (TypeError, ValueError):
            min_score = None
        out.append({
            'name': name,
            'min_grade': str(min_grade).upper() if min_grade else None,
            'min_score': min_score,
        })
    return out or [{'name': 'jongga_v2_base', 'min_grade': None, 'min_score': None}]


def _signal_passes_config(signal: dict[str, Any], cfg: dict[str, Any]) -> bool:
    min_grade = cfg.get('min_grade')
    if min_grade:
        order = {'S': 3, 'A': 2, 'B': 1, 'C': 0}
        sig_grade = str(signal.get('grade') or '').upper()
        if order.get(sig_grade, 0) < order.get(min_grade, 0):
            return False
    min_score = cfg.get('min_score')
    if min_score is not None:
        total = _signal_score_total(signal) or 0
        if total < min_score:
            return False
    return True


def _signal_score_total(signal: dict[str, Any]) -> float | None:
    score = signal.get('score')
    if isinstance(score, dict) and score.get('total') is not None:
        try:
            return float(score['total'])
        except (TypeError, ValueError):
            return None
    return None


def _load_signals_in_range(from_date: str, to_date: str) -> list[dict[str, Any]]:
    """jongga_v2_results_YYYYMMDD.json 들에서 signal_date 가 범위 내인 것만 추출."""
    signals: list[dict[str, Any]] = []
    for path in glob.glob(ARCHIVE_PATTERN):
        m = ARCHIVE_DATE_RE.search(os.path.basename(path))
        if not m:
            continue
        ymd = m.group(1)
        try:
            iso = f'{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}'
        except (IndexError, ValueError):
            continue
        if iso < from_date or iso > to_date:
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for sig in (data.get('signals') or []):
            if isinstance(sig, dict) and sig.get('stock_code'):
                signals.append(sig)
    return signals


def _load_price_history(symbols: set[str]) -> dict[str, list[dict[str, Any]]]:
    """daily_prices.csv 에서 지정 symbol 만 적재. 날짜 오름차순 정렬."""
    if not symbols or not os.path.isfile(PRICE_HISTORY_PATH):
        return {}
    rows: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    try:
        with open(PRICE_HISTORY_PATH, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                sym = _symbol(row.get('ticker') or row.get('symbol') or row.get('code'))
                if sym in rows:
                    price = _number(row.get('current_price') or row.get('close') or row.get('price'))
                    if price <= 0:
                        continue
                    rows[sym].append({
                        'date': str(row.get('date') or '')[:10],
                        'close': price,
                    })
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    for sym_rows in rows.values():
        sym_rows.sort(key=lambda r: r['date'])
    return rows


def _evaluate_signal(
    signal: dict[str, Any],
    price_index: dict[str, list[dict[str, Any]]],
    horizon_days: int,
) -> dict[str, Any]:
    """단일 signal forward 평가. signal_date 이후 데이터만 사용."""
    symbol = _symbol(signal.get('stock_code'))
    signal_date = str(signal.get('signal_date') or '')[:10]
    rows = price_index.get(symbol) or []

    base: dict[str, Any] = {
        'stock_code': symbol,
        'stock_name': signal.get('stock_name'),
        'grade': signal.get('grade'),
        'score_total': _signal_score_total(signal),
        'signal_date': signal_date,
        'lookahead_safe': True,
    }

    if not signal_date or not rows:
        return {**base, 'status': 'pending', 'reason': 'no signal_date or no price rows'}

    # signal_date 이후 첫 거래일 진입
    future = [r for r in rows if r['date'] > signal_date]
    if len(future) == 0:
        return {**base, 'status': 'pending', 'reason': 'no future price rows'}

    entry_row = future[0]
    entry_price = entry_row['close']
    target_idx = min(horizon_days - 1, len(future) - 1)
    exit_row = future[target_idx]
    exit_price = exit_row['close']

    if entry_price <= 0:
        return {**base, 'status': 'pending', 'reason': 'invalid entry price'}

    forward_return = round((exit_price - entry_price) / entry_price * 100, 2)
    available_days = len(future)
    insufficient = available_days < horizon_days

    if forward_return >= HIT_THRESHOLD_PCT:
        status = 'hit'
    elif forward_return <= MISS_THRESHOLD_PCT:
        status = 'miss'
    else:
        status = 'neutral'  # evaluated 지만 hit/miss 임계 미달
    if insufficient and status == 'neutral':
        # 데이터 불충분이고 결정적 임계도 안 넘으면 pending 으로 격리
        status = 'pending'

    return {
        **base,
        'status': status,
        'entry_date': entry_row['date'],
        'entry_price': entry_price,
        'exit_date': exit_row['date'],
        'exit_price': exit_price,
        'forward_return_pct': forward_return,
        'horizon_days_requested': horizon_days,
        'horizon_days_available': available_days,
    }


# ── 작은 헬퍼 ──────────────────────────────────────────────────────────

def _symbol(value: Any) -> str:
    s = str(value or '').strip()
    digits = ''.join(ch for ch in s if ch.isdigit())
    if len(digits) == 6:
        return digits
    return s.upper()


def _number(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
