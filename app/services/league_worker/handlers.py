"""잡 종류별 실행. 로직은 forecast_league 에 있고 여기서는 연결만 한다."""
from __future__ import annotations

import sqlite3
from typing import Any, Callable

from app.services.forecast_league import baselines, candidates, clock, price_sources, resolver, scorecards


def _sync_universe(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    return price_sources.sync_universe_bars(conn, today=args['today'])


def _submit_baselines(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    codes = candidates.jongga_candidates(args['asof_date'])
    return {'candidates': len(codes),
            **baselines.submit_baselines(conn, asof_date=args['asof_date'], stock_codes=codes)}


def _collect_regular(conn: sqlite3.Connection, args: dict[str, Any]) -> dict[str, Any]:
    from app.services.mirofish.alpha_lab.regular_source import KISRegularProvider
    targets = price_sources.needed_regular_targets(conn, now=clock.now_utc())
    return price_sources.collect_regular_bars(conn, provider=KISRegularProvider(), targets=targets)


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
