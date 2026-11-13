"""Read-only reuse of AlphaLab's sealed TOP100 financial-quality daily cohort.

Provider daily bars are estimator inputs, never evidence for E1 resolution.
Today's constituent selection is not a historical point-in-time universe.
"""
from __future__ import annotations

from datetime import date

from app.services.forecast_league import capsules, clock


def snapshot(conn, asof_date):
    row = conn.execute('SELECT capsule_hash FROM universe_snapshots WHERE asof_date=?', (asof_date,)).fetchone()
    return (row['capsule_hash'], capsules.get_capsule(conn, row['capsule_hash'])) if row else (None, None)


def sync_saved_universe(conn, *, today, loader=None):
    asof = clock.previous_trading_day(date.fromisoformat(today)).isoformat()
    digest, saved = snapshot(conn, asof)
    if saved is not None:
        return {'asof_date': asof, 'codes': len(saved['prices_by_symbol']), 'capsule_hash': digest, 'reused': True}
    if loader is None:
        from app.services.mirofish.alpha_lab.candidate_inputs import load_inputs
        from app.services.mirofish.alpha_lab.service import ROOT
        loader = lambda: load_inputs(ROOT / 'candidate-desk' / 'inputs')
    data = loader()  # Revalidates sealed public responses, identities and 20:30 capture cutoff.
    prices = data['prices_by_symbol']
    if data['latest_session'] != asof or not 1 <= len(prices) <= 100:
        raise RuntimeError('sealed_universe_stale_or_scope_invalid')
    # Freeze the exact calculation inputs; later daily-price revisions cannot rewrite them.
    digest = capsules.put_capsule(conn, data)
    conn.execute('INSERT INTO universe_snapshots VALUES (?, ?)', (asof, digest))
    return {'asof_date': asof, 'codes': len(prices), 'capsule_hash': digest, 'reused': False}
