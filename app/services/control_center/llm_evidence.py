"""Bounded read-only evidence of real router calls; never sends inference requests."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from app.services.control_center.local_checks import _parse_ts, resolve_path
from app.services.control_center.model import CheckResult


def routing_evidence(config: dict, now: datetime, providers: list[str]) -> CheckResult:
    path = Path(resolve_path(config['usage_path']))
    rows = []
    try:
        # mode=ro avoids creating/migrating a usage DB from a monitor process.
        with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA query_only=ON')
            for provider in providers:
                row = conn.execute('''SELECT provider, model, operation, status, error_class, event_ts_utc
                    FROM provider_attempts WHERE provider=? AND cache_hit=0
                    AND status NOT GLOB 'skipped_*'
                    ORDER BY event_ts_utc DESC LIMIT 1''', (provider,)).fetchone()
                rows.append(dict(row) if row else {'provider': provider})
    except (OSError, sqlite3.Error):
        return CheckResult('provider:' + config['id'], 'provider', config['label'], 'unknown',
                           '실제 호출 원장을 읽을 수 없음 (읽기 전용 점검)')
    max_age = float(config.get('usage_max_age_hours', 72))
    missing, failed = [], []
    evidence = []
    for row in rows:
        provider = row['provider']
        stamp = _parse_ts(row.get('event_ts_utc'))
        age = (now - stamp).total_seconds() / 3600 if stamp else None
        current = age is not None and 0 <= age <= max_age
        status = 'unknown' if not current else ('ok' if row.get('status') == 'success' else 'warn')
        if status == 'unknown':
            missing.append(provider)
        elif status == 'warn':
            failed.append(provider)
        evidence.append({'provider': provider, 'status': status, 'observed_at': row.get('event_ts_utc'),
                         'age_hours': round(age, 2) if age is not None else None,
                         'operation': row.get('operation'), 'model': row.get('model'),
                         'error_class': row.get('error_class')})
    status = 'warn' if failed else ('unknown' if missing or not providers else 'ok')
    detail = f'최근 {max_age:g}시간 실제 호출 · 정상 {len(providers)-len(failed)-len(missing)}/{len(providers)}곳'
    if failed:
        detail += ' · 마지막 호출 실패: ' + ', '.join(failed)
    if missing:
        detail += ' · 최근 관측 없음: ' + ', '.join(missing)
    return CheckResult('provider:' + config['id'], 'provider', config['label'], status, detail,
                       value={'providers': evidence}, data={'basis': 'physical_call_ledger', 'window_hours': max_age,
                       'live_probe': False, 'scope': '마지막 실제 호출 결과이며 현재 모든 모델의 가용성 보장은 아님'})
