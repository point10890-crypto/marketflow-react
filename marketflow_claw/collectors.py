"""수집기 — 주도주 스냅샷(파일/KIS)과 레짐 입력(market_gate 캐시).

단일 폴러 원칙: Flask ScreenerWorker가 쓴 screener_leading_latest.json 이
신선하면 KIS 를 직접 부르지 않는다. 직접 호출은 data/claw/kis_poller.lock 을
잡은 한 프로세스만 한다(다른 프로세스가 잡고 있으면 파일로 폴백).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Any

from marketflow_claw.paths import CLAW_DIR, DATA_DIR, LEADERS_LATEST, MARKET_GATE_CACHE, ensure_dirs

FILE_FRESH_SECONDS = 30
KIS_POLLER_LOCK = os.path.join(CLAW_DIR, 'kis_poller.lock')
GRADE_RANK = {'S': 3, 'A': 2, 'B': 1}


def normalize_snapshot(raw: dict[str, Any], *, source: str) -> dict[str, Any]:
    """kis_screener 결과 → Claw 스냅샷. 상위 30개, 필요한 필드만."""
    rows = []
    for r in (raw.get('results') or [])[:30]:
        score = r.get('score') or {}
        total = score.get('total') if isinstance(score, dict) else score
        price = r.get('price')
        high_52w = r.get('high_52w')
        if isinstance(high_52w, dict):  # enricher 형식: {'high_52w': 9690, 'distance_pct': ...}
            high_52w = high_52w.get('high_52w')
        rows.append({
            'code': str(r.get('code') or ''),
            'name': r.get('name') or '',
            'grade': r.get('grade') or '',
            'score': int(total or 0),
            'chg': float(r.get('change_pct') or 0.0),
            'trval_eok': float(r.get('trading_value_eok') or 0.0),
            'volx': float(r.get('volume_ratio') or 0.0),
            'price': float(price) if price not in (None, '') else None,
            'high_52w': float(high_52w) if high_52w not in (None, '') else None,
            'rank': int(r.get('rank') or 0),
        })
    by_grade: dict[str, int] = {}
    for r in rows:
        by_grade[r['grade']] = by_grade.get(r['grade'], 0) + 1
    return {
        'ts': raw.get('timestamp') or datetime.now().isoformat(timespec='seconds'),
        'market_status': raw.get('market_status') or 'unknown',
        'source': source,
        'error': raw.get('error'),
        'by_grade': by_grade,
        'rows': rows,
    }


def _file_age_seconds(path: str) -> float | None:
    if not os.path.isfile(path):
        return None
    return time.time() - os.path.getmtime(path)


def _missing(source: str, error: str) -> dict[str, Any]:
    return {'ts': datetime.now().isoformat(timespec='seconds'), 'market_status': 'unknown',
            'source': source, 'error': error, 'by_grade': {}, 'rows': []}


def load_leaders_file(path: str = LEADERS_LATEST) -> dict[str, Any] | None:
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    snap = normalize_snapshot(raw, source='file')
    snap['file_age_s'] = round(_file_age_seconds(path) or 0, 1)
    return snap


def load_leaders_history(date_str: str) -> dict[str, Any] | None:
    path = os.path.join(DATA_DIR, f'screener_leading_{date_str}.json')
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        raw = json.load(f)
    return normalize_snapshot(raw, source=f'history:{date_str}')


def fetch_leaders_kis() -> dict[str, Any]:
    """KIS 직접 호출 (run_screening 이 latest 파일도 갱신한다). 단일 폴러 락 보유자만."""
    from filelock import FileLock, Timeout

    from app.services.kis_screener import run_screening

    ensure_dirs()
    lock = FileLock(KIS_POLLER_LOCK)
    try:
        lock.acquire(timeout=0)
    except Timeout:
        snap = load_leaders_file()
        if snap is None:
            return _missing('kis', 'kis_poller_busy_and_no_file')
        snap['source'] = 'file(poller_busy)'
        return snap
    try:
        t0 = time.time()
        raw = run_screening(force=True)
        snap = normalize_snapshot(raw, source='kis')
        snap['elapsed_s'] = round(time.time() - t0, 1)
        snap['api_calls'] = raw.get('api_calls')
        return snap
    finally:
        lock.release()


def fetch_leaders(mode: str = 'auto') -> dict[str, Any]:
    """mode: auto | file | kis.  auto = 파일이 30초 이내면 파일, 아니면 KIS."""
    if mode == 'file':
        return load_leaders_file() or _missing('file', 'leaders_file_missing')
    if mode == 'kis':
        return fetch_leaders_kis()
    age = _file_age_seconds(LEADERS_LATEST)
    if age is not None and age <= FILE_FRESH_SECONDS:
        return load_leaders_file()  # type: ignore[return-value]
    return fetch_leaders_kis()


def load_regime_inputs() -> dict[str, Any]:
    """market_gate 캐시(일 1회 갱신)에서 레짐 입력을 읽는다. 없으면 unknown."""
    if not os.path.isfile(MARKET_GATE_CACHE):
        return {'available': False, 'status': None, 'age_hours': None}
    with open(MARKET_GATE_CACHE, 'r', encoding='utf-8') as f:
        d = json.load(f)
    age_h = None
    try:
        upd = datetime.fromisoformat(d.get('updated_at'))
        age_h = round((datetime.now() - upd).total_seconds() / 3600, 1)
    except Exception:  # noqa: BLE001
        pass
    return {
        'available': True,
        'status': d.get('status'),      # GREEN / YELLOW / RED
        'label': d.get('label'),
        'score': d.get('score'),
        'kospi_close': d.get('kospi_close'),
        'kospi_change_pct': d.get('kospi_change_pct'),
        'updated_at': d.get('updated_at'),
        'age_hours': age_h,
    }
