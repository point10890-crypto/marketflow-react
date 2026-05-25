"""Dual Kalman-style shadow gate for Alpha Scanner candidates.

This module is intentionally conservative.  It does not try to predict stock
prices directly.  It estimates whether an alpha-scanner candidate's recent
price/volume signal is stable enough to pass into the heavier GraphRAG Top 3
pipeline.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from typing import Any

import app.services.mirofish.alpha_scanner as alpha_scanner
from app.utils.atomic_json import write_json_atomic


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
KALMAN_RUNS_ROOT = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'kalman_runs')
SCHEMA_VERSION = 'mirofish.dual_kalman_gate.v1'
DEFAULT_PROFILE = 'linear_dkf_shadow_v1'
DEFAULT_LIMIT = 20
DEFAULT_MIN_CONFIDENCE = 0.55
MAX_LIMIT = 100


def get_dual_kalman_status() -> dict[str, Any]:
    """Return a lightweight operator status for the shadow gate."""
    latest = read_latest_dual_kalman_run()
    price_path = _price_path()
    return {
        'service': 'mirofish-dual-kalman',
        'ready': True,
        'mode': 'scanner_signal_shadow_gate',
        'schema_version': SCHEMA_VERSION,
        'profile': DEFAULT_PROFILE,
        'storage': os.path.relpath(KALMAN_RUNS_ROOT, REPO_ROOT).replace('\\', '/'),
        'latest_run_id': latest.get('id') if latest else None,
        'source_freshness': {
            'daily_prices': _file_freshness(price_path),
            'scanner_run': ((alpha_scanner.read_latest_scanner_run() or {}).get('freshness') or {}).get('status')
                or 'unknown',
        },
        'model_health': {
            'lookahead_safe': True,
            'live_ranking_mutation': False,
            'gate_values': ['pass', 'watch', 'block'],
        },
        'checked_at': _now_iso(),
    }


def create_dual_kalman_run(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a persisted DKF shadow analysis for scanner candidates."""
    payload = payload or {}
    scanner_run = _scanner_run_from_payload(payload)
    if not isinstance(scanner_run, dict):
        return {
            'ok': False,
            'status': 'scanner_run_not_found',
            'schema_version': SCHEMA_VERSION,
            'lookahead_safe': True,
            'generated_at': _now_iso(),
        }

    limit = _int(payload.get('limit'), DEFAULT_LIMIT, 1, MAX_LIMIT)
    symbols = _clean_symbols(payload.get('symbols'))
    candidates = [
        candidate for candidate in (scanner_run.get('candidates') or [])
        if isinstance(candidate, dict)
    ]
    if symbols:
        candidates = [
            candidate for candidate in candidates
            if _symbol(candidate) in symbols
        ]
    candidates = candidates[:limit]
    return run_dual_kalman_signal_gate(
        scanner_run,
        candidates,
        profile=str(payload.get('profile') or DEFAULT_PROFILE),
        min_confidence=_float(payload.get('min_confidence'), DEFAULT_MIN_CONFIDENCE),
        block_high_innovation=_bool(payload.get('block_high_innovation'), True),
        persist=True,
    )


def run_dual_kalman_signal_gate(
    scanner_run: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    profile: str = DEFAULT_PROFILE,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    block_high_innovation: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """Analyze candidates and optionally persist the shadow gate artifact."""
    created_at = _now_iso()
    safe_profile = str(profile or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
    scanner_run_id = str(scanner_run.get('id') or 'latest')
    run_id = _run_id(created_at, scanner_run_id, candidates, safe_profile)
    symbols = [_symbol(candidate) for candidate in candidates if _symbol(candidate)]
    histories = _load_price_history(symbols)
    signals = [
        _candidate_signal(
            candidate,
            histories.get(_symbol(candidate), []),
            profile=safe_profile,
            min_confidence=min_confidence,
            block_high_innovation=block_high_innovation,
        )
        for candidate in candidates
    ]
    summary = _signal_summary(signals)
    run = {
        'id': run_id,
        'ok': True,
        'status': 'completed',
        'schema_version': SCHEMA_VERSION,
        'service': 'mirofish-dual-kalman',
        'mode': 'scanner_signal_shadow_gate',
        'profile': safe_profile,
        'scanner_run_id': scanner_run.get('id'),
        'generated_at': created_at,
        'created_at': created_at,
        'candidate_count': len(candidates),
        'signal_count': len(signals),
        'summary': summary,
        'lookahead_safe': True,
        'mutates_scanner_scores': False,
        'source_files': [
            'data/daily_prices.csv',
            f"scanner_run:{scanner_run.get('id') or 'inline'}",
        ],
        'signals': signals,
        'links': {
            'self': f'/api/admin/mirofish/kalman/runs/{run_id}',
            'signals': f'/api/admin/mirofish/kalman/runs/{run_id}/signals',
        },
    }
    if persist:
        os.makedirs(_run_dir(run_id), exist_ok=True)
        write_json_atomic(_run_path(run_id), run, sort_keys=False)
        write_json_atomic(_signals_path(run_id), {
            'run_id': run_id,
            'schema_version': SCHEMA_VERSION,
            'generated_at': created_at,
            'lookahead_safe': True,
            'signals': signals,
        }, sort_keys=False)
    return run


def read_dual_kalman_run(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = _run_path(safe_id)
    if not os.path.isfile(path):
        return None
    return _read_json(path)


def read_latest_dual_kalman_run() -> dict[str, Any] | None:
    latest_id = _latest_run_id()
    return read_dual_kalman_run(latest_id) if latest_id else None


def read_dual_kalman_signals(run_id: str) -> dict[str, Any] | None:
    safe_id = _safe_run_id(run_id)
    path = _signals_path(safe_id)
    if not os.path.isfile(path):
        run = read_dual_kalman_run(safe_id)
        if not run:
            return None
        return {
            'run_id': safe_id,
            'schema_version': SCHEMA_VERSION,
            'generated_at': run.get('generated_at'),
            'lookahead_safe': True,
            'signals': run.get('signals') or [],
        }
    return _read_json(path)


def apply_dual_kalman_gate_to_candidates(
    candidates: list[dict[str, Any]],
    kalman_run: dict[str, Any],
    *,
    drop_blocked: bool = True,
) -> list[dict[str, Any]]:
    """Attach gate metadata to candidate copies for workflow scoring."""
    by_symbol = {
        str(signal.get('symbol') or '').zfill(6): signal
        for signal in (kalman_run.get('signals') or [])
        if isinstance(signal, dict) and signal.get('symbol')
    }
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        item = copy.deepcopy(candidate)
        symbol = _symbol(item)
        signal = by_symbol.get(symbol)
        if signal:
            profile = item.get('analysis_profile')
            if not isinstance(profile, dict):
                profile = {}
                item['analysis_profile'] = profile
            profile['dual_kalman_gate'] = _candidate_gate_snapshot(signal)
            item['kalman_gate'] = signal.get('gate')
            item['kalman_score_delta'] = signal.get('score_delta')
            item['shadow_ranking_score'] = round(
                _float(item.get('ranking_score'), 0.0) + _float(signal.get('score_delta'), 0.0),
                2,
            )
            tags = list(item.get('strategy_tags') or [])
            gate = str(signal.get('gate') or 'watch')
            marker = f'kalman_{gate}'
            if marker not in tags:
                tags.append(marker)
            item['strategy_tags'] = tags
            if drop_blocked and gate == 'block':
                continue
        enriched.append(item)
    return enriched


def _candidate_signal(
    candidate: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    profile: str,
    min_confidence: float,
    block_high_innovation: bool,
) -> dict[str, Any]:
    symbol = _symbol(candidate)
    name = candidate.get('display_name') or candidate.get('name') or symbol
    scanner_alpha = _float(candidate.get('alpha_score'), 0.0)
    scanner_risk = _float(candidate.get('risk_score'), 0.0)
    scanner_rank = candidate.get('rank')
    base = {
        'symbol': symbol,
        'name': name,
        'display_name': name,
        'market': candidate.get('market'),
        'profile': profile,
        'scanner': {
            'rank': scanner_rank,
            'alpha_score': scanner_alpha,
            'risk_score': scanner_risk,
            'ranking_score': candidate.get('ranking_score'),
            'action': candidate.get('action'),
        },
        'lookahead_safe': True,
    }
    if len(history) < 8:
        return {
            **base,
            'status': 'data_insufficient',
            'gate': 'watch',
            'score_delta': -3.0,
            'shadow_alpha_score': max(0.0, round(scanner_alpha - 3.0, 2)),
            'kalman': {
                'history_count': len(history),
                'signal_confidence': 0.25,
                'volatility_state': 'unknown',
            },
            'reason': '가격 히스토리가 부족해 DKF 게이트는 watch로 제한',
        }

    metrics = _history_metrics(history)
    confidence = _confidence(metrics)
    gate = _gate(metrics, confidence, min_confidence, block_high_innovation)
    score_delta = _score_delta(metrics, gate)
    shadow_alpha = max(0.0, min(100.0, scanner_alpha + score_delta))
    return {
        **base,
        'status': 'ready',
        'gate': gate,
        'score_delta': score_delta,
        'shadow_alpha_score': round(shadow_alpha, 2),
        'kalman': {
            **metrics,
            'signal_confidence': confidence,
            'min_confidence': min_confidence,
        },
        'reason': _reason(metrics, gate),
    }


def _history_metrics(history: list[dict[str, Any]]) -> dict[str, Any]:
    closes = [_float(row.get('close'), 0.0) for row in history if _float(row.get('close'), 0.0) > 0]
    volumes = [_float(row.get('volume'), 0.0) for row in history]
    returns = [
        ((closes[index] / closes[index - 1]) - 1.0) * 100.0
        for index in range(1, len(closes))
        if closes[index - 1] > 0
    ]
    recent_returns = returns[-20:] or returns
    trend_5d = _mean(returns[-5:])
    trend_20d = _mean(recent_returns)
    volatility_20d = _std(recent_returns)
    latest_return = returns[-1] if returns else 0.0
    latest_close = closes[-1]
    recent_closes = closes[-20:] if len(closes) >= 20 else closes
    fair_mean = _mean(recent_closes)
    fair_std = _std(recent_closes)
    fair_value_gap_z = (latest_close - fair_mean) / max(fair_std, latest_close * 0.01, 1e-6)
    innovation_z = abs(latest_return - trend_5d) / max(volatility_20d, 0.75)
    prev_volumes = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
    volume_ratio = volumes[-1] / max(_mean(prev_volumes), 1.0) if volumes else 0.0
    latent_return_z = trend_5d / max(volatility_20d, 0.75)
    if volatility_20d >= 8:
        volatility_state = 'high'
    elif volatility_20d >= 4:
        volatility_state = 'elevated'
    else:
        volatility_state = 'normal'
    return {
        'history_count': len(closes),
        'latest_date': history[-1].get('date'),
        'latest_close': round(latest_close, 4),
        'latest_return_pct': round(latest_return, 4),
        'trend_5d_pct': round(trend_5d, 4),
        'trend_20d_pct': round(trend_20d, 4),
        'volatility_20d_pct': round(volatility_20d, 4),
        'volatility_state': volatility_state,
        'latent_return_z': round(latent_return_z, 4),
        'fair_value_gap_z': round(fair_value_gap_z, 4),
        'innovation_z': round(innovation_z, 4),
        'volume_ratio': round(volume_ratio, 4),
    }


def _confidence(metrics: dict[str, Any]) -> float:
    confidence = 0.45
    trend_5d = _float(metrics.get('trend_5d_pct'), 0.0)
    trend_20d = _float(metrics.get('trend_20d_pct'), 0.0)
    innovation_z = _float(metrics.get('innovation_z'), 0.0)
    gap_z = abs(_float(metrics.get('fair_value_gap_z'), 0.0))
    volume_ratio = _float(metrics.get('volume_ratio'), 0.0)
    volatility_state = str(metrics.get('volatility_state') or 'unknown')

    if trend_5d > 0:
        confidence += 0.08
    if trend_20d > 0:
        confidence += 0.08
    if 1.05 <= volume_ratio <= 4.5:
        confidence += 0.05
    if innovation_z < 1.5:
        confidence += 0.12
    elif innovation_z < 2.5:
        confidence += 0.04
    else:
        confidence -= 0.18
    if gap_z < 2.2:
        confidence += 0.08
    else:
        confidence -= 0.15
    if volatility_state == 'high':
        confidence -= 0.12
    elif volatility_state == 'elevated':
        confidence -= 0.04
    return round(max(0.05, min(0.95, confidence)), 4)


def _gate(
    metrics: dict[str, Any],
    confidence: float,
    min_confidence: float,
    block_high_innovation: bool,
) -> str:
    latest_return = _float(metrics.get('latest_return_pct'), 0.0)
    innovation_z = _float(metrics.get('innovation_z'), 0.0)
    gap_z = abs(_float(metrics.get('fair_value_gap_z'), 0.0))
    trend_5d = _float(metrics.get('trend_5d_pct'), 0.0)
    volatility_state = str(metrics.get('volatility_state') or 'unknown')
    if block_high_innovation and (
        (latest_return >= 9.0 and innovation_z >= 2.6)
        or gap_z >= 3.5
        or (volatility_state == 'high' and latest_return >= 10.0)
    ):
        return 'block'
    if confidence >= min_confidence and trend_5d > 0 and innovation_z < 2.6:
        return 'pass'
    return 'watch'


def _score_delta(metrics: dict[str, Any], gate: str) -> float:
    latent_z = _float(metrics.get('latent_return_z'), 0.0)
    trend_20d = _float(metrics.get('trend_20d_pct'), 0.0)
    innovation_z = _float(metrics.get('innovation_z'), 0.0)
    gap_z = abs(_float(metrics.get('fair_value_gap_z'), 0.0))
    volume_ratio = _float(metrics.get('volume_ratio'), 0.0)
    volatility_state = str(metrics.get('volatility_state') or 'unknown')
    delta = latent_z * 2.2
    delta += 0.8 if trend_20d > 0 else -0.8
    delta += min(max(volume_ratio - 1.0, 0.0), 2.5) * 0.5
    delta -= max(0.0, innovation_z - 1.4) * 2.0
    delta -= max(0.0, gap_z - 2.0) * 1.8
    if volatility_state == 'high':
        delta -= 2.5
    elif volatility_state == 'elevated':
        delta -= 0.8
    if gate == 'block':
        delta = min(delta, -6.0)
    elif gate == 'watch':
        delta = max(-4.0, min(3.0, delta))
    return round(max(-8.0, min(8.0, delta)), 2)


def _reason(metrics: dict[str, Any], gate: str) -> str:
    if gate == 'block':
        return 'innovation spike 또는 공정가치 괴리가 커서 Top3 자동분석 전 감점/제외'
    if gate == 'pass':
        return '잠재 추세와 변동성 상태가 안정적이라 Top3 후보 검증 통과'
    return '일부 신호는 유효하지만 확신도 제한으로 watch 처리'


def _signal_summary(signals: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {'pass': 0, 'watch': 0, 'block': 0}
    for signal in signals:
        gate = str(signal.get('gate') or 'watch')
        if gate in counts:
            counts[gate] += 1
    return {
        'gate_counts': counts,
        'pass_count': counts['pass'],
        'watch_count': counts['watch'],
        'block_count': counts['block'],
        'avg_score_delta': round(_mean([_float(signal.get('score_delta'), 0.0) for signal in signals]), 4),
    }


def _candidate_gate_snapshot(signal: dict[str, Any]) -> dict[str, Any]:
    kalman = signal.get('kalman') if isinstance(signal.get('kalman'), dict) else {}
    return {
        'schema_version': SCHEMA_VERSION,
        'gate': signal.get('gate'),
        'score_delta': signal.get('score_delta'),
        'shadow_alpha_score': signal.get('shadow_alpha_score'),
        'signal_confidence': kalman.get('signal_confidence'),
        'latent_return_z': kalman.get('latent_return_z'),
        'innovation_z': kalman.get('innovation_z'),
        'fair_value_gap_z': kalman.get('fair_value_gap_z'),
        'volatility_state': kalman.get('volatility_state'),
        'reason': signal.get('reason'),
        'lookahead_safe': True,
    }


def _scanner_run_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    inline = payload.get('scanner_run')
    if isinstance(inline, dict):
        return inline
    scanner_run_id = str(payload.get('scanner_run_id') or 'latest').strip()
    if not scanner_run_id or scanner_run_id == 'latest':
        return alpha_scanner.read_latest_scanner_run()
    return alpha_scanner.read_scanner_run(scanner_run_id)


def _load_price_history(symbols: list[str]) -> dict[str, list[dict[str, Any]]]:
    wanted = {str(symbol).zfill(6) for symbol in symbols if symbol}
    if not wanted:
        return {}
    path = _price_path()
    history: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in wanted}
    if not os.path.isfile(path):
        return history
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get('ticker') or row.get('symbol') or '').zfill(6)
                if symbol not in wanted:
                    continue
                close = _float(row.get('current_price') or row.get('close'), 0.0)
                if close <= 0:
                    continue
                history.setdefault(symbol, []).append({
                    'date': str(row.get('date') or '').strip(),
                    'close': close,
                    'open': _float(row.get('open'), close),
                    'high': _float(row.get('high'), close),
                    'low': _float(row.get('low'), close),
                    'volume': _float(row.get('volume'), 0.0),
                })
    except (OSError, csv.Error):
        return history
    for rows in history.values():
        rows.sort(key=lambda item: str(item.get('date') or ''))
        del rows[:-250]
    return history


def _price_path() -> str:
    return os.path.join(alpha_scanner.DATA_ROOT, 'daily_prices.csv')


def _file_freshness(path: str) -> str:
    if not os.path.isfile(path):
        return 'missing'
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    except OSError:
        return 'unknown'
    age_days = (datetime.now(timezone.utc) - mtime).total_seconds() / 86400
    if age_days <= 5:
        return 'fresh'
    if age_days <= 30:
        return 'stale'
    return 'old'


def _run_id(created_at: str, scanner_run_id: str, candidates: list[dict[str, Any]], profile: str) -> str:
    basis = '|'.join([
        created_at,
        scanner_run_id,
        profile,
        ','.join(_symbol(candidate) for candidate in candidates),
    ])
    digest = hashlib.sha1(basis.encode('utf-8')).hexdigest()[:10]
    stamp = re.sub(r'[^0-9]', '', created_at)[:14]
    return f'dkf_{stamp}_{digest}'


def _latest_run_id() -> str | None:
    if not os.path.isdir(KALMAN_RUNS_ROOT):
        return None
    items: list[tuple[float, str]] = []
    try:
        entries = os.scandir(KALMAN_RUNS_ROOT)
    except OSError:
        return None
    with entries:
        for entry in entries:
            if not entry.is_dir():
                continue
            try:
                run_id = _safe_run_id(entry.name)
                path = _run_path(run_id)
                mtime = os.path.getmtime(path)
            except (ValueError, OSError):
                continue
            items.append((mtime, run_id))
    if not items:
        return None
    items.sort(reverse=True)
    return items[0][1]


def _run_dir(run_id: str) -> str:
    return os.path.join(KALMAN_RUNS_ROOT, _safe_run_id(run_id))


def _run_path(run_id: str) -> str:
    return os.path.join(_run_dir(run_id), 'run.json')


def _signals_path(run_id: str) -> str:
    return os.path.join(_run_dir(run_id), 'signals.json')


def _safe_run_id(run_id: str) -> str:
    value = str(run_id or '').strip()
    if not value or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
        raise ValueError('invalid dual kalman run_id')
    if value in {'.', '..'} or '/' in value or '\\' in value:
        raise ValueError('invalid dual kalman run_id')
    return value


def _read_json(path: str) -> dict[str, Any]:
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _clean_symbols(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw_items = re.split(r'[\s,]+', value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    symbols = set()
    for item in raw_items:
        text = str(item or '').strip()
        if not text:
            continue
        digits = re.sub(r'\D', '', text)
        if digits:
            symbols.add(digits.zfill(6)[-6:])
    return symbols


def _symbol(candidate: dict[str, Any]) -> str:
    text = str(candidate.get('symbol') or candidate.get('ticker') or '').strip()
    digits = re.sub(r'\D', '', text)
    return digits.zfill(6)[-6:] if digits else text


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def _mean(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if not clean:
        return 0.0
    return sum(clean) / len(clean)


def _std(values: list[float]) -> float:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return 0.0
    mean = _mean(clean)
    variance = sum((value - mean) ** 2 for value in clean) / (len(clean) - 1)
    return math.sqrt(max(0.0, variance))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
