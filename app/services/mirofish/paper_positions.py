# -*- coding: utf-8 -*-
"""Alpha Position Engine — 알파캐치형 가상 포지션 수명주기 (STEP5: 매매 완결).

TOP3(CIO BUY) 검출을 "따라할 수 있는 완결 신호"로 바꾼다:
가상 진입 → 보유 관리 → 청산 신호 → 공개 성과 원장.

설계 원칙 (tests/test_paper_positions.py 로 고정):
- 진입은 검출 **다음 거래일 시가** — 검출일 종가 진입은 lookahead 로 성과를 부풀린다.
- 같은 날 목표/손절 동시 관통 시 보수적으로 손절 처리.
- 기존 스캐너/워크플로우 산출물은 읽기만 한다 (스코어링 무변경).
- 실주문 없음 — 가상 매매 신호와 성과만 제공한다.

원장: data/admin_mirofish/paper_positions.json  { pending / open / closed }
킬스위치: MIROFISH_PAPER_DISABLED
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from app.utils.atomic_json import write_json_atomic

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LEDGER_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'paper_positions.json')

# PriceFeed: symbol -> [{'date','open','high','low','close'}, ...] (날짜 오름차순)
PriceFeed = Callable[[str], list[dict[str, Any]]]


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, '') or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, '') or default)
    except (TypeError, ValueError):
        return default


def _disabled() -> bool:
    return (os.getenv('MIROFISH_PAPER_DISABLED', '') or '').strip().lower() in {'1', 'true', 'yes', 'on'}


def target_pct() -> float:
    return _env_float('MIROFISH_PAPER_TARGET_PCT', 8.0)


def stop_pct() -> float:
    return _env_float('MIROFISH_PAPER_STOP_PCT', 7.0)


def max_hold_trading_days() -> int:
    return _env_int('MIROFISH_PAPER_MAX_DAYS', 8)


def max_open_positions() -> int:
    return _env_int('MIROFISH_PAPER_MAX_POSITIONS', 10)


# ─────────────────────────────────────────────────────────────────────────────
# 원장 I/O
# ─────────────────────────────────────────────────────────────────────────────

def load_ledger() -> dict[str, Any]:
    if not os.path.isfile(LEDGER_PATH):
        return {'pending': [], 'open': [], 'closed': []}
    import json
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {'pending': [], 'open': [], 'closed': []}
    for key in ('pending', 'open', 'closed'):
        data.setdefault(key, [])
    return data


def save_ledger(ledger: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    write_json_atomic(LEDGER_PATH, ledger)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 검출 수집 — CIO BUY 만 진입 대기로 등록
# ─────────────────────────────────────────────────────────────────────────────

PHASE_GATE_BLOCKED = {'downtrend', 'rebound_early'}


def _phase_gate_on() -> bool:
    return (os.getenv('MIROFISH_PAPER_PHASE_GATE', 'true') or '').strip().lower() not in {
        '0', 'false', 'no', 'off'}


def ingest_detections(workflow: dict[str, Any] | None, *, phase: str | None = None) -> int:
    """워크플로우 top3 에서 BUY 판정 종목을 pending 으로 등록. 반환: 신규 등록 수.

    phase 게이트 — Detection Alpha Lab 실측(2026-08-17, 검출 603건 리플레이):
    하락/반등초입 국면의 검출은 기대수익 음수(-2.07%/-2.16%), 상승확산/주도주장세는
    양수(+3.00%/+1.96%). 양(+)국면에서만 진입한다 (승률 37%→63%, PF 0.67→2.06).
    phase 미상(None/'')이면 기존 동작 유지(허용). env MIROFISH_PAPER_PHASE_GATE=false 로 해제.
    """
    if _disabled() or not workflow:
        return 0
    if _phase_gate_on() and phase and phase in PHASE_GATE_BLOCKED:
        return 0
    top3 = [it for it in (workflow.get('top3') or []) if isinstance(it, dict)]
    if not top3:
        return 0

    ledger = load_ledger()
    active = {p['symbol'] for p in ledger['open']} | {p['symbol'] for p in ledger['pending']}
    detected_at = str(workflow.get('created_at') or '')[:10] or _today()
    created = 0
    for item in top3:
        verdict = item.get('verdict') if isinstance(item.get('verdict'), dict) else {}
        action = str(verdict.get('action') or '').upper()
        symbol = str(item.get('symbol') or '').strip()
        if action != 'BUY' or not symbol or symbol in active:
            continue
        if len(ledger['open']) + len(ledger['pending']) + created >= max_open_positions():
            break
        ledger['pending'].append({
            'symbol': symbol,
            'name': str(verdict.get('target') or item.get('name') or symbol),
            'market': str(item.get('market') or ''),
            'detected_at': detected_at,
            'workflow_id': str(workflow.get('id') or ''),
            'run_id': str(item.get('run_id') or ''),
            'score': item.get('final_score'),
        })
        active.add(symbol)
        created += 1
    if created:
        save_ledger(ledger)
    return created


# ─────────────────────────────────────────────────────────────────────────────
# 2) 체결 — 검출 다음 거래일 시가 진입 (lookahead-safe)
# ─────────────────────────────────────────────────────────────────────────────

def settle_pending(price_feed: PriceFeed) -> list[dict[str, Any]]:
    """pending → open. 검출일 이후 첫 거래일 시가로 체결. 반환: 신규 open 포지션."""
    if _disabled():
        return []
    ledger = load_ledger()
    if not ledger['pending']:
        return []

    entered: list[dict[str, Any]] = []
    still_pending: list[dict[str, Any]] = []
    for cand in ledger['pending']:
        rows = price_feed(cand['symbol']) or []
        next_bar = next((r for r in rows if str(r.get('date')) > cand['detected_at']), None)
        if next_bar is None or not next_bar.get('open'):
            still_pending.append(cand)   # 아직 다음 거래일 데이터 없음 — 대기
            continue
        entry_price = float(next_bar['open'])
        position = {
            'id': f"pp_{uuid.uuid4().hex[:10]}",
            'symbol': cand['symbol'],
            'name': cand['name'],
            'market': cand.get('market', ''),
            'entry_date': str(next_bar['date']),
            'entry_price': entry_price,
            'target_price': round(entry_price * (1 + target_pct() / 100.0), 4),
            'stop_price': round(entry_price * (1 - stop_pct() / 100.0), 4),
            'workflow_id': cand.get('workflow_id', ''),
            'run_id': cand.get('run_id', ''),
            'detected_at': cand['detected_at'],
            'score': cand.get('score'),
        }
        ledger['open'].append(position)
        entered.append(position)
    ledger['pending'] = still_pending
    if entered or len(still_pending) != len(ledger['pending']):
        save_ledger(ledger)
    return entered


# ─────────────────────────────────────────────────────────────────────────────
# 3) 청산 평가 — 일 단위 (target / stop / expiry / cio_sell)
# ─────────────────────────────────────────────────────────────────────────────

def _close(ledger: dict[str, Any], position: dict[str, Any], *,
           exit_date: str, exit_price: float, exit_reason: str) -> dict[str, Any]:
    entry = float(position['entry_price'])
    closed = {
        **position,
        'exit_date': exit_date,
        'exit_price': round(float(exit_price), 4),
        'exit_reason': exit_reason,
        'return_pct': round((float(exit_price) / entry - 1) * 100.0, 2),
    }
    ledger['open'] = [p for p in ledger['open'] if p['id'] != position['id']]
    ledger['closed'].append(closed)
    return closed


def evaluate_positions(price_feed: PriceFeed, *, cio_actions: dict[str, str],
                       max_hold_days: int | None = None) -> list[dict[str, Any]]:
    """보유 포지션을 일봉 기준으로 평가해 청산 신호 목록을 반환한다.

    규칙 우선순위(각 거래일 내): 손절(저가) > 익절(고가) > CIO SELL(종가)
    > 보유 만료(종가). 손절/익절 동시 관통은 보수적으로 손절.
    """
    if _disabled():
        return []
    hold_limit = max_hold_days or max_hold_trading_days()
    ledger = load_ledger()
    signals: list[dict[str, Any]] = []

    for position in list(ledger['open']):
        rows = price_feed(position['symbol']) or []
        bars = [r for r in rows if str(r.get('date')) >= position['entry_date']]
        if not bars:
            continue
        target = float(position['target_price'])
        stop = float(position['stop_price'])
        cio_sell = str(cio_actions.get(position['symbol'], '')).upper() == 'SELL'

        closed = None
        for held_days, bar in enumerate(bars, start=1):
            date = str(bar.get('date'))
            low = float(bar.get('low') or 0)
            high = float(bar.get('high') or 0)
            close_px = float(bar.get('close') or 0)
            if low and low <= stop:
                closed = _close(ledger, position, exit_date=date, exit_price=stop,
                                exit_reason='stop')
                break
            if high and high >= target:
                closed = _close(ledger, position, exit_date=date, exit_price=target,
                                exit_reason='target')
                break
            if held_days >= hold_limit:
                closed = _close(ledger, position, exit_date=date, exit_price=close_px,
                                exit_reason='expiry')
                break
        if closed is None and cio_sell and bars:
            last = bars[-1]
            closed = _close(ledger, position, exit_date=str(last.get('date')),
                            exit_price=float(last.get('close') or 0),
                            exit_reason='cio_sell')
        if closed is not None:
            closed['holding_days'] = _holding_days(position['entry_date'], closed['exit_date'], bars)
            signals.append(closed)

    if signals:
        save_ledger(ledger)
    return signals


def _holding_days(entry_date: str, exit_date: str, bars: list[dict[str, Any]]) -> int:
    dates = [str(b.get('date')) for b in bars]
    try:
        return dates.index(exit_date) + 1
    except ValueError:
        return max(1, len(dates))


# ─────────────────────────────────────────────────────────────────────────────
# 4) 장중 감시 — 현재가 기준 즉시 청산 신호
# ─────────────────────────────────────────────────────────────────────────────

def intraday_check(quotes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """quotes: {symbol: {'price': float}} — 목표/손절 터치 시 즉시 청산."""
    if _disabled():
        return []
    ledger = load_ledger()
    signals: list[dict[str, Any]] = []
    today = _today()
    for position in list(ledger['open']):
        quote = quotes.get(position['symbol']) or {}
        price = float(quote.get('price') or 0)
        if not price:
            continue
        if price <= float(position['stop_price']):
            closed = _close(ledger, position, exit_date=today, exit_price=price,
                            exit_reason='stop')
        elif price >= float(position['target_price']):
            closed = _close(ledger, position, exit_date=today, exit_price=price,
                            exit_reason='target')
        else:
            continue
        closed['holding_days'] = None  # 장중 청산 — 일봉 시퀀스 밖
        closed['intraday'] = True
        signals.append(closed)
    if signals:
        save_ledger(ledger)
    return signals


# ─────────────────────────────────────────────────────────────────────────────
# 5) 성과 요약 — 최근 N일 완결 매매
# ─────────────────────────────────────────────────────────────────────────────

def performance_summary(days: int = 30, today: str | None = None) -> dict[str, Any]:
    ledger = load_ledger()
    ref = datetime.strptime(today or _today(), '%Y-%m-%d')
    cutoff = (ref - timedelta(days=days)).strftime('%Y-%m-%d')
    trades = [c for c in ledger['closed'] if str(c.get('exit_date') or '') >= cutoff]

    wins = [t for t in trades if float(t.get('return_pct') or 0) > 0]
    returns = [float(t.get('return_pct') or 0) for t in trades]
    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r / 100.0)

    return {
        'window_days': days,
        'trades': len(trades),
        'win_rate_pct': round(len(wins) / len(trades) * 100.0, 1) if trades else 0.0,
        'avg_return_pct': round(sum(returns) / len(returns), 2) if returns else 0.0,
        'cumulative_return_pct': round((cumulative - 1) * 100.0, 2),
        'recent': sorted(trades, key=lambda t: str(t.get('exit_date') or ''), reverse=True)[:10],
        'open_count': len(ledger['open']),
    }


def _today() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')
