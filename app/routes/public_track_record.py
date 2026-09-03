# -*- coding: utf-8 -*-
"""공개 Track Record API — 인증 없음, 지연·마스킹 적용 (로드맵 §3.3-4 / §6 Prove).

종가베팅 V2 아카이브(`data/jongga_v2_results_YYYYMMDD.json`)를 비로그인 방문자에게
읽기 전용으로 연다. 구독 가치(당일 신호)는 지키고 검증 가능성(사후 성적)만 노출한다.

경계 (tests/test_public_track_record.py 로 고정):
- 지연 공개: 신호일 이후 거래일이 1일 이상 지난 것만. 당일 신호는 절대 나가지 않는다.
- 마스킹: 신호일 이후 거래일이 5일 미만이면 종목명 `삼성**` + 종목코드 숨김.
- 창: 최근 60 거래일(공개 가능한 아카이브 날짜 기준).
- 사후 수익은 계산하지 않는다. `data/cumulative_performance.json`(yfinance 사후 추적
  캐시)에 같은 (종목코드, 신호일) 행이 있을 때만 그대로 싣고, 없으면
  `forward_return: null` + `verification: 'pending'`.
- 응답은 사용자 특정 정보가 없으므로 `Cache-Control: public, max-age=600`.

거래일 계산은 주중(월~금) 기준이다. 한국 공휴일 달력을 쓰지 않으므로 공휴일이 낀
주에는 지연이 하루 정도 짧게 계산될 수 있다 — 어느 경우에도 당일 신호는 나가지 않는다.
"""
from __future__ import annotations

import glob
import os
import re
from datetime import date, datetime, timedelta
from typing import Any

from flask import Blueprint, jsonify

from app.utils.json_cache import load_json_cached
from app.utils.paths import DATA_DIR

public_track_record_bp = Blueprint('public_track_record', __name__)

WINDOW_TRADING_DAYS = 60   # 공개 창
DELAY_TRADING_DAYS = 1     # 이 미만이면 비공개
MASK_TRADING_DAYS = 5      # 이 미만이면 종목명 마스킹
CACHE_TTL = 600
_ARCHIVE_RE = re.compile(r'jongga_v2_results_(\d{8})\.json$')

METHODOLOGY = {
    'delay': f'신호는 발생일 이후 거래일 {DELAY_TRADING_DAYS}일이 지난 뒤 공개됩니다. 당일 신호는 공개하지 않습니다.',
    'masking': f'발생 후 거래일 {MASK_TRADING_DAYS}일 미만인 신호는 종목명 앞 두 글자만 표시하고 종목코드를 숨깁니다.',
    'window': f'최근 {WINDOW_TRADING_DAYS} 거래일(공개 가능한 분석일 기준)의 신호를 전부 싣습니다. 선별하지 않습니다.',
    'source': '종가베팅 V2 엔진이 매 거래일 저장한 결과 파일을 그대로 읽습니다. 등급·점수·등락률은 신호 당일 값입니다.',
    'forward': '사후 수익은 별도 추적 파일(목표가/손절가 도달 판정, 일봉 기준)에 기록된 경우에만 표시하며, 기록이 없으면 "검증 대기"로 둡니다. 이 페이지에서 수익률을 새로 계산하지 않습니다.',
    'costs': '사후 수익률에는 거래 비용·슬리피지가 반영되어 있지 않습니다.',
}


def _today() -> date:
    return datetime.now().date()


def _trading_days_between(start: date, end: date) -> int:
    """(start, end] 구간의 주중 일수. start >= end 면 0."""
    if start >= end:
        return 0
    count = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += timedelta(days=1)
    return count


def mask_name(name: Any) -> str:
    text = str(name or '').strip()
    if not text:
        return '**'
    keep = 2 if len(text) > 2 else 1
    return text[:keep] + '**'


def _archive_dates(data_dir: str) -> list[tuple[date, str]]:
    out: list[tuple[date, str]] = []
    for path in glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json')):
        m = _ARCHIVE_RE.search(os.path.basename(path))
        if not m:
            continue
        try:
            d = datetime.strptime(m.group(1), '%Y%m%d').date()
        except ValueError:
            continue
        out.append((d, path))
    out.sort(key=lambda item: item[0], reverse=True)
    return out


def _forward_index(data_dir: str) -> dict[tuple[str, str], dict[str, Any]]:
    """cumulative_performance.json → {(code, signal_date): row}. 파일이 없으면 빈 dict."""
    data = load_json_cached(os.path.join(data_dir, 'cumulative_performance.json'), ttl=CACHE_TTL)
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(data, dict):
        return index
    for row in data.get('signals') or []:
        if not isinstance(row, dict):
            continue
        key = (str(row.get('stock_code') or ''), str(row.get('signal_date') or ''))
        if key[0] and key[1]:
            index[key] = row
    return index


def _forward_fields(row: dict[str, Any] | None) -> dict[str, Any]:
    """추적 행이 있어도 가격 데이터가 없어 평가되지 않은 행(OPEN·0일)은 pending."""
    if not row:
        return {'forward_return': None, 'verification': 'pending', 'forward': None}
    outcome = str(row.get('outcome') or 'OPEN')
    days_held = int(row.get('days_held') or 0)
    if outcome == 'OPEN' and days_held <= 0:
        return {'forward_return': None, 'verification': 'pending', 'forward': None}
    verification = 'closed' if outcome in ('TARGET_HIT', 'STOP_HIT') else 'open'
    return {
        'forward_return': row.get('roi_pct'),
        'verification': verification,
        'forward': {
            'outcome': outcome,
            'outcome_date': row.get('outcome_date'),
            'roi_pct': row.get('roi_pct'),
            'hold_roi_pct': row.get('hold_roi_pct'),
            'max_high_pct': row.get('max_high_pct'),
            'days_held': days_held,
        },
    }


def _safe_float(v: Any) -> float | None:
    try:
        if v is None or v == '':
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def build_track_record(data_dir: str | None = None, *, today: date | None = None,
                       window: int = WINDOW_TRADING_DAYS) -> dict[str, Any]:
    data_dir = data_dir or DATA_DIR
    today = today or _today()
    forward = _forward_index(data_dir)

    days: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    for d, path in _archive_dates(data_dir):
        delay = _trading_days_between(d, today)
        if delay < DELAY_TRADING_DAYS:
            continue   # 당일·미래·아직 지연이 안 찬 날은 존재 자체를 숨긴다
        if len(days) >= window:
            break
        data = load_json_cached(path, ttl=CACHE_TTL)
        if not isinstance(data, dict):
            continue
        masked = delay < MASK_TRADING_DAYS
        day_iso = d.isoformat()
        day_signals = [s for s in (data.get('signals') or []) if isinstance(s, dict)]
        day_grade: dict[str, int] = {}
        for sig in day_signals:
            grade = str(sig.get('grade') or '').upper() or '-'
            day_grade[grade] = day_grade.get(grade, 0) + 1
            code = str(sig.get('stock_code') or '')
            score = sig.get('score') if isinstance(sig.get('score'), dict) else {}
            row: dict[str, Any] = {
                'date': day_iso,
                'grade': grade,
                'market': sig.get('market') or None,
                'masked': masked,
                'stock_name': mask_name(sig.get('stock_name')) if masked else str(sig.get('stock_name') or ''),
                'stock_code': None if masked else (code or None),
                'change_pct': _safe_float(sig.get('change_pct')),
                'score_total': score.get('total') if isinstance(score, dict) else None,
            }
            row.update(_forward_fields(forward.get((code, day_iso))))
            signals.append(row)
        days.append({'date': day_iso, 'count': len(day_signals), 'by_grade': day_grade, 'masked': masked})

    by_grade: dict[str, int] = {}
    for row in signals:
        by_grade[row['grade']] = by_grade.get(row['grade'], 0) + 1

    evaluated = [s for s in signals if s['verification'] != 'pending']
    closed = [s for s in evaluated if s['verification'] == 'closed']
    wins = sum(1 for s in closed if s['forward']['outcome'] == 'TARGET_HIT')
    losses = sum(1 for s in closed if s['forward']['outcome'] == 'STOP_HIT')
    closed_roi = [float(s['forward_return']) for s in closed if s['forward_return'] is not None]
    hold_roi = [float(s['forward']['hold_roi_pct']) for s in evaluated
                if s['forward'] and s['forward'].get('hold_roi_pct') is not None]

    grade_stats: dict[str, dict[str, Any]] = {}
    for grade in sorted(by_grade):
        g_closed = [s for s in closed if s['grade'] == grade]
        g_wins = sum(1 for s in g_closed if s['forward']['outcome'] == 'TARGET_HIT')
        g_roi = [float(s['forward_return']) for s in g_closed if s['forward_return'] is not None]
        grade_stats[grade] = {
            'count': by_grade[grade],
            'closed': len(g_closed),
            'wins': g_wins,
            'win_rate': round(g_wins / len(g_closed) * 100, 1) if g_closed else None,
            'avg_roi_pct': round(sum(g_roi) / len(g_roi), 2) if g_roi else None,
        }

    return {
        'schema_version': 'marketflow.public_track_record.v1',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'as_of': days[0]['date'] if days else None,
        'date_range': {'from': days[-1]['date'] if days else None, 'to': days[0]['date'] if days else None},
        'days_count': len(days),
        'window_trading_days': window,
        'sample_size': len(signals),
        'masked_count': sum(1 for s in signals if s['masked']),
        'by_grade': by_grade,
        'verification': {
            'evaluated': len(evaluated),
            'pending': len(signals) - len(evaluated),
            'closed': len(closed),
            'open': len(evaluated) - len(closed),
            'wins': wins,
            'losses': losses,
            'win_rate': round(wins / len(closed) * 100, 1) if closed else None,
            'avg_roi_pct': round(sum(closed_roi) / len(closed_roi), 2) if closed_roi else None,
            'avg_hold_roi_pct': round(sum(hold_roi) / len(hold_roi), 2) if hold_roi else None,
        },
        'grade_stats': grade_stats,
        'days': days,
        'signals': signals,
        'methodology': dict(METHODOLOGY),
        'disclaimer': '성과 지표는 사후 검증 결과이며 미래 수익을 보장하지 않습니다. 투자 판단과 책임은 이용자 본인에게 있습니다.',
    }


@public_track_record_bp.route('/track-record', methods=['GET'])
def public_track_record():
    payload = build_track_record(DATA_DIR)
    resp = jsonify(payload)
    resp.headers['Cache-Control'] = f'public, max-age={CACHE_TTL}'
    return resp
