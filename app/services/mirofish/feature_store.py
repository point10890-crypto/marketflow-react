# -*- coding: utf-8 -*-
"""피처 스냅샷 리더 — 날짜별 아카이브에서 신호 시점 피처를 순회한다.

종가베팅 V2(`jongga_v2_results_YYYYMMDD.json`) 와 주도주(`screener_leading_YYYYMMDD.json`)
는 v3.6 부터 행마다 `feature_snapshot` 을 남긴다. 이 모듈은 그것을 캘리브레이션
스크립트가 소비할 수 있게 **읽기 전용**으로 평탄화해 yield 한다.

불변조건
    - 읽기전용. 파일을 쓰거나 지우지 않는다.
    - 손상된 파일·스냅샷 없는 행은 조용히 건너뛴다 (부분 아카이브가 정상).
    - 날짜 필터는 파일명 날짜(YYYYMMDD) 기준 — lookahead 없음.
"""
from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Iterator

from app.utils.paths import DATA_DIR

KINDS = {
    'jongga_v2': {
        'pattern': 'jongga_v2_results_*.json',
        'regex': re.compile(r'jongga_v2_results_(\d{8})\.json$'),
        'rows_key': 'signals',
        'symbol_key': 'stock_code',
        'name_key': 'stock_name',
    },
    'leading': {
        'pattern': 'screener_leading_*.json',
        'regex': re.compile(r'screener_leading_(\d{8})\.json$'),
        'rows_key': 'results',
        'symbol_key': 'code',
        'name_key': 'name',
    },
}


def _normalize_date(value: Any) -> str | None:
    """'2026-09-02' / '20260902' / date → 'YYYYMMDD'. 해석 불가면 None."""
    if value is None:
        return None
    if hasattr(value, 'strftime'):
        return value.strftime('%Y%m%d')
    digits = re.sub(r'[^0-9]', '', str(value))
    return digits if len(digits) == 8 else None


def list_snapshot_files(kind: str, date_from: Any = None, date_to: Any = None,
                        *, data_dir: str | None = None) -> list[tuple[str, str]]:
    """(YYYYMMDD, path) 오름차순 목록. latest 파일은 날짜가 없으므로 제외된다."""
    spec = KINDS.get(kind)
    if not spec:
        raise ValueError(f'unknown feature snapshot kind: {kind!r} (expected one of {sorted(KINDS)})')
    base = data_dir or DATA_DIR
    lo = _normalize_date(date_from)
    hi = _normalize_date(date_to)
    out: list[tuple[str, str]] = []
    for path in glob.glob(os.path.join(base, spec['pattern'])):
        m = spec['regex'].search(os.path.basename(path))
        if not m:
            continue
        day = m.group(1)
        if lo and day < lo:
            continue
        if hi and day > hi:
            continue
        out.append((day, path))
    out.sort()
    return out


def _load(path: str) -> dict[str, Any] | None:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def iter_feature_snapshots(kind: str, date_from: Any = None, date_to: Any = None,
                           *, data_dir: str | None = None) -> Iterator[dict[str, Any]]:
    """날짜별 아카이브에서 `feature_snapshot` 을 가진 행을 순회한다.

    yield 항목::

        {
          'kind': 'jongga_v2' | 'leading',
          'date': 'YYYYMMDD',          # 파일명 날짜
          'symbol': '005930',
          'name': '삼성전자',
          'grade': 'A',
          'score_total': 11,
          'snapshot': {...},           # 행의 feature_snapshot 원형
          'path': '/.../jongga_v2_results_20260902.json',
        }
    """
    spec = KINDS[kind] if kind in KINDS else None
    if spec is None:
        raise ValueError(f'unknown feature snapshot kind: {kind!r} (expected one of {sorted(KINDS)})')

    for day, path in list_snapshot_files(kind, date_from, date_to, data_dir=data_dir):
        data = _load(path)
        if not data:
            continue
        rows = data.get(spec['rows_key'])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            snapshot = row.get('feature_snapshot')
            if not isinstance(snapshot, dict):
                continue
            score = row.get('score') if isinstance(row.get('score'), dict) else {}
            yield {
                'kind': kind,
                'date': day,
                'symbol': str(row.get(spec['symbol_key']) or ''),
                'name': str(row.get(spec['name_key']) or ''),
                'grade': str(row.get('grade') or ''),
                'score_total': score.get('total'),
                'snapshot': snapshot,
                'path': path,
            }
