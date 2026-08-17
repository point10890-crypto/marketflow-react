# -*- coding: utf-8 -*-
"""Alpha Position Engine 오케스트레이터 — 스케줄러/API 가 부르는 상위 흐름.

paper_positions(순수 규칙)와 실데이터 소스(daily_prices.csv, 워크플로우,
스캐너 run, KIS/키움 시세)를 잇는다. 텔레그램 발송은 하지 않는다 —
메시지 문자열과 신호만 반환하고, 발송은 scheduler.py 래퍼가 담당한다
(순환 import 방지 + 채널 정책 일원화).
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from typing import Any

from app.services.mirofish import paper_positions as pp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DAILY_PRICES_CSV = os.path.join(REPO_ROOT, 'data', 'daily_prices.csv')

EXIT_REASON_LABEL = {
    'target': '목표가 도달',
    'stop': '손절선 터치',
    'expiry': '보유기간 만료',
    'cio_sell': 'CIO SELL 전환',
}

PHASE_LABEL = {
    'uptrend_broadening': '상승 추세 확산',
    'leader_market': '주도주 장세',
    'downtrend': '하락 국면',
    'rebound_early': '반등 초입',
}


# ─────────────────────────────────────────────────────────────────────────────
# 가격 피드 — daily_prices.csv (필요 심볼만 로드)
# ─────────────────────────────────────────────────────────────────────────────

def load_price_feed(symbols: set[str]):
    """symbols 의 일봉 시퀀스를 한 번 읽어 클로저로 반환."""
    series: dict[str, list[dict[str, Any]]] = {s: [] for s in symbols}
    if symbols and os.path.isfile(DAILY_PRICES_CSV):
        with open(DAILY_PRICES_CSV, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                ticker = (row.get('ticker') or '').strip()
                if ticker not in series:
                    continue
                try:
                    series[ticker].append({
                        'date': (row.get('date') or '').strip(),
                        'open': float(row.get('open') or 0),
                        'high': float(row.get('high') or 0),
                        'low': float(row.get('low') or 0),
                        'close': float(row.get('current_price') or 0),
                    })
                except (TypeError, ValueError):
                    continue
    for rows in series.values():
        rows.sort(key=lambda r: r['date'])

    def feed(symbol: str) -> list[dict[str, Any]]:
        return series.get(symbol, [])
    return feed


def _ledger_symbols(ledger: dict[str, Any]) -> set[str]:
    return (
        {p['symbol'] for p in ledger.get('pending', [])}
        | {p['symbol'] for p in ledger.get('open', [])}
    )


# ─────────────────────────────────────────────────────────────────────────────
# CIO 판정 맵 — 최신 워크플로우의 top3 verdict
# ─────────────────────────────────────────────────────────────────────────────

def collect_cio_actions() -> dict[str, str]:
    try:
        from app.services.mirofish.workflow import read_latest_workflow
        workflow = read_latest_workflow() or {}
    except Exception:
        return {}
    actions: dict[str, str] = {}
    for item in (workflow.get('top3') or []):
        if not isinstance(item, dict):
            continue
        verdict = item.get('verdict') if isinstance(item.get('verdict'), dict) else {}
        symbol = str(item.get('symbol') or '').strip()
        action = str(verdict.get('action') or '').upper()
        if symbol and action:
            actions[symbol] = action
    return actions


# ─────────────────────────────────────────────────────────────────────────────
# 시장 4국면 — regime timeline 경량 확장
# ─────────────────────────────────────────────────────────────────────────────

def market_phase() -> dict[str, Any]:
    """RISK_ON/OFF/NEUTRAL 위에 알파캐치식 4국면(phase)을 병기한다.

    - RISK_ON                          → 상승 추세 확산
    - RISK_OFF + breadth 5일 반등(+5%p) → 반등 초입, 아니면 하락 국면
    - NEUTRAL  + breadth 5일 반등(+5%p) → 반등 초입, 아니면 주도주 장세
    """
    import json
    from app.services.mirofish.intelligence.regime import REGIME_TIMELINE_PATH
    try:
        with open(REGIME_TIMELINE_PATH, 'r', encoding='utf-8') as f:
            timeline = json.load(f)
    except (OSError, ValueError):
        return {'phase': 'leader_market', 'phase_label': PHASE_LABEL['leader_market'],
                'regime': 'NEUTRAL', 'breadth': None}

    by_date = timeline.get('by_date') or {}
    dates = sorted(by_date.keys())
    if not dates:
        return {'phase': 'leader_market', 'phase_label': PHASE_LABEL['leader_market'],
                'regime': 'NEUTRAL', 'breadth': None}

    latest = by_date[dates[-1]]
    breadth = float(latest.get('breadth') or 0)
    regime = str(latest.get('regime') or 'NEUTRAL')
    breadth_5d_ago = float(by_date[dates[-6]].get('breadth') or breadth) if len(dates) >= 6 else breadth
    rebounding = (breadth - breadth_5d_ago) >= 0.05

    if regime == 'RISK_ON':
        phase = 'uptrend_broadening'
    elif regime == 'RISK_OFF':
        phase = 'rebound_early' if rebounding else 'downtrend'
    else:
        phase = 'rebound_early' if rebounding else 'leader_market'

    return {
        'phase': phase,
        'phase_label': PHASE_LABEL[phase],
        'regime': regime,
        'breadth': round(breadth, 3),
        'breadth_change_5d': round(breadth - breadth_5d_ago, 3),
        'as_of': dates[-1],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 타임라인 작업 3종 — 메시지/신호 반환 (발송은 scheduler)
# ─────────────────────────────────────────────────────────────────────────────

def run_close_cycle() -> dict[str, Any]:
    """15:00 마감 신호 — 검출 수집(국면 게이트) → 체결 → 청산 평가."""
    from app.services.mirofish.workflow import read_latest_workflow
    try:
        workflow = read_latest_workflow()
    except Exception:
        workflow = None
    phase = market_phase()
    ingested = pp.ingest_detections(workflow, phase=phase.get('phase'))

    ledger = pp.load_ledger()
    feed = load_price_feed(_ledger_symbols(ledger))
    entered = pp.settle_pending(feed)

    # settle 이후 open 이 갱신됐을 수 있으므로 다시 로드해 평가
    ledger = pp.load_ledger()
    feed = load_price_feed(_ledger_symbols(ledger))
    exits = pp.evaluate_positions(feed, cio_actions=collect_cio_actions())

    gate_blocked = bool(
        workflow and not ingested
        and phase.get('phase') in pp.PHASE_GATE_BLOCKED
    )
    return {
        'ingested': ingested,
        'entered': entered,
        'exits': exits,
        'phase': phase,
        'gate_blocked': gate_blocked,
        'message': _close_cycle_message(entered, exits, phase=phase, gate_blocked=gate_blocked),
    }


def run_intraday_watch() -> dict[str, Any]:
    """장중 보유 포지션 감시 — KIS 현재가 → 목표/손절 즉시 신호."""
    ledger = pp.load_ledger()
    open_positions = ledger.get('open', [])
    if not open_positions:
        return {'checked': 0, 'exits': [], 'message': ''}

    quotes: dict[str, dict[str, Any]] = {}
    try:
        from app.services.kis_screener import fetch_price_detail, get_token
        token = get_token()
        for position in open_positions:
            detail = fetch_price_detail(token, position['symbol']) or {}
            price = detail.get('stck_prpr')
            try:
                quotes[position['symbol']] = {'price': float(price)}
            except (TypeError, ValueError):
                continue
    except Exception:
        quotes = {}

    exits = pp.intraday_check(quotes) if quotes else []
    lines = [_exit_line(s) for s in exits]
    message = ''
    if exits:
        message = "<b>⚡ 장중 청산 신호</b>\n\n" + "\n".join(lines) + _disclaimer()
    return {'checked': len(quotes), 'exits': exits, 'message': message}


def morning_top_message(top_n: int = 5) -> str:
    """08:30 알파스코어 상위 + 시장 4국면."""
    from app.services.mirofish.alpha_scanner import read_latest_scanner_run
    try:
        run = read_latest_scanner_run() or {}
    except Exception:
        run = {}
    candidates = [c for c in (run.get('candidates') or []) if isinstance(c, dict)][:top_n]
    phase = market_phase()

    lines = [
        "<b>🌅 알파 모닝 브리핑</b>",
        "",
        f"시장 국면: <b>{phase['phase_label']}</b>"
        + (f" (시장폭 {phase['breadth']:.0%})" if phase.get('breadth') is not None else ''),
        "",
        f"<b>알파스코어 상위 {len(candidates)}종목</b>",
    ]
    for i, cand in enumerate(candidates, 1):
        name = cand.get('name') or cand.get('symbol')
        alpha = cand.get('alpha_score')
        alpha_txt = ''
        if isinstance(alpha, dict):
            alpha_txt = f" α={alpha.get('value', '?')}"
        elif alpha is not None:
            alpha_txt = f" α={alpha}"
        lines.append(f"  {i}. <b>{name}</b> ({cand.get('symbol')}){alpha_txt}")
    if not candidates:
        lines.append("  (최근 스캐너 실행 없음)")
    lines.append(_disclaimer())
    return "\n".join(lines)


def performance_brief_message() -> str:
    """18:00 성과 브리핑 — 보유 현황 + 30일 완결 성과."""
    perf = pp.performance_summary(days=30)
    ledger = pp.load_ledger()
    feed = load_price_feed({p['symbol'] for p in ledger['open']})

    lines = ["<b>📊 알파 성과 브리핑</b>", ""]
    if ledger['open']:
        lines.append(f"<b>보유 중 ({len(ledger['open'])})</b>")
        for position in ledger['open']:
            rows = feed(position['symbol'])
            last_close = rows[-1]['close'] if rows else None
            ret = ''
            if last_close:
                ret_pct = (last_close / float(position['entry_price']) - 1) * 100
                ret = f" {ret_pct:+.1f}%"
            lines.append(f"  • <b>{position['name']}</b> ({position['symbol']}) "
                         f"진입 {position['entry_price']:,.0f}{ret}")
    else:
        lines.append("보유 중 포지션 없음")
    lines += [
        "",
        f"<b>최근 30일 완결 매매</b>",
        f"  거래 {perf['trades']}건 · 승률 {perf['win_rate_pct']}% · "
        f"평균 {perf['avg_return_pct']:+.2f}% · 누적 {perf['cumulative_return_pct']:+.2f}%",
    ]
    lines.append(_disclaimer())
    return "\n".join(lines)


def _close_cycle_message(entered: list[dict[str, Any]], exits: list[dict[str, Any]],
                         *, phase: dict[str, Any] | None = None,
                         gate_blocked: bool = False) -> str:
    if not entered and not exits and not gate_blocked:
        return ''
    lines = ["<b>🔔 알파 매매신호</b>", ""]
    if gate_blocked and phase:
        lines.append(
            f"⛔ 시장 국면 <b>{phase.get('phase_label')}</b> — 신규 진입을 보류합니다 "
            f"(실측: 이 국면의 검출은 기대수익 음수)."
        )
        lines.append("")
    if entered:
        lines.append("<b>🟢 신규 진입 (가상)</b>")
        for position in entered:
            lines.append(
                f"  • <b>{position['name']}</b> ({position['symbol']}) "
                f"진입가 {position['entry_price']:,.0f} · "
                f"목표 {position['target_price']:,.0f} · 손절 {position['stop_price']:,.0f}"
            )
        lines.append("")
    if exits:
        lines.append("<b>🔴 청산 신호</b>")
        lines += [_exit_line(s) for s in exits]
    lines.append(_disclaimer())
    return "\n".join(lines)


def _exit_line(signal: dict[str, Any]) -> str:
    reason = EXIT_REASON_LABEL.get(signal.get('exit_reason', ''), signal.get('exit_reason', ''))
    return (
        f"  • <b>{signal.get('name')}</b> ({signal.get('symbol')}) "
        f"{reason} — 청산 {float(signal.get('exit_price') or 0):,.0f} "
        f"({float(signal.get('return_pct') or 0):+.2f}%)"
    )


def _disclaimer() -> str:
    return "\n\n<i>가상 매매 신호이며 투자 권유가 아닙니다. 투자 책임은 본인에게 있습니다.</i>"


# ─────────────────────────────────────────────────────────────────────────────
# 구독자 대시보드 overview
# ─────────────────────────────────────────────────────────────────────────────

def paper_overview() -> dict[str, Any]:
    ledger = pp.load_ledger()
    feed = load_price_feed({p['symbol'] for p in ledger['open']})
    open_positions = []
    for position in ledger['open']:
        rows = feed(position['symbol'])
        last_close = rows[-1]['close'] if rows else None
        bars_held = len([r for r in rows if r['date'] >= position['entry_date']])
        open_positions.append({
            **position,
            'last_close': last_close,
            'unrealized_pct': round((last_close / float(position['entry_price']) - 1) * 100, 2)
            if last_close else None,
            'held_trading_days': bars_held,
            'max_hold_days': pp.max_hold_trading_days(),
        })
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'phase': market_phase(),
        'open_positions': open_positions,
        'pending': ledger['pending'],
        'performance': pp.performance_summary(days=30),
        'rules': {
            'target_pct': pp.target_pct(),
            'stop_pct': pp.stop_pct(),
            'max_hold_trading_days': pp.max_hold_trading_days(),
            'entry': 'next_trading_day_open',
        },
        'disabled': bool(os.getenv('MIROFISH_PAPER_DISABLED')),
    }
