# -*- coding: utf-8 -*-
"""종목 판단 브리프 — 한 종목의 독립 근거를 팬아웃 집계해 합의·이견을 드러낸다.

설계 출처: stablyai/orca 의 "하나의 프롬프트를 여러 에이전트에 팬아웃 → 결과 비교 →
승자 선택" 패턴. 다만 Orca 는 코딩 에이전트를 병렬 실행하는 개발 도구이므로 매매
도메인 코드는 없다. 여기서는 그 **비교 구조만** 가져오고, 새 에이전트를 돌리는 대신
시스템이 이미 보유한 읽기전용 근거(Claw·종가베팅·스캐너·CIO·TradingAgents·페이퍼·
관측 원장)를 같은 종목 기준으로 모아 **어디서 일치하고 어디서 갈리는지**를 노출한다.

불변조건
    - 읽기전용. 스캔·발송·주문·원장 변경을 절대 트리거하지 않는다.
    - 매수/매도 판정 어휘를 만들지 않는다 (`ALLOWED_STATUS` 3종 고정).
    - 소스별 try/except 격리 — 한 소스가 죽어도 나머지 판단은 살아남는다.
    - 근거 등급과 데이터 공백을 숨기지 않는다. 모르면 `data_gaps` 로 명시한다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 'mirofish.decision_brief.v1'
ALLOWED_STATUS = ('watch', 'neutral', 'avoid_data_gap')

# Detection Lab 실측(검출 642건): 하락·반등초입 국면의 기대값은 음수였다.
NEGATIVE_PHASES = frozenset({'downtrend', 'rebound_early'})
POSITIVE_PHASES = frozenset({'uptrend_broadening', 'leader_market'})

CAP_BASE = 0.75
CAP_FLOOR = 0.10
NEGATIVE_PHASE_CEILING = 0.40
GAP_PENALTY = 0.10
THIN_EVIDENCE_PENALTY = 0.15
CONFLICT_PENALTY = 0.10
MIN_STRONG_EVIDENCE = 2  # E1: 서로 다른 S/A 소스 2개 이상

# 근거 등급 — S: 거래소·공시 원장 / A: 시세·수급·내부 실측 / B: LLM 해석
SOURCE_GRADE = {
    'price': 'A',        # 거래소 시세 원장 파생 (일봉 추세)
    'flow': 'A',         # KIS 실시간 시세·투자자 수급
    'sector_rs': 'B',    # 유니버스 상대강도 파생
    'risk': 'A',         # KIND 지정·신용잔고 점검
    'claw': 'A',
    'jongga': 'A',
    'scanner': 'A',
    'paper': 'A',
    'observation': 'A',
    'detection': 'B',
    'tradingagents': 'B',
}

#: 검출 '이력'에서 나오는 소스 — 스캐너에 걸린 적 없는 종목이면 비는 게 정상이다.
#: 이 계열의 공백은 개별 감산 대신 1회 합산 감산으로 다룬다(2026-09-01, SKT 사례).
DETECTION_HISTORY_SOURCES = frozenset({
    'claw', 'jongga', 'scanner', 'detection', 'tradingagents', 'paper', 'observation',
})

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
JONGGA_PATH = os.path.join(REPO_ROOT, 'data', 'jongga_v2_latest.json')
UNIVERSE_PATH = os.path.join(REPO_ROOT, 'data', 'korean_stocks_list.csv')
MARKET_GATE_PATH = os.path.join(REPO_ROOT, 'data', 'market_gate_cache.json')


# ─── 순수 로직 ──────────────────────────────────────────────

def normalize_symbol(raw: Any) -> str:
    """KR 6자리 코드는 0-패딩, 그 외(해외 티커)는 대문자화."""
    text = str(raw or '').strip()
    if not text:
        raise ValueError('symbol is required')
    if text.isdigit():
        return text.zfill(6)
    return text.upper()


_universe_cache: dict[str, str] | None = None


def load_universe() -> dict[str, str]:
    """종목코드 → 종목명. 이름 검색을 위해 한 번만 읽어 캐시한다."""
    global _universe_cache
    if _universe_cache is not None:
        return _universe_cache
    import csv

    table: dict[str, str] = {}
    try:
        with open(UNIVERSE_PATH, encoding='utf-8-sig', newline='') as fp:
            for row in csv.DictReader(fp):
                code = str(row.get('ticker') or '').strip()
                name = str(row.get('name') or '').strip()
                if code and name:
                    table[code] = name
    except OSError:
        # 읽기 실패(파일 부재·재작성 중 잠금)는 캐시하지 않는다 — 빈 테이블을
        # 프로세스 수명 내내 물고 있으면 이름 해석이 재시작 전까지 죽는다.
        return table
    _universe_cache = table
    return table


def _graphrag_matches(text: str, limit: int = 8) -> list[dict[str, Any]]:
    """기존 GraphRAG 엔티티 리졸버에 물어본다.

    거기에는 이미 초성(ㅅㅅㅈㅈ→삼성전자), 별칭(하닉→SK하이닉스), 접두·퍼지 매칭이
    다 들어 있다. 새로 만들지 않고 그대로 쓴다. entities.db 가 없는 환경(개발 PC)
    이나 조회 실패는 빈 목록으로 흘려 CSV 폴백에 맡긴다.
    """
    try:
        from app.services.mirofish.graphrag import resolver

        result = resolver.resolve(text, limit=limit) or {}
    except Exception as exc:  # noqa: BLE001 — 리졸버 장애가 조회를 막지 않는다
        logger.debug('[decision] graphrag resolve failed: %s', exc)
        return []

    out = []
    for m in (result.get('matches') or []):
        code = str((m or {}).get('symbol') or '').strip()
        if code:
            out.append(m)
    return out


def _universe_matches(text: str, universe: dict[str, str]) -> list[tuple[str, str]]:
    """CSV 유니버스 부분 일치. 짧은 이름일수록 구체적인 매칭으로 본다."""
    compact = text.replace(' ', '').upper()
    if not compact:
        return []
    exact = [(c, n) for c, n in universe.items()
             if str(n).replace(' ', '').upper() == compact]
    partial = sorted(
        [(c, n) for c, n in universe.items()
         if compact in str(n).replace(' ', '').upper()],
        key=lambda kv: len(str(kv[1])),
    )
    seen, out = set(), []
    for code, name in exact + partial:
        if code not in seen:
            seen.add(code)
            out.append((code, name))
    return out


def resolve_symbol(raw: Any) -> tuple[str, str | None]:
    """코드든 종목명이든 별칭이든 초성이든 (코드, 이름)으로 해석한다.

    사용자는 '005930' 이 아니라 '우리기술투자', '하닉', 'ㅅㅅㅈㅈ' 로 검색한다.
    해석은 기존 GraphRAG 리졸버가 하고, 그게 없으면 CSV 유니버스로 폴백한다.
    끝내 못 찾으면 입력을 그대로 코드로 두고 이름은 None — 조회를 막지는 않는다.
    """
    text = str(raw or '').strip()
    if not text:
        raise ValueError('symbol is required')

    universe = load_universe()
    if text.isdigit():
        code = text.zfill(6)
        return code, universe.get(code)

    for match in _graphrag_matches(text, limit=1):
        code = str(match.get('symbol')).strip()
        return code, match.get('name_ko') or universe.get(code)

    hits = _universe_matches(text, universe)
    if hits:
        return hits[0]
    return normalize_symbol(text), None


def search_symbols(query: Any, *, limit: int = 8) -> dict[str, Any]:
    """자동완성용 후보 목록. 왜 걸렸는지(reason)까지 같이 준다.

    모바일에서는 종목명을 정확히 치기 어렵다 — 후보를 보여주고 고르게 한다.
    """
    text = str(query or '').strip()
    limit = max(1, min(int(limit or 8), 20))
    if not text:
        return {'query': text, 'candidates': []}

    universe = load_universe()
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(code: str, name: str | None, confidence: float, reason: str) -> None:
        code = str(code or '').strip()
        if not code or code in seen or len(candidates) >= limit:
            return
        seen.add(code)
        candidates.append({'symbol': code, 'name': name or universe.get(code),
                           'confidence': round(float(confidence or 0), 4),
                           'reason': reason})

    if text.isdigit():
        _add(text.zfill(6), None, 1.0, 'ticker_direct')

    for match in _graphrag_matches(text, limit=limit):
        # 리졸버는 근거를 'match_reason' 에 담는다 — 'reason' 이 아니다.
        reason = match.get('match_reason') or match.get('reason') or 'graphrag'
        _add(str(match.get('symbol')), match.get('name_ko'),
             match.get('confidence') or 0.0, str(reason))

    for code, name in _universe_matches(text, universe):
        _add(code, name, 0.5, 'universe_substring')

    return {'query': text, 'candidates': candidates[:limit]}


def summarize_agreement(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """소스 간 방향 합의도. absent 는 의견이 아니라 공백으로 센다."""
    counts = {'positive': 0, 'negative': 0, 'neutral': 0, 'absent': 0}
    for sig in signals:
        stance = str((sig or {}).get('stance') or 'absent')
        counts[stance if stance in counts else 'absent'] += 1

    active = counts['positive'] + counts['negative'] + counts['neutral']
    if active == 0:
        verdict, direction, ratio = 'insufficient', None, None
    elif counts['positive'] and counts['negative']:
        verdict, direction = 'conflicted', 'split'
        ratio = round(max(counts['positive'], counts['negative']) / active, 3)
    elif counts['positive']:
        verdict, direction = 'aligned', 'positive'
        ratio = round(counts['positive'] / active, 3)
    elif counts['negative']:
        verdict, direction = 'aligned', 'negative'
        ratio = round(counts['negative'] / active, 3)
    else:
        verdict, direction = 'mixed', 'neutral'
        ratio = round(counts['neutral'] / active, 3)

    return {**counts, 'active': active, 'ratio': ratio,
            'verdict': verdict, 'direction': direction}


def strong_evidence_count(signals: list[dict[str, Any]]) -> int:
    """의견을 낸(absent 아닌) S/A 등급 소스의 수 — 서로 다른 소스만 센다."""
    return len({
        str(s.get('source'))
        for s in signals
        if s and s.get('stance') != 'absent' and str(s.get('grade')) in {'S', 'A'}
    })


def compute_confidence_cap(
    signals: list[dict[str, Any]],
    *,
    data_gaps: list[str],
    phase: str | None,
    agreement: dict[str, Any],
    regime_conflict: bool = False,
    verification: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    """결정론적 신뢰 상한. LLM 은 이 값을 올릴 수 없다(내리는 것만 허용)."""
    cap = CAP_BASE
    reasons: list[str] = []

    if strong_evidence_count(signals) < MIN_STRONG_EVIDENCE:
        cap -= THIN_EVIDENCE_PENALTY
        reasons.append(f'strong evidence < {MIN_STRONG_EVIDENCE} (S/A 소스 부족)')

    history_gaps = [g for g in data_gaps if g in DETECTION_HISTORY_SOURCES]
    for gap in data_gaps:
        if gap in DETECTION_HISTORY_SOURCES:
            continue
        cap -= GAP_PENALTY
        reasons.append(f'data gap: {gap}')
    if history_gaps:
        # 미검출 종목이면 검출계열 공백은 정상이다 — 개별 누적 대신 1회만 감산한다.
        cap -= GAP_PENALTY
        reasons.append(f"data gap: 검출 이력 {len(history_gaps)}종 (미검출 종목 정상)")

    if agreement.get('verdict') == 'conflicted':
        cap -= CONFLICT_PENALTY
        reasons.append('sources conflicted')

    if regime_conflict:
        cap -= CONFLICT_PENALTY
        reasons.append('regime sources conflict')

    if verification:
        from app.services.mirofish import number_guard
        penalty = number_guard.cap_penalty(verification)
        if penalty > 0:
            cap -= penalty
            reasons.append(
                'unverified numbers: %s (기계적 검증 미통과 수치)'
                % verification.get('unverified', 0))

    if phase in NEGATIVE_PHASES:
        cap = min(cap, NEGATIVE_PHASE_CEILING)
        reasons.append(f'negative phase ceiling ({phase})')

    return round(max(cap, CAP_FLOOR), 4), reasons


def decide_status(signals: list[dict[str, Any]], agreement: dict[str, Any]) -> str:
    """watch | neutral | avoid_data_gap — 매수/매도 어휘는 생성 불가."""
    if strong_evidence_count(signals) < MIN_STRONG_EVIDENCE:
        return 'avoid_data_gap'
    if (agreement.get('verdict') == 'aligned'
            and agreement.get('direction') == 'positive'
            and agreement.get('positive', 0) >= MIN_STRONG_EVIDENCE):
        return 'watch'
    return 'neutral'


# ─── 소스 리더 (각각 dict | None) ───────────────────────────

def _src_claw(symbol: str) -> dict[str, Any] | None:
    """장중/마감 주도주 스냅샷 + 당일 전이 이벤트."""
    from marketflow_claw.overview import build_close_leaders

    data = build_close_leaders() or {}
    row = next((r for r in (data.get('rows') or []) if str(r.get('code')) == symbol), None)
    if not row:
        return None
    events = row.get('events') or []
    dropped = any(str(e.get('type')) == 'LEADER_DROP' for e in events)
    grade = str(row.get('grade') or '')
    if dropped:
        stance = 'negative'
    elif grade in {'S', 'A'}:
        stance = 'positive'
    else:
        stance = 'neutral'
    return {
        'stance': stance,
        'as_of': data.get('snapshot_ts'),
        'name': row.get('name'),
        'detail': {'grade': grade, 'score': row.get('score'), 'chg_pct': row.get('chg'),
                   'trading_value_eok': row.get('trval_eok'), 'session': data.get('day'),
                   'events': [{'type': e.get('type'), 'ts': e.get('ts')} for e in events[:5]]},
    }


def _src_jongga(symbol: str) -> dict[str, Any] | None:
    """종가베팅 V2 최신 시그널 (17점 채점)."""
    with open(JONGGA_PATH, encoding='utf-8') as fp:
        data = json.load(fp)
    sig = next((s for s in (data.get('signals') or [])
                if str(s.get('stock_code')) == symbol), None)
    if not sig:
        return None
    grade = str(sig.get('grade') or '')
    stance = 'positive' if grade in {'S', 'A'} else 'neutral'
    score = sig.get('score') or {}
    return {
        'stance': stance,
        'as_of': data.get('updated_at') or data.get('date'),
        'name': sig.get('stock_name'),
        'detail': {'grade': grade,
                   'score_total': score.get('total') if isinstance(score, dict) else score,
                   'entry_price': sig.get('entry_price'), 'stop_price': sig.get('stop_price'),
                   'target_price': sig.get('target_price'), 'chg_pct': sig.get('change_pct')},
    }


def _src_scanner(symbol: str) -> dict[str, Any] | None:
    """알파 스캐너 최신 후보 (alpha/risk/RS)."""
    from app.services.mirofish.alpha_scanner import read_latest_scanner_candidates

    data = read_latest_scanner_candidates(limit=20) or {}
    cand = next((c for c in (data.get('candidates') or [])
                 if str(c.get('symbol')) == symbol), None)
    if not cand:
        return None
    action = str(cand.get('action') or '').upper()
    stance = 'positive' if 'BUY' in action else 'neutral'
    return {
        'stance': stance,
        'as_of': data.get('generated_at'),
        'name': cand.get('name') or cand.get('display_name'),
        'detail': {'rank': cand.get('rank'), 'action': action or None,
                   'alpha_score': cand.get('alpha_score'), 'risk_score': cand.get('risk_score')},
    }


def _src_detection(symbol: str) -> dict[str, Any] | None:
    """워크플로우 TOP3 의 CIO 판정."""
    import app.services.mirofish.workflow as wf

    workflow = wf.read_latest_workflow()
    if not isinstance(workflow, dict):
        return None
    payload = wf.build_share_payload(workflow, rank=None) or {}
    item = next((i for i in (payload.get('top_items') or [])
                 if isinstance(i, dict) and str(i.get('symbol')) == symbol), None)
    if not item:
        return None
    action = str(item.get('action') or '').upper()
    if 'BUY' in action:
        stance = 'positive'
    elif 'SELL' in action:
        stance = 'negative'
    else:
        stance = 'neutral'
    return {
        'stance': stance,
        'as_of': workflow.get('completed_at') or workflow.get('generated_at'),
        'name': item.get('name'),
        'detail': {'action': action or None, 'alpha_score': item.get('alpha_score'),
                   'risk_score': item.get('risk_score'), 'rs_rating': item.get('rs_rating')},
    }


def _src_tradingagents(symbol: str) -> dict[str, Any] | None:
    """딥검증(4애널리스트 → 불/베어 토론 → 리스크) 최신 판정."""
    from app.services.mirofish import scanner_deepverify

    best: dict[str, Any] | None = None
    for key, rec in (scanner_deepverify.latest_by_event_key() or {}).items():
        if not str(key).startswith(f'{symbol}:'):
            continue
        if best is None or str(rec.get('verified_at') or '') >= str(best.get('verified_at') or ''):
            best = rec
    if not best:
        return None
    verdict = str(best.get('verdict') or '').upper()
    if 'BUY' in verdict:
        stance = 'positive'
    elif 'SELL' in verdict:
        stance = 'negative'
    else:
        stance = 'neutral'
    return {
        'stance': stance,
        'as_of': best.get('verified_at'),
        'detail': {'verdict': verdict or None, 'confidence': best.get('confidence'),
                   'strong_buy': best.get('strong_buy'), 'method': best.get('method'),
                   # L4 기계적 검증 결과 — build_decision_brief 가 신뢰 상한에 반영한다
                   'number_verification': best.get('number_verification')},
    }


def _src_paper(symbol: str) -> dict[str, Any] | None:
    """가상 매매 원장 — 시스템이 지금 이 종목을 들고 있는지."""
    from app.services.mirofish.paper_positions import load_ledger

    ledger = load_ledger() or {}
    for state in ('open', 'pending'):
        pos = next((p for p in (ledger.get(state) or [])
                    if str(p.get('symbol')) == symbol), None)
        if pos:
            return {
                'stance': 'positive',
                'as_of': pos.get('entry_date') or pos.get('detected_date'),
                'name': pos.get('name'),
                'detail': {'state': state, 'entry_price': pos.get('entry_price'),
                           'stop_price': pos.get('stop_price'),
                           'target_price': pos.get('target_price')},
            }
    closed = [p for p in (ledger.get('closed') or []) if str(p.get('symbol')) == symbol]
    if not closed:
        return None
    last = sorted(closed, key=lambda p: str(p.get('exit_date') or ''))[-1]
    ret = last.get('return_pct')
    return {
        'stance': 'neutral',
        'as_of': last.get('exit_date'),
        'name': last.get('name'),
        'detail': {'state': 'closed', 'return_pct': ret, 'exit_reason': last.get('exit_reason')},
    }


OBSERVATION_QUERY = (
    'SELECT i.opened_at, o.status, o.return_pct, o.horizon_sessions '
    'FROM signal_instances i LEFT JOIN signal_outcomes o '
    '  ON o.signal_instance_id = i.id '
    'WHERE i.code = ? ORDER BY i.opened_at DESC LIMIT 40'
)


def _src_observation(symbol: str) -> dict[str, Any] | None:
    """관측 원장 — 이 종목의 과거 검출 인스턴스와 실측 성과."""
    import sqlite3

    from marketflow_claw import observation

    try:
        with observation.connect(write=False) as con:
            rows = con.execute(OBSERVATION_QUERY, (symbol,)).fetchall()
    except sqlite3.OperationalError:
        # 관측 원장이 아직 없는 호스트(개발기 등)는 오류가 아니라 데이터 공백이다.
        return None
    if not rows:
        return None

    completed = [r[2] for r in rows if r[1] == 'complete' and r[2] is not None]
    pending = sum(1 for r in rows if r[1] == 'pending')
    if completed:
        avg = sum(completed) / len(completed)
        stance = 'positive' if avg > 0 else ('negative' if avg < 0 else 'neutral')
    else:
        avg, stance = None, 'neutral'
    return {
        'stance': stance,
        'as_of': rows[0][0],
        'detail': {'instances': len({r[0] for r in rows}), 'complete': len(completed),
                   'pending': pending,
                   'avg_return_pct': round(avg, 2) if avg is not None else None},
    }


# ─── 보편 소스 (전 종목, 검출 이력과 무관) ───────────────────

def _src_price_trend(symbol: str) -> dict[str, Any] | None:
    """일봉 추세 — 로컬 시세 원장(전 유니버스)에서 이평·수익률·고점 이격 계산.

    검출 이력이 없는 종목도 항상 평가 가능한 A급 근거다(거래소 시세 실측 파생).
    """
    from app.services.mirofish.alpha_scanner import _load_price_history_cached

    rows = sorted(_load_price_history_cached().get(symbol) or [],
                  key=lambda r: str(r.get('date') or ''))
    closes = [float(r.get('current_price') or 0) for r in rows
              if float(r.get('current_price') or 0) > 0]
    if len(closes) < 21:
        return None
    close = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if len(closes) >= 60 else None
    ret20 = (close / closes[-21] - 1) * 100
    hi120 = max(closes[-120:])
    from_high = (close / hi120 - 1) * 100 if hi120 > 0 else None

    if close > ma20 and (ma60 is None or ma20 > ma60) and ret20 > 0:
        stance = 'positive'
    elif (close < ma20 and ret20 < 0) or ret20 < -15:
        stance = 'negative'
    else:
        stance = 'neutral'
    return {
        'stance': stance,
        'as_of': str(rows[-1].get('date') or ''),
        'detail': {'close': round(close), 'ma20': round(ma20),
                   'ma60': round(ma60) if ma60 is not None else None,
                   'ret_20d_pct': round(ret20, 1),
                   'from_120d_high_pct': round(from_high, 1) if from_high is not None else None,
                   'bars': len(closes)},
    }


def _src_live_flow(symbol: str) -> dict[str, Any] | None:
    """KIS 실시간 시세·투자자 수급 — 30초 TTL 캐시(live_data) 재사용."""
    from app.services.mirofish import live_data

    snap = live_data.load_kis_snapshot({'symbol': symbol})
    if not snap.get('found'):
        return None
    quote = snap.get('quote') or {}
    inv = snap.get('investor') or {}
    chg = quote.get('change_pct')
    f = inv.get('foreign_net_value')
    i = inv.get('institution_net_value')

    both_buy = (f or 0) > 0 and (i or 0) > 0
    both_sell = (f or 0) < 0 and (i or 0) < 0
    if both_buy or ((chg or 0) >= 3 and ((f or 0) > 0 or (i or 0) > 0)):
        stance = 'positive'
    elif both_sell and (chg or 0) < 0:
        stance = 'negative'
    else:
        stance = 'neutral'
    return {
        'stance': stance,
        'as_of': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'detail': {'price': quote.get('price'), 'change_pct': chg,
                   'foreign_net_value': f, 'institution_net_value': i,
                   'per': quote.get('per'), 'pbr': quote.get('pbr')},
    }


def _src_sector_rs(symbol: str) -> dict[str, Any] | None:
    """오닐 상대강도(1~99) — 스캐너가 만든 아티팩트를 읽기만 한다(요청 경로 재계산 금지)."""
    from app.services.mirofish import sector_rs

    ratings = sector_rs.get_rs_ratings(
        data_root=os.path.join(REPO_ROOT, 'data'), allow_compute=False)
    entry = (ratings.get('entries') or {}).get(symbol)
    adj = sector_rs.score_rs_adjustment(entry)
    rs = adj.get('rs_rating')
    if rs is None:
        return None
    stance = 'positive' if rs >= 70 else ('negative' if rs <= 30 else 'neutral')
    return {
        'stance': stance,
        'as_of': ratings.get('generated_at'),
        'detail': {'rs_rating': rs, 'tag': adj.get('tag')},
    }


def _src_risk_flags(symbol: str) -> dict[str, Any] | None:
    """공시·신용 리스크 점검 — KIND 지정 + 신용잔고. '깨끗함'도 정보다(중립)."""
    from app.services.mirofish import blacklist as bl_service
    from app.services.mirofish import credit_balance as cb_service

    b = bl_service.is_blacklisted(symbol, allow_fetch=False)
    credit = cb_service.get_credit_entry(symbol, allow_fetch=False)
    has_data = bool(b.get('fetched_at')) or credit is not None
    if not has_data and not b.get('listed'):
        return None   # 점검 데이터 자체가 없는 호스트 — 공백으로 다룬다

    flags: list[str] = []
    if b.get('listed'):
        flags.append('KIND ' + (','.join(b.get('categories') or []) or '지정'))
    return {
        'stance': 'negative' if flags else 'neutral',
        'as_of': b.get('fetched_at'),
        'detail': {'flags': flags, 'kind_risk_level': b.get('risk_level'),
                   'credit_entry': bool(credit)},
    }


SOURCE_READERS: dict[str, Callable[[str], dict[str, Any] | None]] = {
    # 보편 소스 — 전 종목에서 평가 가능 (2026-09-01 분석력 강화)
    'price': _src_price_trend,
    'flow': _src_live_flow,
    'sector_rs': _src_sector_rs,
    # 검출 이력 소스 — 스캐너/종가베팅에 걸렸던 종목만 값을 가진다
    'claw': _src_claw,
    'jongga': _src_jongga,
    'scanner': _src_scanner,
    'detection': _src_detection,
    'tradingagents': _src_tradingagents,
    'paper': _src_paper,
    'observation': _src_observation,
    # 리스크 점검 — 항상 마지막 줄에 표시
    'risk': _src_risk_flags,
}


# ─── 뉴스 맥락 (L1 옴니소스 → L5) ──────────────────────────

NEWS_LIMIT = 5


def _read_news(symbol: str) -> dict[str, Any]:
    """옴니소스 사건 원장에서 이 종목의 최근 뉴스를 붙인다.

    뉴스는 **방향 판정이 아니라 맥락**이다. 언론 해석(B등급)만으로 후보를 확정할 수
    없다는 근거 규칙에 따라 `signals`(합의 계산)에는 넣지 않고 별도로 반환한다.
    """
    from app.services.omni import ledger as omni_ledger

    rows = omni_ledger.events_for_symbol(symbol, limit=NEWS_LIMIT) or []
    items = [{
        'title': r.get('title'), 'link': r.get('link'), 'source': r.get('source'),
        'grade': r.get('grade'), 'score': r.get('score'),
        'published_ts': r.get('published_ts'), 'corroboration': r.get('corroboration'),
    } for r in rows]
    return {'count': len(items), 'items': items}


# ─── 레짐 / 무효화 ──────────────────────────────────────────

def _read_regime() -> dict[str, Any]:
    """구조 국면(breadth 기반)과 게이트(market_gate)를 함께 읽고 충돌을 표시한다.

    둘은 서로 대체하지 않는 독립 축이다. 상충하면 라벨을 통일하지 않고
    `conflict` 로 남겨 신뢰 상한을 낮춘다.
    """
    phase = gate_status = None
    try:
        from app.services.mirofish.paper_orchestrator import market_phase
        phase = (market_phase() or {}).get('phase')
    except Exception:  # noqa: BLE001 — 레짐 부재는 판단을 막지 않는다
        phase = None
    try:
        with open(MARKET_GATE_PATH, encoding='utf-8') as fp:
            gate_status = (json.load(fp) or {}).get('status')
    except Exception:  # noqa: BLE001
        gate_status = None

    conflict = bool(
        (gate_status == 'RED' and phase in POSITIVE_PHASES)
        or (gate_status == 'GREEN' and phase in NEGATIVE_PHASES)
    )
    return {'phase': phase, 'gate_status': gate_status, 'conflict': conflict}


def _build_invalidators(by_source: dict[str, dict[str, Any]], phase: str | None) -> list[dict[str, Any]]:
    """무효화 조건 — 전부 shadow(관측 전용). 발송·청산을 트리거하지 않는다."""
    out: list[dict[str, Any]] = []
    paper = (by_source.get('paper') or {}).get('detail') or {}
    if paper.get('state') in {'open', 'pending'}:
        if paper.get('stop_price') is not None:
            out.append({'type': 'STOP_LEVEL', 'cond': f"종가 {paper['stop_price']} 이탈",
                        'mode': 'shadow'})
        if paper.get('target_price') is not None:
            out.append({'type': 'TARGET_LEVEL', 'cond': f"종가 {paper['target_price']} 도달",
                        'mode': 'shadow'})
    jongga = (by_source.get('jongga') or {}).get('detail') or {}
    if jongga.get('stop_price') is not None and not out:
        out.append({'type': 'STOP_LEVEL', 'cond': f"종가 {jongga['stop_price']} 이탈",
                    'mode': 'shadow'})
    if 'claw' in by_source:
        out.append({'type': 'DROP_CONFIRMED', 'cond': 'S/A 이탈 3틱 연속 확정', 'mode': 'shadow'})
    if phase:
        out.append({'type': 'PHASE_FLIP', 'cond': '국면이 하락·반등초입으로 전환', 'mode': 'shadow'})
    return out


# ─── 온디맨드 심층 분석 (L2·L3 실행) ────────────────────────

def run_deep_analysis_for(symbol: Any, *, rounds: int | None = None) -> dict[str, Any]:
    """검출 이력이 없는 종목도 에이전트를 직접 돌려 판단 근거를 만든다.

    4 애널리스트 → 불/베어 토론 → 트레이더/리스크 판정을 실행하고, 그 논거를
    그대로 반환한다. LLM 을 호출하므로 GET 조회와 분리된 명시적 실행 경로다.
    딥검증 verdict 는 참고 판정이며 매매 지시가 아니다 — status 어휘는 유지된다.
    """
    code, resolved_name = resolve_symbol(symbol)
    target = resolved_name or code
    stamp = datetime.now(timezone.utc).isoformat()
    out: dict[str, Any] = {
        'schema_version': 'mirofish.deep_analysis.v1',
        'generated_at': stamp, 'symbol': code, 'name': resolved_name,
        'status': 'neutral', 'analysts': [], 'debate': None, 'risk': None,
        'verdict': None, 'verification': None, 'method': None,
        'run_id': None, 'error': None, 'citations': [], 'retrieval': None,
        'disclaimer': '정보 제공 목적이며 투자 권유가 아닙니다. 매매 실행 경로는 시스템에 존재하지 않습니다.',
    }

    # 변형 RAG — 종목 키 검색으로 근거를 모아 토론 프롬프트에 주입한다.
    context_line = ''
    try:
        from app.services.mirofish import retrieval

        retrieved = retrieval.retrieve_for_symbol(code, resolved_name)
        out['citations'] = retrieved.get('citations') or []
        out['retrieval'] = {'news_count': retrieved.get('news_count', 0),
                            'graph_count': retrieved.get('graph_count', 0),
                            'errors': retrieved.get('errors') or {}}
        context_line = retrieval.format_context_line(retrieved)
    except Exception as exc:  # noqa: BLE001 — 검색 실패가 분석을 막지 않는다
        out['retrieval'] = {'error': f'{type(exc).__name__}: {exc}'}

    try:
        from app.services.mirofish.tradingagents import engine

        run = engine.run_deep_analysis(target, symbol=code, rounds=rounds,
                                       context_line=context_line) or {}
    except Exception as exc:  # noqa: BLE001 — 실패해도 화면이 죽지 않게 사유를 돌려준다
        out['error'] = f'{type(exc).__name__}: {exc}'
        return out

    reports = run.get('analyst_reports') or []
    out['analysts'] = [{
        'role': r.get('role'), 'title': r.get('title'), 'stance': r.get('stance'),
        'score': r.get('score'), 'summary': r.get('summary'),
        'evidence': (r.get('evidence') or [])[:6], 'method': r.get('method'),
        'verification': r.get('number_verification'),
    } for r in reports if isinstance(r, dict)]

    debate = run.get('research_debate') or {}
    out['debate'] = {
        'rounds': [{
            'round': d.get('round'),
            'bull': ((d.get('bull') or {}).get('message') or ''),
            'bear': ((d.get('bear') or {}).get('message') or ''),
        } for d in (debate.get('rounds') or [])],
        'manager': debate.get('manager') or {},
        'method': debate.get('method'),
    }

    tr = run.get('trader_risk') or {}
    out['risk'] = tr.get('risk') or tr.get('risk_team') or None
    out['verdict'] = run.get('verdict') or None
    out['method'] = run.get('method')
    out['run_id'] = run.get('id')

    try:
        from app.services.mirofish import number_guard

        out['verification'] = number_guard.aggregate_verification(reports)
    except Exception:  # noqa: BLE001
        out['verification'] = None

    # 판정 어휘는 매매 지시가 될 수 없다 — 참고 스탠스만 상태로 환산한다.
    stance = str(((debate.get('manager') or {}).get('stance')) or '').lower()
    strong = [a for a in out['analysts'] if str(a.get('method')) == 'llm']
    if len(strong) < MIN_STRONG_EVIDENCE:
        out['status'] = 'avoid_data_gap'
    elif stance == 'bull':
        out['status'] = 'watch'
    else:
        out['status'] = 'neutral'
    return out


# ─── 집계 진입점 ────────────────────────────────────────────

def build_decision_brief(symbol: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """한 종목의 모든 독립 근거를 모아 합의·공백·신뢰 상한을 계산한다 (읽기전용)."""
    code, resolved_name = resolve_symbol(symbol)
    stamp = (now or datetime.now(timezone.utc)).isoformat()

    signals: list[dict[str, Any]] = []
    by_source: dict[str, dict[str, Any]] = {}
    data_gaps: list[str] = []
    errors: dict[str, str] = {}
    name: str | None = resolved_name
    # 프로덕션 병목 자가진단 — 어느 소스가 느린지 응답이 스스로 말한다 (2026-08-31 75초 장애).
    timings_ms: dict[str, int] = {}
    t_total = time.perf_counter()

    for source in SOURCE_READERS:
        reader = SOURCE_READERS[source]
        t0 = time.perf_counter()
        try:
            result = reader(code)
        except Exception as exc:  # noqa: BLE001 — 소스 장애가 판단 전체를 막지 않는다
            errors[source] = f'{type(exc).__name__}: {exc}'
            data_gaps.append(source)
            continue
        finally:
            timings_ms[source] = int((time.perf_counter() - t0) * 1000)
        if not result:
            data_gaps.append(source)
            continue
        signal = {
            'source': source,
            'stance': str(result.get('stance') or 'neutral'),
            'grade': result.get('grade') or SOURCE_GRADE.get(source, 'C'),
            'as_of': result.get('as_of'),
            'detail': result.get('detail') or {},
        }
        signals.append(signal)
        by_source[source] = signal
        name = name or result.get('name')

    news = {'count': 0, 'items': []}
    t0 = time.perf_counter()
    try:
        news = _read_news(code)
    except Exception as exc:  # noqa: BLE001 — 뉴스 원장 부재가 판단을 막지 않는다
        errors['news'] = f'{type(exc).__name__}: {exc}'
    timings_ms['news'] = int((time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    regime = _read_regime()
    timings_ms['regime'] = int((time.perf_counter() - t0) * 1000)
    agreement = summarize_agreement(signals)

    # L4 — LLM 산출(딥검증)의 수치 검증 결과를 신뢰 상한에 반영한다.
    verification = None
    ta_detail = (by_source.get('tradingagents') or {}).get('detail') or {}
    raw_verification = ta_detail.get('number_verification')
    if isinstance(raw_verification, dict):
        verification = {k: int(raw_verification.get(k) or 0)
                        for k in ('verified', 'unverified', 'contradicted')}

    cap, cap_reasons = compute_confidence_cap(
        signals, data_gaps=data_gaps, phase=regime.get('phase'),
        agreement=agreement, regime_conflict=bool(regime.get('conflict')),
        verification=verification)

    return {
        'schema_version': SCHEMA_VERSION,
        'generated_at': stamp,
        'symbol': code,
        'name': name,
        'status': decide_status(signals, agreement),
        'signals': signals,
        'agreement': agreement,
        'strong_evidence': strong_evidence_count(signals),
        'data_gaps': data_gaps,
        'invalidators': _build_invalidators(by_source, regime.get('phase')),
        'confidence_cap': cap,
        'cap_reasons': cap_reasons,
        'verification': verification,
        'news': news,
        'regime': regime,
        'errors': errors,
        'timings_ms': dict(timings_ms, total=int((time.perf_counter() - t_total) * 1000)),
        'disclaimer': '정보 제공 목적이며 투자 권유가 아닙니다. 매매 실행 경로는 시스템에 존재하지 않습니다.',
    }
