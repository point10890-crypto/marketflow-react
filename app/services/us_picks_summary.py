"""US Smart Money picks 히스토리 성과 요약 — 순수 함수 + 사전계산 파일.

리뷰(2026-09-02 §3.5): ``/api/us/history-summary`` 가 요청마다 ``us_market/history/picks_*.json``
전부를 열고 pick 마다 pandas 스캔(O(dates × picks × rows))을 돌렸다. 이 모듈은 그 집계를
라우트 밖으로 꺼내(``build_picks_summary``) 결과를 ``us_market/output/picks_summary.json`` 에
원자적으로 저장하고, 라우트는 파일이 최신이면 그대로 서빙한다(self-healing: 없거나 오래되면
즉시 재계산 후 저장). 스케줄러 훅은 별도 — 이 모듈은 파일 신선도 판정만 제공한다.

신선도: summary 파일 mtime 이 (가장 새 picks 파일 mtime, 가격 CSV mtime) 둘 다보다 새로워야 한다.
가격 CSV 가 갱신되면 같은 picks 라도 수익률이 달라지므로 CSV 도 기준에 넣는다.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic
from app.utils.json_cache import load_json_cached

logger = logging.getLogger(__name__)

SUMMARY_FILENAME = 'picks_summary.json'
_PICKS_PREFIX = 'picks_'
_PICKS_SUFFIX = '.json'


def list_picks_files(history_dir: str) -> list[str]:
    """``picks_<date>.json`` 파일 절대경로 목록 (파일명 정렬)."""
    try:
        names = sorted(
            name for name in os.listdir(history_dir)
            if name.startswith(_PICKS_PREFIX) and name.endswith(_PICKS_SUFFIX)
        )
    except OSError:
        return []
    return [os.path.join(history_dir, name) for name in names]


def newest_source_mtime(history_dir: str, latest_csv: str) -> float | None:
    """집계 입력(가장 새 picks 파일, 가격 CSV) 중 가장 늦은 mtime. 입력이 없으면 None."""
    mtimes: list[float] = []
    for path in list_picks_files(history_dir):
        try:
            mtimes.append(os.path.getmtime(path))
        except OSError:
            continue
    try:
        mtimes.append(os.path.getmtime(latest_csv))
    except OSError:
        pass
    return max(mtimes) if mtimes else None


def is_summary_fresh(summary_path: str, history_dir: str, latest_csv: str) -> bool:
    """summary 파일이 존재하고 모든 입력보다 새로우면 True."""
    try:
        summary_mtime = os.path.getmtime(summary_path)
    except OSError:
        return False
    source_mtime = newest_source_mtime(history_dir, latest_csv)
    if source_mtime is None:
        return False
    return summary_mtime >= source_mtime


def _load_snapshot(path: str) -> dict[str, Any] | None:
    data = load_json_cached(path, ttl=3600)
    return data if isinstance(data, dict) else None


def build_picks_summary(history_dir: str, latest_csv: str) -> dict[str, Any]:
    """picks 히스토리 × 최신 종가로 날짜별/전체 성과를 계산한다 (라우트와 동일한 수식).

    Returns:
        {'overall': {...}, 'by_date': [...], 'generated_at': iso, 'source': {...}}
        입력이 없으면 overall={} , by_date=[] 인 빈 요약.
    """
    import numpy as np
    import pandas as pd

    picks_files = list_picks_files(history_dir)
    generated_at = datetime.now(timezone.utc).isoformat()
    empty: dict[str, Any] = {
        'overall': {},
        'by_date': [],
        'generated_at': generated_at,
        'source': {'picks_files': len(picks_files), 'latest_csv': os.path.basename(latest_csv), 'latest_date': None},
    }
    if not picks_files or not os.path.exists(latest_csv):
        return empty

    try:
        df = pd.read_csv(latest_csv, encoding='utf-8-sig')
    except Exception as exc:  # noqa: BLE001 — 깨진 CSV 는 빈 요약 (라우트가 404/빈 결과 처리)
        logger.warning('[us_picks_summary] price csv unreadable: %s', type(exc).__name__)
        return empty
    if df.empty or 'Date' not in df.columns or 'Ticker' not in df.columns or 'Close' not in df.columns:
        return empty

    latest_date = df['Date'].max()
    latest_df = df[df['Date'] == latest_date]
    # pick 마다 pandas 스캔 대신 한 번만 dict 로 — 중복 티커는 첫 행(기존 iloc[0] 과 동일)
    latest_close = (
        latest_df.drop_duplicates('Ticker', keep='first')
        .set_index('Ticker')['Close']
        .to_dict()
    )
    spy_df = df[df['Ticker'] == 'SPY'].sort_values('Date')

    summaries: list[dict[str, Any]] = []
    for path in picks_files:
        name = os.path.basename(path)
        date_str = name[len(_PICKS_PREFIX):-len(_PICKS_SUFFIX)]
        snapshot = _load_snapshot(path)
        if snapshot is None:
            logger.warning('[us_picks_summary] skipping unreadable snapshot %s', name)
            continue

        changes: list[float] = []
        for pick in snapshot.get('picks') or []:
            if not isinstance(pick, dict):
                continue
            ticker = pick.get('ticker')
            try:
                price_at_rec = float(pick.get('price_at_analysis') or 0)
            except (TypeError, ValueError):
                price_at_rec = 0.0
            if ticker in latest_close and price_at_rec > 0:
                try:
                    current = float(latest_close[ticker])
                except (TypeError, ValueError):
                    continue
                changes.append(((current / price_at_rec) - 1) * 100)

        if not changes:
            continue

        window = spy_df[spy_df['Date'] >= date_str]
        spy_return = 0.0
        if len(window) >= 2:
            spy_return = ((float(window['Close'].iloc[-1]) / float(window['Close'].iloc[0])) - 1) * 100

        avg_return = float(np.mean(changes))
        summaries.append({
            'date': date_str,
            'avg_return': round(avg_return, 2),
            'spy_return': round(spy_return, 2),
            'alpha': round(avg_return - spy_return, 2),
            'win_rate': round(len([c for c in changes if c > 0]) / len(changes) * 100, 1),
            'num_picks': len(changes),
        })

    summaries.sort(key=lambda item: item['date'], reverse=True)

    overall: dict[str, Any] = {}
    if summaries:
        overall = {
            'total_recommendations': sum(s['num_picks'] for s in summaries),
            'avg_return_all': round(float(np.mean([s['avg_return'] for s in summaries])), 2),
            'avg_alpha': round(float(np.mean([s['alpha'] for s in summaries])), 2),
            'avg_win_rate': round(float(np.mean([s['win_rate'] for s in summaries])), 1),
            'num_dates': len(summaries),
        }

    return {
        'overall': overall,
        'by_date': summaries,
        'generated_at': generated_at,
        'source': {
            'picks_files': len(picks_files),
            'latest_csv': os.path.basename(latest_csv),
            'latest_date': str(latest_date),
        },
    }


def load_or_build_picks_summary(history_dir: str, latest_csv: str, summary_path: str) -> dict[str, Any]:
    """신선한 ``summary_path`` 가 있으면 그것을, 아니면 계산 후 저장(원자적)하고 돌려준다.

    저장 실패는 결과에 영향을 주지 않는다 (다음 요청이 다시 계산할 뿐).
    """
    if is_summary_fresh(summary_path, history_dir, latest_csv):
        cached = load_json_cached(summary_path, ttl=60)
        if isinstance(cached, dict) and 'by_date' in cached:
            return cached

    summary = build_picks_summary(history_dir, latest_csv)
    try:
        write_json_atomic(summary_path, summary)
    except Exception as exc:  # noqa: BLE001
        logger.warning('[us_picks_summary] failed to persist %s: %s', summary_path, type(exc).__name__)
    return summary


def to_route_payload(summary: dict[str, Any]) -> dict[str, Any]:
    """라우트 응답 형태(overall/by_date + 부가 메타)."""
    return {
        'overall': summary.get('overall') or {},
        'by_date': summary.get('by_date') or [],
        'generated_at': summary.get('generated_at'),
        'source': summary.get('source') or {},
    }


def dumps_for_debug(summary: dict[str, Any]) -> str:  # pragma: no cover - 운영 진단용
    return json.dumps(summary, ensure_ascii=False, indent=2)
