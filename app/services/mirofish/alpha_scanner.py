"""Deterministic file-backed alpha scanner for MiroFish Phase 1."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DATA_ROOT = os.path.join(REPO_ROOT, 'data')
SCANNER_RUNS_ROOT = os.path.join(DATA_ROOT, 'admin_mirofish', 'scanner_runs')

MAX_CANDIDATES = 100
DEFAULT_LIMIT = 30
DEFAULT_ALERT_LIMIT = 20
DEFAULT_ALERT_MIN_ALPHA = 70.0
DEFAULT_ALERT_MAX_RISK = 45.0
DEFAULT_ALERT_MAX_EVENTS = 8
DEFAULT_SCHEDULE_TIMES = '09:20,11:20,14:20,15:40,16:10'
KST = timezone(timedelta(hours=9))

SCORING_SCHEMA = {
    'alpha_score': {
        'description': 'Profit-potential score from deterministic local artifacts.',
        'components': {
            'price_momentum': '0..25 from latest daily change_rate.',
            'liquidity': '0..15 from trading value or price*volume.',
            'screener_leading': '0..25 from screener score.total_enriched/total.',
            'vcp_quality': '0..20 from VCP composite_score and entry-ready flag.',
            'jongga_setup': '0..15 from jongga_v2 total score and checklist.',
        },
    },
    'risk_score': {
        'description': 'Penalty score where higher means worse entry/risk quality.',
        'components': {
            'overextension': 'Large one-day moves increase risk.',
            'intraday_range': 'Wide high-low range increases execution risk.',
            'liquidity_gap': 'Missing or thin trading value increases risk.',
            'artifact_staleness': 'Older source artifacts increase risk.',
            'negative_flags': 'Negative news, suspicious volume, or long upper wick add risk.',
        },
    },
    'ranking': 'rank by alpha_score - 0.45 * risk_score, descending.',
}


def create_scanner_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    limit = _clean_limit(payload.get('limit'), default=DEFAULT_LIMIT)
    requested_symbols = _clean_symbols(payload.get('symbols'))
    generated_at = datetime.now(timezone.utc).isoformat()
    run_id = _run_id(generated_at, requested_symbols, limit)

    artifacts = _load_artifacts()
    candidates = _build_candidates(
        artifacts,
        generated_at=generated_at,
        limit=limit,
        requested_symbols=requested_symbols,
    )
    source_files = _source_files(artifacts)
    run = {
        'id': run_id,
        'status': 'completed',
        'mode': 'deterministic_file_artifacts',
        'source': 'local_marketflow_artifacts',
        'generated_at': generated_at,
        'created_at': generated_at,
        'limit': limit,
        'requested_symbols': sorted(requested_symbols),
        'universe_size': len(artifacts['candidate_symbols']),
        'candidate_count': len(candidates),
        'scoring_schema': SCORING_SCHEMA,
        'source_files': source_files,
        'freshness': _aggregate_freshness(source_files),
        'candidates': candidates,
        'links': {
            'self': f'/api/admin/mirofish/scanner/runs/{run_id}',
            'candidates': f'/api/admin/mirofish/scanner/runs/{run_id}/candidates',
        },
    }

    write_json_atomic(_run_path(run_id), run, sort_keys=False)
    return run


def read_scanner_run(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = _run_path(safe_id)
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def read_scanner_candidates(run_id: str) -> dict[str, Any] | None:
    run = read_scanner_run(run_id)
    if run is None:
        return None
    return {
        'run_id': run['id'],
        'generated_at': run.get('generated_at'),
        'source': run.get('source'),
        'freshness': run.get('freshness'),
        'candidate_count': len(run.get('candidates') or []),
        'candidates': run.get('candidates') or [],
    }


def list_scanner_runs(limit: int = 20) -> list[dict[str, Any]]:
    """Return recent scanner run summaries without loading candidate payloads."""
    records = _scanner_run_records()
    clean_limit = max(1, min(_clean_limit(limit, default=20), 100))
    return [_scanner_run_summary(item['run']) for item in records[:clean_limit]]


def read_latest_scanner_run() -> dict[str, Any] | None:
    """Return the newest persisted scanner run, if one exists."""
    records = _scanner_run_records()
    return records[0]['run'] if records else None


def get_scanner_schedule_status(now: datetime | None = None) -> dict[str, Any]:
    """Return alpha scanner schedule, latest run, and source freshness status."""
    current = (now or datetime.now(KST)).astimezone(KST)
    scheduled_times = _scanner_schedule_times()
    latest = read_latest_scanner_run()
    artifacts = _load_artifacts()
    source_files = latest.get('source_files') if latest else None
    if not source_files:
        source_files = _source_files(artifacts)
    freshness = latest.get('freshness') if latest else None
    if not freshness:
        freshness = _aggregate_freshness(source_files)
    scheduler_last_run_at = _scheduler_last_run_at()
    next_scheduled = _next_scheduled_times(current, scheduled_times, count=5)
    return {
        'enabled': os.getenv('ALPHA_SCANNER_ENABLED', 'true').strip().lower() == 'true',
        'timezone': 'Asia/Seoul',
        'scheduled_times': [item.strftime('%H:%M') for item in scheduled_times],
        'next_scheduled_times': next_scheduled,
        'next_scheduled_at': next_scheduled[0] if next_scheduled else None,
        'last_run_id': latest.get('id') if latest else None,
        'last_run_at': (latest or {}).get('generated_at') or (latest or {}).get('created_at'),
        'scheduler_last_run_at': scheduler_last_run_at,
        'freshness': freshness,
        'freshness_status': (freshness or {}).get('status'),
        'source_files': source_files,
        'candidate_count': latest.get('candidate_count') if latest else 0,
        'checked_at': current.isoformat(),
    }


def run_scanner_alert_check(
    payload: dict[str, Any] | None = None,
    *,
    state_path: str | None = None,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
    actions: tuple[str, ...] = ('BUY_CANDIDATE',),
    max_events: int = DEFAULT_ALERT_MAX_EVENTS,
) -> dict[str, Any]:
    """Create a scanner run and return only newly-qualified alert events.

    The state file stores stable symbol/action keys so a scheduled job can run
    repeatedly without spamming Telegram with the same candidate.
    """
    run_payload = dict(payload or {})
    run_payload.setdefault('limit', DEFAULT_ALERT_LIMIT)
    run = create_scanner_run(run_payload)
    state_file = state_path or _alert_state_path()
    state = _read_alert_state(state_file)
    events = _new_candidate_events(
        run,
        state,
        min_alpha=float(min_alpha),
        max_risk=float(max_risk),
        actions=actions,
        max_events=max_events,
    )
    updated_state = _update_alert_state(state, run, events)
    write_json_atomic(state_file, updated_state, sort_keys=True)
    return {
        'run': run,
        'events': events,
        'message': build_scanner_alert_message(run, events, min_alpha=min_alpha, max_risk=max_risk),
        'state_path': state_file,
        'new_event_count': len(events),
    }


def build_scanner_alert_message(
    run: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    min_alpha: float = DEFAULT_ALERT_MIN_ALPHA,
    max_risk: float = DEFAULT_ALERT_MAX_RISK,
) -> str:
    generated_at = _escape(run.get('generated_at') or '')
    run_id = _escape(run.get('id') or '')
    candidate_count = int(run.get('candidate_count') or 0)
    lines = [
        '<b>미로피쉬 알파 스캐너</b>',
        f'신규 매수 후보: <b>{len(events)}</b>건 / 전체 후보: {candidate_count}건',
        f'기준: 알파 &gt;= {min_alpha:g}, 리스크 &lt;= {max_risk:g}, 로컬 데이터 기반 결정론 스캔',
        f'실행 ID: <code>{run_id}</code>',
        f'생성 시각: {generated_at}',
    ]
    if not events:
        lines.append('이전 알림 이후 새 조건 충족 후보가 없습니다.')
        return '\n'.join(lines)

    for event in events:
        candidate = event['candidate']
        evidence = (candidate.get('evidence') or [{}])[0]
        tags = ', '.join(_tag_label(tag) for tag in (candidate.get('strategy_tags') or [])[:4])
        price = candidate.get('price') or {}
        current_price = _format_number(price.get('current_price'))
        lines.extend([
            '',
            (
                f"#{candidate.get('rank')} <b>{_escape(candidate.get('display_name'))}</b> "
                f"(<code>{_escape(candidate.get('symbol'))}</code> {_escape(candidate.get('market'))})"
            ),
            (
                f"알파 <b>{candidate.get('alpha_score')}</b> / "
                f"리스크 <b>{candidate.get('risk_score')}</b> / "
                f"순위점수 {candidate.get('ranking_score')}"
            ),
            (
                f"판정: <b>{_escape(_action_label(candidate.get('action')))}</b> / "
                f"투자기간: {_escape(_horizon_label(candidate.get('horizon')))}"
            ),
            f"현재가: {current_price} / 전략태그: {_escape(tags)}",
            (
                f"근거: {_escape(evidence.get('source'))} "
                f"{_escape(_evidence_field_label(evidence.get('field')))}={evidence.get('score')}"
            ),
        ])
    return '\n'.join(lines)


def _load_artifacts() -> dict[str, Any]:
    screener = _load_json_artifact('screener_leading_latest.json')
    vcp = _load_json_artifact('vcp_kr_latest.json')
    jongga = _load_json_artifact('jongga_v2_latest.json')

    maps = _load_ticker_map()
    candidate_symbols = set()
    candidate_symbols.update(_symbols_from_screener(screener.get('data')))
    candidate_symbols.update(_symbols_from_vcp(vcp.get('data')))
    candidate_symbols.update(_symbols_from_jongga(jongga.get('data')))

    latest_prices = _load_latest_prices(candidate_symbols or None)
    if not candidate_symbols:
        candidate_symbols.update(latest_prices.keys())

    return {
        'ticker_map': maps,
        'daily_prices': latest_prices,
        'screener': screener,
        'vcp': vcp,
        'jongga': jongga,
        'candidate_symbols': candidate_symbols,
    }


def _build_candidates(
    artifacts: dict[str, Any],
    *,
    generated_at: str,
    limit: int,
    requested_symbols: set[str],
) -> list[dict[str, Any]]:
    maps = artifacts['ticker_map']
    prices = artifacts['daily_prices']
    screener_by_symbol = _index_screener(artifacts['screener'].get('data'))
    vcp_by_symbol = _index_vcp(artifacts['vcp'].get('data'))
    jongga_by_symbol = _index_jongga(artifacts['jongga'].get('data'))

    symbols = set(artifacts['candidate_symbols'])
    if requested_symbols:
        symbols = {symbol for symbol in symbols if symbol in requested_symbols}
        symbols.update(requested_symbols)

    rows = []
    for symbol in sorted(symbols):
        candidate = _score_symbol(
            symbol,
            maps.get(symbol) or {},
            prices.get(symbol) or {},
            screener_by_symbol.get(symbol),
            vcp_by_symbol.get(symbol),
            jongga_by_symbol.get(symbol),
            artifacts,
            generated_at,
        )
        rows.append(candidate)

    rows.sort(
        key=lambda item: (
            item['ranking_score'],
            item['alpha_score'],
            -item['risk_score'],
            item['symbol'],
        ),
        reverse=True,
    )
    for index, item in enumerate(rows[:limit], start=1):
        item['rank'] = index
    return rows[:limit]


def _score_symbol(
    symbol: str,
    mapped: dict[str, Any],
    price: dict[str, Any],
    screener: dict[str, Any] | None,
    vcp: dict[str, Any] | None,
    jongga: dict[str, Any] | None,
    artifacts: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    evidence = []
    change_rate = _float(price.get('change_rate'))
    trading_value = _float(price.get('trading_value'))
    current_price = _float(price.get('current_price'))
    volume = _float(price.get('volume'))
    if not trading_value and current_price and volume:
        trading_value = current_price * volume

    price_momentum = _clamp(change_rate * 2.0 if change_rate > 0 else 0, 0, 25)
    liquidity = _clamp(trading_value / 20_000_000_000 * 15, 0, 15)
    alpha = price_momentum + liquidity
    evidence.append(_evidence('daily_prices.csv', 'price_momentum', price_momentum, change_rate))
    evidence.append(_evidence('daily_prices.csv', 'liquidity', liquidity, trading_value))

    screener_score = 0.0
    if screener:
        raw = _nested_float(screener, ['score', 'total_enriched'])
        if raw <= 0:
            raw = _nested_float(screener, ['score', 'total'])
        screener_score = _clamp(raw / 100 * 25, 0, 25)
        alpha += screener_score
        evidence.append(_evidence('screener_leading_latest.json', 'screener_leading', screener_score, raw))

    vcp_score = 0.0
    if vcp:
        raw = _nested_float(vcp, ['composite', 'composite_score'])
        entry_ready = _truthy(_nested_get(vcp, ['composite', 'entry_ready']))
        vcp_score = _clamp(raw / 100 * 17, 0, 17) + (3 if entry_ready else 0)
        alpha += vcp_score
        evidence.append(_evidence('vcp_kr_latest.json', 'vcp_quality', vcp_score, raw))

    jongga_score = 0.0
    if jongga:
        raw = _nested_float(jongga, ['score', 'total'])
        jongga_score = _clamp(raw / 15 * 15, 0, 15)
        alpha += jongga_score
        evidence.append(_evidence('jongga_v2_latest.json', 'jongga_setup', jongga_score, raw))

    intraday_range = 0.0
    if current_price:
        intraday_range = max(0.0, (_float(price.get('high')) - _float(price.get('low'))) / current_price * 100)
    risk = 0.0
    risk += _clamp(abs(change_rate) - 12, 0, 18)
    risk += _clamp(intraday_range * 2.0, 0, 22)
    if trading_value <= 0:
        risk += 18
    elif trading_value < 2_000_000_000:
        risk += 10
    risk += _staleness_penalty(artifacts, generated_at)
    risk += _negative_flag_penalty(jongga)
    risk = round(_clamp(risk, 0, 100), 2)

    alpha = round(_clamp(alpha, 0, 100), 2)
    ranking_score = round(alpha - (0.45 * risk), 2)
    action = _action(alpha, risk)
    tags = _strategy_tags(price_momentum, screener_score, vcp_score, jongga_score, risk)

    display_name = (
        mapped.get('display_name')
        or mapped.get('name')
        or price.get('name')
        or (screener or {}).get('name')
        or (vcp or {}).get('name')
        or (jongga or {}).get('stock_name')
        or symbol
    )

    return {
        'rank': None,
        'symbol': symbol,
        'display_name': display_name,
        'market': mapped.get('market') or (jongga or {}).get('market') or (vcp or {}).get('market') or 'KR',
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_score': ranking_score,
        'action': action,
        'horizon': 'swing_5_20d' if action in ('BUY_CANDIDATE', 'WATCH') else 'avoid_or_recheck',
        'strategy_tags': tags,
        'evidence': [item for item in evidence if item['score'] > 0 or item['value'] not in (None, 0)],
        'price': {
            'date': price.get('date'),
            'current_price': current_price,
            'change_rate': change_rate,
            'volume': volume,
            'trading_value': trading_value,
        },
        'generated_at': generated_at,
        'source': 'local_marketflow_artifacts',
        'freshness': _symbol_freshness(artifacts),
    }


def _load_ticker_map() -> dict[str, dict[str, Any]]:
    path = os.path.join(DATA_ROOT, 'ticker_to_yahoo_map.csv')
    rows: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                symbol = _symbol(row.get('ticker'))
                if symbol:
                    rows[symbol] = {
                        'symbol': symbol,
                        'market': row.get('market') or 'KR',
                        'yahoo_ticker': row.get('yahoo_ticker') or '',
                        'display_name': row.get('name') or symbol,
                    }
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _load_latest_prices(symbol_filter: set[str] | None) -> dict[str, dict[str, Any]]:
    path = os.path.join(DATA_ROOT, 'daily_prices.csv')
    rows: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return rows
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = _symbol(row.get('ticker'))
                if not symbol or (symbol_filter and symbol not in symbol_filter):
                    continue
                date = str(row.get('date') or '')
                previous = rows.get(symbol)
                if previous and str(previous.get('date') or '') > date:
                    continue
                current_price = _float(row.get('current_price'))
                volume = _float(row.get('volume'))
                rows[symbol] = {
                    'symbol': symbol,
                    'date': date,
                    'name': row.get('name') or symbol,
                    'current_price': current_price,
                    'change_rate': _float(row.get('change_rate')),
                    'high': _float(row.get('high')),
                    'low': _float(row.get('low')),
                    'open': _float(row.get('open')),
                    'volume': volume,
                    'trading_value': current_price * volume if current_price and volume else 0.0,
                    'update_time': row.get('update_time') or '',
                }
    except (OSError, csv.Error, UnicodeDecodeError):
        return {}
    return rows


def _load_json_artifact(filename: str) -> dict[str, Any]:
    path = os.path.join(DATA_ROOT, filename)
    artifact = {
        'filename': filename,
        'path': path,
        'exists': os.path.isfile(path),
        'data': None,
        'generated_at': None,
        'mtime': None,
    }
    if not artifact['exists']:
        return artifact
    try:
        artifact['mtime'] = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat()
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return artifact
    artifact['data'] = data
    artifact['generated_at'] = (
        data.get('timestamp')
        or data.get('date')
        or _nested_get(data, ['metadata', 'generated_at'])
        or artifact['mtime']
    )
    return artifact


def _symbols_from_screener(data: Any) -> set[str]:
    return {_symbol(item.get('code')) for item in _list_from(data, 'results')} - {''}


def _symbols_from_vcp(data: Any) -> set[str]:
    return {_symbol(item.get('symbol')) for item in _list_from(data, 'signals')} - {''}


def _symbols_from_jongga(data: Any) -> set[str]:
    return {_symbol(item.get('stock_code')) for item in _list_from(data, 'signals')} - {''}


def _index_screener(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('code')): item for item in _list_from(data, 'results') if _symbol(item.get('code'))}


def _index_vcp(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('symbol')): item for item in _list_from(data, 'signals') if _symbol(item.get('symbol'))}


def _index_jongga(data: Any) -> dict[str, dict[str, Any]]:
    return {_symbol(item.get('stock_code')): item for item in _list_from(data, 'signals') if _symbol(item.get('stock_code'))}


def _list_from(data: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [item for item in data[key] if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _source_files(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    files = []
    for filename in [
        'daily_prices.csv',
        'ticker_to_yahoo_map.csv',
        'screener_leading_latest.json',
        'vcp_kr_latest.json',
        'jongga_v2_latest.json',
    ]:
        path = os.path.join(DATA_ROOT, filename)
        exists = os.path.isfile(path)
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).isoformat() if exists else None
        generated_at = None
        for key in ['screener', 'vcp', 'jongga']:
            artifact = artifacts.get(key) or {}
            if artifact.get('filename') == filename:
                generated_at = artifact.get('generated_at')
        files.append({
            'file': f'data/{filename}',
            'exists': exists,
            'generated_at': generated_at,
            'modified_at': mtime,
            'freshness': _freshness_label(generated_at or mtime),
        })
    return files


def _aggregate_freshness(source_files: list[dict[str, Any]]) -> dict[str, Any]:
    existing = [item for item in source_files if item.get('exists')]
    stale_count = sum(1 for item in existing if item.get('freshness') == 'stale')
    return {
        'status': 'stale' if stale_count else 'fresh',
        'available_files': len(existing),
        'missing_files': len(source_files) - len(existing),
        'stale_files': stale_count,
    }


def _symbol_freshness(artifacts: dict[str, Any]) -> dict[str, Any]:
    source_files = _source_files(artifacts)
    return _aggregate_freshness(source_files)


def _staleness_penalty(artifacts: dict[str, Any], generated_at: str) -> float:
    penalty = 0.0
    for key in ['screener', 'vcp', 'jongga']:
        artifact = artifacts.get(key) or {}
        if not artifact.get('exists'):
            penalty += 2.5
        elif _freshness_label(artifact.get('generated_at'), generated_at) == 'stale':
            penalty += 4.0
    return penalty


def _negative_flag_penalty(jongga: dict[str, Any] | None) -> float:
    if not jongga:
        return 0.0
    checklist = jongga.get('checklist') or {}
    penalty = 0.0
    for key in ['negative_news', 'upper_wick_long', 'volume_suspicious']:
        if checklist.get(key) is True:
            penalty += 7.0
    return penalty


def _freshness_label(value: Any, now_iso: str | None = None) -> str:
    if not value:
        return 'unknown'
    now = _parse_dt(now_iso) or datetime.now(timezone.utc)
    dt = _parse_dt(value)
    if dt is None:
        return 'unknown'
    age_days = max(0, (now - dt).total_seconds() / 86400)
    return 'fresh' if age_days <= 7 else 'stale'


def _evidence(source: str, field: str, score: float, value: Any) -> dict[str, Any]:
    return {
        'source': source,
        'field': field,
        'score': round(float(score), 2),
        'value': value,
        'confidence': 0.75 if value not in (None, '', 0) else 0.35,
    }


def _action(alpha: float, risk: float) -> str:
    if alpha >= 70 and risk <= 45:
        return 'BUY_CANDIDATE'
    if alpha >= 50 and risk <= 65:
        return 'WATCH'
    return 'REJECT'


def _strategy_tags(
    price_momentum: float,
    screener_score: float,
    vcp_score: float,
    jongga_score: float,
    risk: float,
) -> list[str]:
    tags = []
    if price_momentum >= 12:
        tags.append('momentum')
    if screener_score >= 12:
        tags.append('leading_screener')
    if vcp_score >= 10:
        tags.append('vcp_entry')
    if jongga_score >= 8:
        tags.append('jongga_setup')
    if risk >= 45:
        tags.append('risk_penalty')
    return tags or ['artifact_candidate']


def _clean_limit(value: Any, *, default: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(limit, MAX_CANDIDATES))


def _clean_symbols(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return set()
    return {_symbol(item) for item in value if _symbol(item)}


def _scanner_run_records() -> list[dict[str, Any]]:
    if not os.path.isdir(SCANNER_RUNS_ROOT):
        return []
    records: list[dict[str, Any]] = []
    for name in os.listdir(SCANNER_RUNS_ROOT):
        try:
            safe_id = _safe_run_id(name)
        except ValueError:
            continue
        path = os.path.join(SCANNER_RUNS_ROOT, safe_id, 'run.json')
        if not os.path.isfile(path):
            continue
        try:
            run = _read_json(path)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(run, dict):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
        sort_dt = _parse_dt(run.get('generated_at') or run.get('created_at')) or mtime
        records.append({'run': run, 'path': path, 'mtime': mtime, 'sort_dt': sort_dt})
    records.sort(key=lambda item: (item['sort_dt'], item['mtime']), reverse=True)
    return records


def _scanner_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': run.get('id'),
        'status': run.get('status'),
        'mode': run.get('mode'),
        'source': run.get('source'),
        'generated_at': run.get('generated_at'),
        'created_at': run.get('created_at'),
        'limit': run.get('limit'),
        'candidate_count': run.get('candidate_count'),
        'freshness': run.get('freshness'),
        'links': run.get('links'),
    }


def _scanner_schedule_times() -> list[dt_time]:
    out: list[dt_time] = []
    raw = os.getenv('ALPHA_SCANNER_TIMES', DEFAULT_SCHEDULE_TIMES)
    for item in str(raw or '').split(','):
        text = item.strip()
        if not re.fullmatch(r'\d{1,2}:\d{2}', text):
            continue
        hour_text, minute_text = text.split(':', 1)
        hour = int(hour_text)
        minute = int(minute_text)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            out.append(dt_time(hour=hour, minute=minute))
    return sorted(set(out)) or [dt_time(9, 20), dt_time(11, 20), dt_time(14, 20), dt_time(15, 40), dt_time(16, 10)]


def _next_scheduled_times(now: datetime, scheduled_times: list[dt_time], *, count: int = 5) -> list[str]:
    current = now.astimezone(KST)
    out: list[str] = []
    day = current.date()
    while len(out) < count:
        if day.weekday() < 5:
            for scheduled in scheduled_times:
                candidate = datetime.combine(day, scheduled, tzinfo=KST)
                if candidate > current:
                    out.append(candidate.isoformat())
                    if len(out) >= count:
                        break
        day += timedelta(days=1)
    return out


def _scheduler_last_run_at() -> str | None:
    path = os.path.join(DATA_ROOT, 'scheduler_last_run.json')
    if not os.path.isfile(path):
        return None
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    values = []
    for key, value in data.items():
        if not str(key).startswith('alpha_scanner_') and key != 'alpha_scanner':
            continue
        parsed = _parse_dt(value)
        if parsed is not None:
            values.append(parsed)
    if not values:
        return None
    return max(values).astimezone(KST).isoformat()


def _alert_state_path() -> str:
    return os.path.join(DATA_ROOT, 'admin_mirofish', 'alpha_scanner_alert_state.json')


def _read_alert_state(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {'version': 1, 'sent_events': {}}
    try:
        data = _read_json(path)
    except (OSError, json.JSONDecodeError, ValueError):
        return {'version': 1, 'sent_events': {}}
    if not isinstance(data, dict):
        return {'version': 1, 'sent_events': {}}
    sent_events = data.get('sent_events')
    if not isinstance(sent_events, dict):
        sent_events = {}
    data['sent_events'] = sent_events
    data.setdefault('version', 1)
    return data


def _new_candidate_events(
    run: dict[str, Any],
    state: dict[str, Any],
    *,
    min_alpha: float,
    max_risk: float,
    actions: tuple[str, ...],
    max_events: int,
) -> list[dict[str, Any]]:
    seen = state.get('sent_events') or {}
    action_set = {str(action) for action in actions}
    events = []
    for candidate in run.get('candidates') or []:
        if candidate.get('action') not in action_set:
            continue
        if _float(candidate.get('alpha_score')) < min_alpha:
            continue
        if _float(candidate.get('risk_score')) > max_risk:
            continue
        event_key = _candidate_event_key(candidate)
        if event_key in seen:
            continue
        events.append({
            'event_key': event_key,
            'run_id': run.get('id'),
            'generated_at': run.get('generated_at'),
            'candidate': candidate,
        })
        if len(events) >= max(1, int(max_events)):
            break
    return events


def _update_alert_state(
    state: dict[str, Any],
    run: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    sent_events = dict(state.get('sent_events') or {})
    checked_at = run.get('generated_at')
    for event in events:
        candidate = event.get('candidate') or {}
        sent_events[event['event_key']] = {
            'sent_at': checked_at,
            'run_id': run.get('id'),
            'rank': candidate.get('rank'),
            'symbol': candidate.get('symbol'),
            'display_name': candidate.get('display_name'),
            'market': candidate.get('market'),
            'action': candidate.get('action'),
            'alpha_score': candidate.get('alpha_score'),
            'risk_score': candidate.get('risk_score'),
        }
    return {
        'version': 1,
        'last_checked_at': checked_at,
        'last_run_id': run.get('id'),
        'last_candidate_count': run.get('candidate_count'),
        'sent_events': sent_events,
    }


def _candidate_event_key(candidate: dict[str, Any]) -> str:
    price_date = (candidate.get('price') or {}).get('date') or str(candidate.get('generated_at') or '')[:10]
    return f"{candidate.get('symbol')}:{candidate.get('action')}:{price_date}"


def _action_label(value: Any) -> str:
    return {
        'BUY_CANDIDATE': '매수 후보',
        'WATCH': '관찰',
        'REJECT': '제외',
    }.get(str(value or ''), str(value or ''))


def _horizon_label(value: Any) -> str:
    return {
        'swing_5_20d': '스윙 5-20일',
        'avoid_or_recheck': '회피 또는 재점검',
    }.get(str(value or ''), str(value or ''))


def _tag_label(value: Any) -> str:
    return {
        'momentum': '모멘텀',
        'leading_screener': '선도 스크리너',
        'vcp_entry': 'VCP 진입',
        'jongga_setup': '종가 셋업',
        'risk_penalty': '리스크 패널티',
        'artifact_candidate': '파일 기반 후보',
    }.get(str(value or ''), str(value or ''))


def _evidence_field_label(value: Any) -> str:
    return {
        'price_momentum': '가격 모멘텀',
        'liquidity': '유동성',
        'screener_leading': '선도 스크리너',
        'vcp_quality': 'VCP 품질',
        'jongga_setup': '종가 셋업',
    }.get(str(value or ''), str(value or ''))


def _run_id(generated_at: str, symbols: set[str], limit: int) -> str:
    seed = json.dumps(
        {'generated_at': generated_at, 'symbols': sorted(symbols), 'limit': limit},
        sort_keys=True,
    )
    digest = hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]
    stamp = re.sub(r'[^0-9]', '', generated_at)[:14]
    return f'mfas_{stamp}_{digest}'


def _run_path(run_id: str) -> str:
    safe_id = _safe_run_id(run_id)
    return os.path.join(SCANNER_RUNS_ROOT, safe_id, 'run.json')


def _safe_run_id(run_id: str) -> str:
    safe_id = str(run_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{8,80}', safe_id):
        raise ValueError('invalid scanner run_id')
    return safe_id


def _read_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def _symbol(value: Any) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.zfill(6)[-6:] if digits else ''


def _float(value: Any) -> float:
    try:
        if value in (None, ''):
            return 0.0
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return 0.0


def _nested_get(data: dict[str, Any], path: list[str]) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _nested_float(data: dict[str, Any], path: list[str]) -> float:
    return _float(_nested_get(data, path))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y'}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _escape(value: Any) -> str:
    return html.escape(str(value or ''), quote=False)


def _format_number(value: Any) -> str:
    number = _float(value)
    if number == 0:
        return '0'
    if number.is_integer():
        return f'{int(number):,}'
    return f'{number:,.2f}'


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        text = f'{text}T00:00:00+00:00'
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
