"""잡 종류별 실행. 로직은 forecast_league 에 있고 여기서는 연결만 한다."""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from app.services.forecast_league import baselines, clock, price_sources, resolver, scorecards, saved_universe

def _sync_universe(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    return saved_universe.sync_saved_universe(conn, today=args['today'])


def _submit_baselines(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    _, snapshot = saved_universe.snapshot(conn, args['asof_date'])
    if snapshot is None:
        raise RuntimeError('sealed_universe_missing')
    codes = sorted(snapshot['prices_by_symbol'])
    return {'candidates': len(codes),
            **baselines.submit_baselines(conn, asof_date=args['asof_date'], stock_codes=codes)}


def _collect_regular(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.forecast_league.regular_vi import LeagueRegularProvider
    targets = price_sources.needed_regular_targets(conn, now=clock.now_utc())
    summary = price_sources.collect_regular_bars(conn, provider=LeagueRegularProvider(), targets=targets)
    if summary['failed']:
        # 한 건도 못 받았으면 공급자 장애로 보고 잡을 실패시켜 재시도·알림이 걸리게 한다.
        raise RuntimeError(f"regular bars incomplete: {summary['stored']} of {len(targets)} targets stored, "
                           f"failed={len(summary['failed'])} sample={summary['failed'][:3]}")
    return summary


def _resolve(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    return resolver.resolve_pending(conn, today=args['today'])


def _score(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    cards = scorecards.compute_scorecards(conn)
    return {'scorecards': len(cards), 'scored': sum(1 for card in cards if card['status'] == 'scored')}


HANDLERS: dict[str, Callable[[sqlite3.Connection, dict[str, Any]], Any]] = {
    'sync_universe': _sync_universe,
    'submit_baselines': _submit_baselines,
    'collect_regular': _collect_regular,
    'resolve': _resolve,
    'score': _score,
}
