# -*- coding: utf-8 -*-
"""Detection Alpha Lab — 과거 검출을 리플레이해 규칙 변형의 실측 수익률을 비교한다.

목적: "검출이 실제로 얼마나 버는가"를 추측이 아니라 실측으로. 과거 워크플로우의
CIO BUY 검출 전체를 포지션 엔진과 같은 의미론(다음 거래일 시가 진입, 손절 우선)
으로 리플레이하고, 진입 게이트(레짐/Stage2)와 청산 방식(고정%/ATR)을 A/B 한다.

lookahead 금지가 제1 원칙이다 (tests/test_detection_lab.py 로 고정):
- 진입: 검출 **다음** 거래일 시가
- 필터: 검출일까지의 데이터만 (레짐 timeline 은 원래 lookahead-safe)
- ATR: 진입 **전일까지** 14일 TR 평균

읽기 전용 — 라이브 검출/원장은 건드리지 않는다.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WORKFLOWS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'workflows')
DETECTION_LAB_METHOD_VERSION = 'mirofish.detection_lab.replay.v3.1'
PHASE_MAX_AGE_DAYS = 7
KNOWN_PHASES = frozenset({
    'uptrend_broadening', 'leader_market', 'downtrend', 'rebound_early',
})


def live_phase_gate_blocked() -> frozenset[str]:
    """Read the paper engine's gate set without duplicating policy constants.

    The dependency is deliberately one-way and local: ``paper_positions`` does
    not import the lab, so the validation harness follows LIVE semantics without
    creating a circular import or changing the paper engine.
    """
    from app.services.mirofish.paper_positions import PHASE_GATE_BLOCKED
    return frozenset(str(phase) for phase in PHASE_GATE_BLOCKED)


def phase_as_of(detection_date: str, phase_by_date: dict[str, str] | None,
                *, max_age_days: int = PHASE_MAX_AGE_DAYS) -> tuple[str, int | None]:
    """Resolve the latest non-future phase and return ``(phase, age_days)``.

    Weekend/holiday detections legitimately have no same-date EOD row.  A
    bounded as-of join uses the latest prior trading date without lookahead;
    inputs older than ``max_age_days`` fail as uncovered instead of silently
    carrying a stale regime forward.
    """
    phase_by_date = phase_by_date or {}
    try:
        target = date_type.fromisoformat(str(detection_date or ''))
    except ValueError:
        return '', None
    dates = sorted(str(item) for item in phase_by_date)
    index = bisect_right(dates, target.isoformat()) - 1
    if index < 0:
        return '', None
    selected_date = dates[index]
    try:
        age_days = (target - date_type.fromisoformat(selected_date)).days
    except ValueError:
        return '', None
    if age_days < 0 or age_days > max_age_days:
        return '', age_days
    return str(phase_by_date.get(selected_date) or ''), age_days


@dataclass
class RuleSet:
    """리플레이 규칙 변형. 기본값 = 라이브 엔진 현행."""
    name: str = 'baseline'
    # 진입 게이트
    regime_gate: bool = False        # V1: LIVE paper phase gate와 동일 국면 스킵
    stage2_filter: bool = False      # V2: 종가 > 150MA & 150MA 상승 중일 때만
    # 청산
    exit_mode: str = 'fixed'         # 'fixed' | 'atr'  (V3)
    target_pct: float = 8.0
    stop_pct: float = 7.0
    atr_target_mult: float = 2.0
    atr_stop_mult: float = 1.5
    atr_window: int = 14
    max_hold_days: int = 8
    extra: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 과거 검출 수집
# ─────────────────────────────────────────────────────────────────────────────

def collect_historical_detections() -> list[dict[str, Any]]:
    """워크플로우 전수 스캔 → CIO BUY 검출. (date, symbol) 중복 제거, 날짜 오름차순."""
    detections: dict[tuple[str, str], dict[str, Any]] = {}
    if not os.path.isdir(WORKFLOWS_ROOT):
        return []
    for name in sorted(os.listdir(WORKFLOWS_ROOT)):
        path = os.path.join(WORKFLOWS_ROOT, name, 'workflow.json')
        if name.startswith(('_', '.')) or not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                workflow = json.load(f)
        except (OSError, ValueError):
            continue
        date = str(workflow.get('created_at') or '')[:10]
        if not date:
            continue
        for item in (workflow.get('top3') or []):
            if not isinstance(item, dict):
                continue
            verdict = item.get('verdict') if isinstance(item.get('verdict'), dict) else {}
            if str(verdict.get('action') or '').upper() != 'BUY':
                continue
            symbol = str(item.get('symbol') or '').strip()
            if not symbol:
                continue
            key = (date, symbol)
            if key in detections:
                continue
            detections[key] = {
                'date': date,
                'symbol': symbol,
                'name': str(verdict.get('target') or symbol),
                'score': item.get('final_score'),
                'workflow_id': str(workflow.get('id') or name),
            }
    return sorted(detections.values(), key=lambda d: (d['date'], d['symbol']))


# ─────────────────────────────────────────────────────────────────────────────
# 2) 지표 계산 유틸 (lookahead-safe)
# ─────────────────────────────────────────────────────────────────────────────

def _atr(bars: list[dict[str, Any]], window: int) -> float | None:
    """마지막 window 개 봉의 평균 True Range. bars 는 '진입 전일까지'만 넘길 것."""
    if len(bars) < 2:
        return None
    trs = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        high, low = float(cur['high']), float(cur['low'])
        prev_close = float(prev['close'])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    tail = trs[-window:]
    return sum(tail) / len(tail) if tail else None


def _stage2_ok(bars_upto_detection: list[dict[str, Any]], *, ma_window: int = 150,
               slope_lookback: int = 20) -> bool:
    """미너비니 Stage 2: 종가 > 150MA(≈30주선) AND 150MA 상승 중."""
    closes = [float(b['close']) for b in bars_upto_detection]
    if len(closes) < ma_window + slope_lookback:
        return False
    ma_now = sum(closes[-ma_window:]) / ma_window
    ma_prev = sum(closes[-ma_window - slope_lookback:-slope_lookback]) / ma_window
    return closes[-1] > ma_now and ma_now > ma_prev


def _simulate_exit(bars_from_entry: list[dict[str, Any]], entry_price: float,
                   target: float, stop: float, max_hold: int) -> dict[str, Any] | None:
    """포지션 엔진과 동일 의미론: 손절(저가) > 익절(고가) > 만료(종가)."""
    for held, bar in enumerate(bars_from_entry, start=1):
        low, high, close = float(bar['low']), float(bar['high']), float(bar['close'])
        date = str(bar['date'])
        if low <= stop:
            return {'exit_date': date, 'exit_price': stop, 'exit_reason': 'stop', 'holding_days': held}
        if high >= target:
            return {'exit_date': date, 'exit_price': target, 'exit_reason': 'target', 'holding_days': held}
        if held >= max_hold:
            return {'exit_date': date, 'exit_price': close, 'exit_reason': 'expiry', 'holding_days': held}
    return None  # 데이터 부족 — 미완결 (표본에서 제외)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 리플레이
# ─────────────────────────────────────────────────────────────────────────────

def replay(detections: list[dict[str, Any]],
           price_series: dict[str, list[dict[str, Any]]],
           rules: RuleSet,
           phase_by_date: dict[str, str] | None = None) -> dict[str, Any]:
    """시간순 리플레이. 반환: {'trades': [...], 'metrics': {...}}."""
    phase_by_date = phase_by_date or {}
    trades: list[dict[str, Any]] = []
    open_until: dict[str, str] = {}   # symbol -> exit_date (보유 중 재검출 무시)
    skipped_filter = 0
    skipped_no_data = 0

    for det in sorted(detections, key=lambda d: (d['date'], d['symbol'])):
        symbol, det_date = det['symbol'], det['date']
        if symbol in open_until and open_until[symbol] >= det_date:
            continue
        bars = price_series.get(symbol) or []
        upto = [b for b in bars if str(b['date']) <= det_date]
        phase, _phase_age_days = phase_as_of(det_date, phase_by_date)

        # ── 진입 게이트 ──
        if rules.regime_gate and phase in live_phase_gate_blocked():
            skipped_filter += 1
            continue
        if rules.stage2_filter and not _stage2_ok(upto):
            skipped_filter += 1
            continue

        # ── 진입: 다음 거래일 시가 ──
        after = [b for b in bars if str(b['date']) > det_date]
        if not after or not after[0].get('open'):
            skipped_no_data += 1
            continue
        entry_bar = after[0]
        entry_price = float(entry_bar['open'])

        # ── 청산 레벨 ──
        if rules.exit_mode == 'atr':
            atr = _atr(upto, rules.atr_window)
            if not atr:
                skipped_no_data += 1
                continue
            target = entry_price + rules.atr_target_mult * atr
            stop = entry_price - rules.atr_stop_mult * atr
        else:
            target = entry_price * (1 + rules.target_pct / 100.0)
            stop = entry_price * (1 - rules.stop_pct / 100.0)

        exit_info = _simulate_exit(after, entry_price, target, stop, rules.max_hold_days)
        if exit_info is None:
            skipped_no_data += 1
            continue

        trade = {
            'symbol': symbol,
            'name': det.get('name', symbol),
            'detected_date': det_date,
            'phase': phase or None,
            'score': det.get('score'),
            'entry_date': str(entry_bar['date']),
            'entry_price': entry_price,
            'target_price': round(target, 4),
            'stop_price': round(stop, 4),
            'return_pct': round((float(exit_info['exit_price']) / entry_price - 1) * 100, 2),
            **exit_info,
        }
        trades.append(trade)
        open_until[symbol] = exit_info['exit_date']

    metrics = _metrics(trades)
    metrics['skipped_by_filter'] = skipped_filter
    metrics['skipped_no_data'] = skipped_no_data
    metrics['ruleset'] = rules.name
    return {'trades': trades, 'metrics': metrics}


def _metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.mirofish import costs

    cost = costs.round_trip_cost_pct()
    if not trades:
        return {'trades': 0, 'win_rate_pct': 0.0, 'expectancy_pct': 0.0,
                'median_pct': 0.0, 'profit_factor': None, 'cumulative_pct': 0.0,
                'max_drawdown_pct': 0.0, 'by_exit_reason': {}, 'by_phase': {},
                'avg_holding_days': 0.0,
                'net': {'round_trip_cost_pct': round(cost, 4), 'expectancy_pct': 0.0,
                        'win_rate_pct': 0.0, 'profit_factor': None, 'cumulative_pct': 0.0}}
    returns = [float(t['return_pct']) for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [-r for r in returns if r < 0]

    # equity curve (청산일 순 복리) + MDD
    ordered = sorted(trades, key=lambda t: str(t['exit_date']))
    equity, peak, mdd = 1.0, 1.0, 0.0
    for t in ordered:
        equity *= (1 + float(t['return_pct']) / 100.0)
        peak = max(peak, equity)
        mdd = min(mdd, (equity / peak - 1) * 100.0)

    sorted_r = sorted(returns)
    n = len(sorted_r)
    median = sorted_r[n // 2] if n % 2 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2

    by_reason: dict[str, int] = {}
    by_phase: dict[str, dict[str, Any]] = {}
    for t in trades:
        by_reason[t['exit_reason']] = by_reason.get(t['exit_reason'], 0) + 1
        phase = t.get('phase') or 'unknown'
        bucket = by_phase.setdefault(phase, {
            'trades': 0,
            'sum_return': 0.0,
            'wins': 0,
            'gross_profit_pct': 0.0,
            'gross_loss_pct': 0.0,
        })
        bucket['trades'] += 1
        trade_return = float(t['return_pct'])
        bucket['sum_return'] += trade_return
        bucket['wins'] += 1 if trade_return > 0 else 0
        if trade_return > 0:
            bucket['gross_profit_pct'] += trade_return
        elif trade_return < 0:
            bucket['gross_loss_pct'] += -trade_return
    for bucket in by_phase.values():
        bucket['expectancy_pct'] = round(bucket['sum_return'] / bucket['trades'], 2)
        bucket['win_rate_pct'] = round(bucket['wins'] / bucket['trades'] * 100, 1)
        bucket['net_expectancy_pct'] = round(bucket['expectancy_pct'] - cost, 2)
        gross_profit = bucket.pop('gross_profit_pct')
        gross_loss = bucket.pop('gross_loss_pct')
        bucket['profit_factor'] = round(gross_profit / gross_loss, 2) if gross_loss else None
        del bucket['sum_return']

    # net(비용 후) 병기 — gross 를 대체하지 않는다
    net_returns = [r - cost for r in returns]
    net_wins = [r for r in net_returns if r > 0]
    net_losses = [-r for r in net_returns if r < 0]
    net_equity = 1.0
    for t in ordered:
        net_equity *= (1 + (float(t['return_pct']) - cost) / 100.0)
    net = {
        'round_trip_cost_pct': round(cost, 4),
        'expectancy_pct': round(sum(net_returns) / len(net_returns), 2),
        'win_rate_pct': round(len(net_wins) / len(net_returns) * 100, 1),
        'profit_factor': round(sum(net_wins) / sum(net_losses), 2) if net_losses else None,
        'cumulative_pct': round((net_equity - 1) * 100, 2),
    }

    return {
        'net': net,
        'trades': len(trades),
        'win_rate_pct': round(len(wins) / len(trades) * 100, 1),
        'expectancy_pct': round(sum(returns) / len(returns), 2),
        'median_pct': round(median, 2),
        'profit_factor': round(sum(wins) / sum(losses), 2) if losses else None,
        'cumulative_pct': round((equity - 1) * 100, 2),
        'max_drawdown_pct': round(mdd, 2),
        'avg_holding_days': round(sum(t['holding_days'] for t in trades) / len(trades), 1),
        'by_exit_reason': by_reason,
        'by_phase': by_phase,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 보조 — 연속 (월,일) 시퀀스 (윤년/말일 단순화: 28일 단위)
# ─────────────────────────────────────────────────────────────────────────────

def _date_seq(n: int) -> list[tuple[int, int]]:
    out = []
    month, day = 1, 1
    for _ in range(n):
        out.append((month, day))
        day += 1
        if day > 28:
            day = 1
            month += 1
    return out

# ─────────────────────────────────────────────────────────────────────────────
# 4) 날짜별 4국면 타임라인 (paper_orchestrator.market_phase 의 시계열 버전)
# ─────────────────────────────────────────────────────────────────────────────

def phase_timeline() -> dict[str, str]:
    """regime timeline → 날짜별 4국면. 각 날짜는 그 시점까지 데이터만 사용."""
    from app.services.mirofish.intelligence.regime import REGIME_TIMELINE_PATH
    try:
        with open(REGIME_TIMELINE_PATH, 'r', encoding='utf-8') as f:
            timeline = json.load(f)
    except (OSError, ValueError):
        return {}
    by_date = timeline.get('by_date') or {}
    dates = sorted(by_date.keys())
    phases: dict[str, str] = {}
    for i, date in enumerate(dates):
        entry = by_date[date]
        breadth = float(entry.get('breadth') or 0)
        regime = str(entry.get('regime') or 'NEUTRAL')
        prev = by_date[dates[i - 5]] if i >= 5 else entry
        rebounding = (breadth - float(prev.get('breadth') or breadth)) >= 0.05
        if regime == 'RISK_ON':
            phases[date] = 'uptrend_broadening'
        elif regime == 'RISK_OFF':
            phases[date] = 'rebound_early' if rebounding else 'downtrend'
        else:
            phases[date] = 'rebound_early' if rebounding else 'leader_market'
    return phases


def phase_coverage(detections: list[dict[str, Any]],
                   phase_by_date: dict[str, str] | None) -> dict[str, Any]:
    """Return deterministic detection-level phase coverage metadata.

    Unknown labels are not considered covered.  This keeps stale/corrupt phase
    inputs from silently qualifying a validation report.
    """
    phase_by_date = phase_by_date or {}
    total = len(detections or [])
    assigned = 0
    unknown_label = 0
    asof_fallback_count = 0
    stale_count = 0
    maximum_age_days = 0
    distribution: dict[str, int] = {}
    missing_dates: set[str] = set()
    for detection in (detections or []):
        detection_date = str(detection.get('date') or '')
        phase, age_days = phase_as_of(detection_date, phase_by_date)
        if phase in KNOWN_PHASES:
            assigned += 1
            distribution[phase] = distribution.get(phase, 0) + 1
            maximum_age_days = max(maximum_age_days, int(age_days or 0))
            if age_days:
                asof_fallback_count += 1
        else:
            if phase:
                unknown_label += 1
            if age_days is not None and age_days > PHASE_MAX_AGE_DAYS:
                stale_count += 1
            if detection_date:
                missing_dates.add(detection_date)
    return {
        'detections_total': total,
        'detections_with_known_phase': assigned,
        'coverage_ratio': round(assigned / total, 6) if total else 0.0,
        'unknown_label_count': unknown_label,
        'asof_fallback_count': asof_fallback_count,
        'stale_count': stale_count,
        'maximum_age_days': maximum_age_days,
        'missing_detection_dates': len(missing_dates),
        'by_phase': dict(sorted(distribution.items())),
    }
