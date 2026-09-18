# -*- coding: utf-8 -*-
"""종목 허브 — Pro 열람 가능한 아티팩트만으로 한 종목의 근거를 모은다 (로드맵 §3.2-3, §3.6-2).

`decision_brief.build_decision_brief` 와 달리 AI Brain 전용 소스(스캐너·CIO·딥검증·
가상원장·GraphRAG)를 읽지 않는다. 여기 실리는 것은 전부 Pro 메뉴가 이미 보여주는
스케줄러 산출물이며, 외부 호출(KIS·yfinance·LLM)은 하지 않는다.

소스별 실패는 격리한다 — 파일이 없으면 null, 예외는 `errors[source]` 로만 남긴다.
"""
from __future__ import annotations

import csv
import glob
import logging
import os
import re
from datetime import datetime
from typing import Any

from app.utils.json_cache import load_json_cached
from app.utils.paths import DATA_DIR, WAVE_DATA_DIR

logger = logging.getLogger(__name__)

WAVE_DIR = WAVE_DATA_DIR
CACHE_TTL = 300
CHART_BARS = 120
HISTORY_LIMIT = 10
HISTORY_SCAN_FILES = 150
NEWS_LIMIT = 8
_CODE_RE = re.compile(r'^[0-9A-Z]{6}$')
_ARCHIVE_RE = re.compile(r'jongga_v2_results_(\d{8})\.json$')

_ticker_map_cache: dict[str, Any] = {'mtime': None, 'rows': {}}


def is_valid_code(code: Any) -> bool:
    return bool(_CODE_RE.match(str(code or '').strip().upper()))


def normalize_code(code: Any) -> str:
    text = str(code or '').strip().upper()
    return text.zfill(6) if text.isdigit() else text


# ── 종목 메타 ─────────────────────────────────────────────────────────────────

def _ticker_map(data_dir: str) -> dict[str, dict[str, str]]:
    """ticker_to_yahoo_map.csv → {code: {name, market}} (mtime 캐시)."""
    path = os.path.join(data_dir, 'ticker_to_yahoo_map.csv')
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}
    if _ticker_map_cache['mtime'] == (path, mtime):
        return _ticker_map_cache['rows']
    rows: dict[str, dict[str, str]] = {}
    try:
        with open(path, encoding='utf-8-sig', newline='') as fp:
            for row in csv.DictReader(fp):
                code = normalize_code(row.get('ticker'))
                if code:
                    rows[code] = {'name': str(row.get('name') or '').strip(),
                                  'market': str(row.get('market') or '').strip()}
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    _ticker_map_cache['mtime'] = (path, mtime)
    _ticker_map_cache['rows'] = rows
    return rows


# ── 가격 ──────────────────────────────────────────────────────────────────────

def _load_price_rows(code: str) -> list[dict[str, Any]]:
    """daily_prices.csv 의 종목 행 — alpha_scanner 의 전 유니버스 메모리 캐시를 공유한다."""
    from app.services.mirofish.alpha_scanner import _load_price_history_cached

    rows = _load_price_history_cached().get(code) or []
    return sorted(rows, key=lambda r: str(r.get('date') or ''))


def _price_block(code: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    rows = [r for r in _load_price_rows(code) if float(r.get('current_price') or 0) > 0]
    if not rows:
        return None, []
    chart = [{
        'date': str(r.get('date') or ''),
        'close': float(r.get('current_price') or 0),
        'high': float(r.get('high') or 0) or None,
        'low': float(r.get('low') or 0) or None,
        'volume': float(r.get('volume') or 0) or None,
    } for r in rows[-CHART_BARS:]]
    last = chart[-1]
    prev_close = chart[-2]['close'] if len(chart) >= 2 else None
    change_pct = round((last['close'] / prev_close - 1) * 100, 2) if prev_close else None
    price = {
        'close': last['close'],
        'prev_close': prev_close,
        'change_pct': change_pct,
        'date': last['date'],
        'bars': len(chart),
        'source': 'daily_prices.csv',
    }
    return price, chart


# ── 소스별 행 추출 ────────────────────────────────────────────────────────────

def _src_jongga(code: str, data_dir: str) -> dict[str, Any] | None:
    data = load_json_cached(os.path.join(data_dir, 'jongga_v2_latest.json'), ttl=CACHE_TTL)
    if not isinstance(data, dict):
        return None
    sig = next((s for s in (data.get('signals') or [])
                if isinstance(s, dict) and normalize_code(s.get('stock_code')) == code), None)
    if not sig:
        return None
    score = sig.get('score') if isinstance(sig.get('score'), dict) else {}
    return {
        'as_of': data.get('updated_at') or data.get('date'),
        'date': data.get('date'),
        'grade': sig.get('grade'),
        'score_total': score.get('total'),
        'score': {k: score.get(k) for k in ('news', 'volume', 'chart', 'candle', 'consolidation',
                                             'supply', 'disclosure', 'analyst') if k in score},
        'llm_reason': score.get('llm_reason'),
        'entry_price': sig.get('entry_price'),
        'stop_price': sig.get('stop_price'),
        'target_price': sig.get('target_price'),
        'change_pct': sig.get('change_pct'),
        'trading_value': sig.get('trading_value'),
        'foreign_5d': sig.get('foreign_5d'),
        'inst_5d': sig.get('inst_5d'),
        'themes': list(sig.get('themes') or [])[:6],
        'sector': sig.get('sector') or None,
        'name': sig.get('stock_name'),
        'market': sig.get('market'),
    }


def _src_leading(code: str, data_dir: str) -> dict[str, Any] | None:
    data = load_json_cached(os.path.join(data_dir, 'screener_leading_latest.json'), ttl=CACHE_TTL)
    if not isinstance(data, dict):
        return None
    row = next((r for r in (data.get('results') or [])
                if isinstance(r, dict) and normalize_code(r.get('code')) == code), None)
    if not row:
        return None
    score = row.get('score') if isinstance(row.get('score'), dict) else {}
    high = row.get('high_52w') if isinstance(row.get('high_52w'), dict) else {}
    investor = row.get('investor') if isinstance(row.get('investor'), dict) else {}
    enrich = row.get('enrichment') if isinstance(row.get('enrichment'), dict) else {}
    return {
        'as_of': data.get('timestamp'),
        'market_status': data.get('market_status'),
        'rank': row.get('rank'),
        'grade': row.get('grade'),
        'score_total': score.get('total_enriched', score.get('total')),
        'price': row.get('price'),
        'change_pct': row.get('change_pct'),
        'trading_value_eok': row.get('trading_value_eok'),
        'volume_ratio': row.get('volume_ratio'),
        'foreign_net': investor.get('foreign_net'),
        'inst_net': investor.get('inst_net'),
        'high_52w_distance_pct': high.get('distance_pct'),
        'market_cap_tier': enrich.get('market_cap_tier') or None,
        'consecutive_days': enrich.get('consecutive_days'),
        'name': row.get('name'),
    }


def _src_vcp(code: str, data_dir: str) -> dict[str, Any] | None:
    data = load_json_cached(os.path.join(data_dir, 'vcp_kr_latest.json'), ttl=CACHE_TTL)
    if not isinstance(data, dict):
        return None
    sig = next((s for s in (data.get('signals') or [])
                if isinstance(s, dict) and normalize_code(s.get('symbol')) == code), None)
    if not sig:
        return None
    meta = data.get('metadata') if isinstance(data.get('metadata'), dict) else {}
    comp = sig.get('composite') if isinstance(sig.get('composite'), dict) else {}
    stage = sig.get('stage') if isinstance(sig.get('stage'), dict) else {}
    vcp = sig.get('vcp_pattern') if isinstance(sig.get('vcp_pattern'), dict) else {}
    rs = sig.get('relative_strength') if isinstance(sig.get('relative_strength'), dict) else {}
    return {
        'as_of': meta.get('generated_at'),
        'gate': meta.get('gate'),
        'composite_score': comp.get('composite_score'),
        'rating': comp.get('rating'),
        'entry_ready': str(comp.get('entry_ready')).lower() == 'true',
        'valid_vcp': str(comp.get('valid_vcp')).lower() == 'true',
        'guidance': comp.get('guidance'),
        'stage_label': stage.get('stage_label'),
        'pivot_price': vcp.get('pivot_price'),
        'num_contractions': vcp.get('num_contractions'),
        'rs_rank': rs.get('rs_rank_estimate', rs.get('score')),
        'price': sig.get('price'),
        'name': sig.get('name'),
    }


def _src_wave(code: str, wave_dir: str) -> dict[str, Any] | None:
    data = load_json_cached(os.path.join(wave_dir, 'wave_screener_latest.json'), ttl=CACHE_TTL)
    if not isinstance(data, dict):
        return None
    sig = next((s for s in (data.get('signals') or [])
                if isinstance(s, dict) and normalize_code(s.get('ticker')) == code), None)
    if not sig:
        return None
    best = sig.get('best_pattern') if isinstance(sig.get('best_pattern'), dict) else {}
    return {
        'as_of': data.get('updated_at') or data.get('date'),
        'pattern_class': best.get('pattern_class'),
        'wave_type': best.get('wave_type'),
        'wave_label': best.get('wave_label'),
        'confidence': best.get('confidence'),
        'completion_pct': best.get('completion_pct'),
        'neckline_price': best.get('neckline_price'),
        'neckline_distance_pct': best.get('neckline_distance_pct'),
        'bullish_bias': best.get('bullish_bias'),
        'volume_confirmed': best.get('volume_confirmed'),
        'pattern_count': sig.get('pattern_count'),
        'price': sig.get('price'),
        'name': sig.get('name'),
    }


def _src_claw(code: str) -> dict[str, Any] | None:
    """마감 기준 주도주 스냅샷 — claw.db 만 읽는다 (스캔·발송 없음)."""
    from marketflow_claw.overview import build_close_leaders

    data = build_close_leaders() or {}
    if data.get('error'):
        return None
    row = next((r for r in (data.get('rows') or [])
                if isinstance(r, dict) and normalize_code(r.get('code')) == code), None)
    if not row:
        return None
    events = [e for e in (row.get('events') or []) if isinstance(e, dict)]
    return {
        'as_of': data.get('snapshot_ts'),
        'day': data.get('day'),
        'grade': row.get('grade'),
        'score': row.get('score'),
        'change_pct': row.get('chg'),
        'trading_value_eok': row.get('trval_eok'),
        'events': [{'type': e.get('type'), 'ts': e.get('ts')} for e in events[:5]],
        'name': row.get('name'),
    }


# ── 이력 / 뉴스 ───────────────────────────────────────────────────────────────

def _forward_index(data_dir: str) -> dict[tuple[str, str], dict[str, Any]]:
    data = load_json_cached(os.path.join(data_dir, 'cumulative_performance.json'), ttl=CACHE_TTL)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(data, dict):
        return out
    for row in data.get('signals') or []:
        if isinstance(row, dict):
            out[(normalize_code(row.get('stock_code')), str(row.get('signal_date') or ''))] = row
    return out


def _history(code: str, data_dir: str, limit: int = HISTORY_LIMIT) -> list[dict[str, Any]]:
    files: list[tuple[str, str]] = []
    for path in glob.glob(os.path.join(data_dir, 'jongga_v2_results_*.json')):
        m = _ARCHIVE_RE.search(os.path.basename(path))
        if m:
            files.append((m.group(1), path))
    files.sort(reverse=True)
    forward = _forward_index(data_dir)
    out: list[dict[str, Any]] = []
    for ymd, path in files[:HISTORY_SCAN_FILES]:
        data = load_json_cached(path, ttl=CACHE_TTL)
        if not isinstance(data, dict):
            continue
        sig = next((s for s in (data.get('signals') or [])
                    if isinstance(s, dict) and normalize_code(s.get('stock_code')) == code), None)
        if not sig:
            continue
        day = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
        score = sig.get('score') if isinstance(sig.get('score'), dict) else {}
        fw = forward.get((code, day))
        entry: dict[str, Any] = {
            'date': day,
            'grade': sig.get('grade'),
            'score_total': score.get('total'),
            'change_pct': sig.get('change_pct'),
            'entry_price': sig.get('entry_price'),
            'stop_price': sig.get('stop_price'),
            'target_price': sig.get('target_price'),
            'outcome': None, 'roi_pct': None, 'hold_roi_pct': None, 'days_held': None,
        }
        if fw and not (str(fw.get('outcome') or 'OPEN') == 'OPEN' and int(fw.get('days_held') or 0) <= 0):
            entry.update({'outcome': fw.get('outcome'), 'roi_pct': fw.get('roi_pct'),
                          'hold_roi_pct': fw.get('hold_roi_pct'), 'days_held': fw.get('days_held')})
        out.append(entry)
        if len(out) >= limit:
            break
    return out


def _news(code: str, limit: int = NEWS_LIMIT) -> list[dict[str, Any]]:
    """옴니 뉴스 원장(omni.db) 종목 사건 — GraphRAG 는 읽지 않는다."""
    from app.services.mirofish.retrieval import _news_for

    items = _news_for(code, limit) or []
    return [{
        'title': it.get('title'), 'link': it.get('link'), 'source': it.get('source'),
        'grade': it.get('grade'), 'score': it.get('score'),
        'published_ts': it.get('published_ts'), 'summary': (it.get('summary') or '')[:200] or None,
    } for it in items if isinstance(it, dict)]


# ── 조립 ──────────────────────────────────────────────────────────────────────

def build_stock_hub(raw_code: Any, *, data_dir: str | None = None,
                    wave_dir: str | None = None) -> dict[str, Any]:
    code = normalize_code(raw_code)
    if not is_valid_code(code):
        raise ValueError(f'invalid stock code: {raw_code!r}')
    data_dir = data_dir or DATA_DIR
    wave_dir = wave_dir or WAVE_DIR
    errors: dict[str, str] = {}

    def _guard(name: str, fn, default):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — 소스 하나가 허브 전체를 막지 않는다
            logger.warning('stock hub source %s failed for %s: %s', name, code, exc)
            errors[name] = f'{type(exc).__name__}: {exc}'
            return default

    price, chart = _guard('price', lambda: _price_block(code), (None, []))
    sources = {
        'jongga': _guard('jongga', lambda: _src_jongga(code, data_dir), None),
        'leading': _guard('leading', lambda: _src_leading(code, data_dir), None),
        'vcp': _guard('vcp', lambda: _src_vcp(code, data_dir), None),
        'wave': _guard('wave', lambda: _src_wave(code, wave_dir), None),
        'claw': _guard('claw', lambda: _src_claw(code), None),
    }
    history = _guard('history', lambda: _history(code, data_dir), [])
    news = _guard('news', lambda: _news(code), [])

    meta = _ticker_map(data_dir).get(code) or {}
    name = meta.get('name') or next((s.get('name') for s in sources.values() if s and s.get('name')), None)
    market = meta.get('market') or (sources['jongga'] or {}).get('market') or None
    sector = (sources['jongga'] or {}).get('sector')

    return {
        'schema_version': 'marketflow.stock_hub.v1',
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'code': code,
        'name': name,
        'market': market,
        'sector': sector,
        'price': price,
        'chart': chart,
        'sources': sources,
        'present': [k for k, v in sources.items() if v],
        'history': history,
        'news': news,
        'errors': errors,
        'disclaimer': '이 화면은 시스템이 이미 저장한 관찰 결과를 한 종목 기준으로 모은 것이며 매수·매도 지시가 아닙니다.',
    }
