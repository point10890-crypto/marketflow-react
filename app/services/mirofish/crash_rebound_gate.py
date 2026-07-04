"""Crash/rebound regime gate for MiroFish alpha detection.

The gate is a deterministic market-context filter.  It does not create buy
signals.  It summarizes whether a broad-market selloff is still risky or
whether rebound conditions are improving enough to relax scanner confidence
caps.  Every signal carries source/freshness metadata so downstream scoring can
decide how much to trust it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 'mirofish.crash_rebound_gate.v1'

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = REPO_ROOT / 'data'
ARTIFACT_ROOT = DATA_ROOT / 'admin_mirofish' / 'market' / 'crash_rebound'
LATEST_PATH = ARTIFACT_ROOT / 'latest.json'
HISTORY_ROOT = ARTIFACT_ROOT / 'history'
MARKET_GATE_CACHE = DATA_ROOT / 'market_gate_cache.json'
US_MARKET_DATA = REPO_ROOT / 'us_market' / 'output' / 'market_data.json'


SIGNAL_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        'id': 'vix_drop_10pct',
        'label': 'VIX 10% 이상 하락',
        'weight': 8,
        'source_grade': 'A',
        'required_indicator': 'vix',
        'reason': '공포 변동성 완화 여부',
    },
    {
        'id': 'fear_greed_extreme_fear',
        'label': 'Fear & Greed 극단 공포',
        'weight': 6,
        'source_grade': 'B',
        'required_indicator': 'fear_greed',
        'reason': '심리 과매도 구간',
    },
    {
        'id': 'put_call_above_1',
        'label': 'Put/Call 1.0 이상',
        'weight': 5,
        'source_grade': 'A',
        'required_indicator': 'put_call',
        'reason': '옵션 방어 포지션 과열',
    },
    {
        'id': 'ewy_rebound_1pct',
        'label': 'EWY 1% 이상 반등',
        'weight': 7,
        'source_grade': 'A',
        'required_indicator': 'ewy',
        'reason': '해외 한국물 선반영 반등',
    },
    {
        'id': 'sp500_positive',
        'label': 'S&P500 양수 전환',
        'weight': 5,
        'source_grade': 'A',
        'required_indicator': 'sp500',
        'reason': '글로벌 위험선호 회복',
    },
    {
        'id': 'insider_cluster_buy',
        'label': '내부자/자사주 매입 군집',
        'weight': 4,
        'source_grade': 'S',
        'required_indicator': 'insider_cluster_buy',
        'reason': '기업 내부 신뢰 확인',
    },
    {
        'id': 'foreign_flow_turn',
        'label': '외국인 수급 순매수 전환',
        'weight': 10,
        'source_grade': 'S',
        'required_indicator': 'foreign_flow',
        'reason': '한국 시장 반등 지속성 핵심',
    },
    {
        'id': 'short_balance_down',
        'label': '공매도 잔고 감소',
        'weight': 6,
        'source_grade': 'S',
        'required_indicator': 'short_balance',
        'reason': '숏커버 또는 압력 완화',
    },
    {
        'id': 'margin_loan_flush',
        'label': '신용잔고 급감 후 안정',
        'weight': 5,
        'source_grade': 'S',
        'required_indicator': 'margin_loan',
        'reason': '레버리지 청산 압력 완화',
    },
    {
        'id': 'hy_oas_narrowing',
        'label': 'HY OAS 축소',
        'weight': 6,
        'source_grade': 'S',
        'required_indicator': 'hy_oas',
        'reason': '크레딧 위험 프리미엄 완화',
    },
    {
        'id': 'usdkrw_down',
        'label': 'USD/KRW 하락',
        'weight': 8,
        'source_grade': 'S',
        'required_indicator': 'usdkrw',
        'reason': '외국인 수급에 유리한 환율 전송',
    },
    {
        'id': 'kospi_rsi_rebound',
        'label': 'KOSPI 과매도/회복 RSI',
        'weight': 7,
        'source_grade': 'A',
        'required_indicator': 'kospi',
        'reason': '기술적 반등 타이밍',
    },
    {
        'id': 'policy_stabilization',
        'label': '정책 안정화 신호',
        'weight': 5,
        'source_grade': 'S/B',
        'required_indicator': 'policy_stabilization',
        'reason': '유동성/규제/정책 지원 확인',
    },
    {
        'id': 'news_tone_recovery',
        'label': '뉴스 톤 회복',
        'weight': 3,
        'source_grade': 'B/C',
        'required_indicator': 'news_tone',
        'reason': '보조 심리 신호, 단독 매수 근거 금지',
    },
)


def get_crash_rebound_schema() -> dict[str, Any]:
    """Return the deterministic contract for the crash/rebound gate."""
    return {
        'schema_version': SCHEMA_VERSION,
        'objective': 'broad-market crash/rebound context for safer Top3 alpha detection',
        'buy_signal': False,
        'signals': [dict(item) for item in SIGNAL_DEFINITIONS],
        'rules': {
            'llm_may_explain_not_invent': True,
            'news_social_secondary_only': True,
            'missing_data_does_not_create_signal': True,
            'freshness_required_for_strong_status': True,
        },
    }


def read_latest_crash_rebound_gate() -> dict[str, Any]:
    """Read the latest gate artifact or build a cheap cache-based snapshot."""
    latest = _read_json_safe(LATEST_PATH)
    if latest:
        return latest
    return evaluate_crash_rebound_gate(collect_crash_rebound_inputs(live_fetch=False), persist=False)


def run_crash_rebound_gate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect, evaluate, persist, and return the crash/rebound gate snapshot."""
    payload = payload or {}
    live_fetch = _as_bool(payload.get('live'), default=_live_fetch_default())
    inputs = collect_crash_rebound_inputs(payload, live_fetch=live_fetch)
    return evaluate_crash_rebound_gate(inputs, persist=True)


def collect_crash_rebound_inputs(
    payload: dict[str, Any] | None = None,
    *,
    live_fetch: bool | None = None,
) -> dict[str, Any]:
    """Collect cache/live indicators into a normalized evidence packet."""
    payload = payload or {}
    now = _now_utc()
    live = _live_fetch_default() if live_fetch is None else bool(live_fetch)
    indicators: dict[str, dict[str, Any]] = {}

    supplied = payload.get('indicators') if isinstance(payload.get('indicators'), dict) else {}
    for key, value in supplied.items():
        indicators[str(key)] = _normalize_indicator(str(key), value, source='payload', now=now)

    _merge_cache_indicators(indicators, now=now)
    if live:
        _merge_live_market_indicators(indicators, now=now)

    return {
        'schema_version': f'{SCHEMA_VERSION}.inputs',
        'generated_at': now.isoformat(),
        'live_fetch': live,
        'indicators': indicators,
    }


def evaluate_crash_rebound_gate(
    inputs: dict[str, Any] | None = None,
    *,
    persist: bool = False,
) -> dict[str, Any]:
    """Evaluate the crash/rebound signals and optionally persist the artifact."""
    now = _now_utc()
    inputs = inputs or collect_crash_rebound_inputs(live_fetch=False)
    indicators = inputs.get('indicators') if isinstance(inputs.get('indicators'), dict) else {}

    signal_rows = [_evaluate_signal(defn, indicators) for defn in SIGNAL_DEFINITIONS]
    available_weight = sum(float(row['weight']) for row in signal_rows if row['status'] != 'unknown')
    positive_weight = sum(float(row['weight']) for row in signal_rows if row['state'] == 'pass')
    total_weight = sum(float(row['weight']) for row in signal_rows)
    yes_count = sum(1 for row in signal_rows if row['state'] == 'pass')
    fail_count = sum(1 for row in signal_rows if row['state'] == 'fail')
    unknown_count = sum(1 for row in signal_rows if row['state'] == 'unknown')
    stale_count = sum(1 for row in signal_rows if row.get('freshness') == 'stale')

    score = round((positive_weight / total_weight) * 100, 1) if total_weight else 0.0
    data_coverage_pct = round((available_weight / total_weight) * 100, 1) if total_weight else 0.0
    regime = _classify_regime(score, yes_count, fail_count, unknown_count, indicators)
    policy = _scanner_policy(regime, score, data_coverage_pct, stale_count)
    summary = _summary_text(regime, score, yes_count, fail_count, unknown_count, data_coverage_pct)

    artifact = {
        'schema_version': SCHEMA_VERSION,
        'generated_at': now.isoformat(),
        'status': regime['status'],
        'label': regime['label'],
        'score': score,
        'confidence': regime['confidence'],
        'data_coverage_pct': data_coverage_pct,
        'summary': summary,
        'signals': signal_rows,
        'counts': {
            'pass': yes_count,
            'fail': fail_count,
            'unknown': unknown_count,
            'stale': stale_count,
            'total': len(signal_rows),
        },
        'scanner_policy': policy,
        'source_packet': {
            'generated_at': inputs.get('generated_at'),
            'live_fetch': bool(inputs.get('live_fetch')),
            'indicators': indicators,
        },
        'non_goals': [
            'not a buy signal',
            'does not originate tickers, prices, or disclosures',
            'news/social signals remain supporting evidence only',
        ],
    }
    if persist:
        _persist_artifact(artifact)
    return artifact


def compact_crash_rebound_gate(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a small dashboard/MCP-friendly summary."""
    data = snapshot or read_latest_crash_rebound_gate()
    policy = data.get('scanner_policy') if isinstance(data.get('scanner_policy'), dict) else {}
    counts = data.get('counts') if isinstance(data.get('counts'), dict) else {}
    return {
        'schema_version': data.get('schema_version') or SCHEMA_VERSION,
        'status': data.get('status') or 'unknown',
        'label': data.get('label') or 'Unknown',
        'score': data.get('score'),
        'confidence': data.get('confidence'),
        'data_coverage_pct': data.get('data_coverage_pct'),
        'summary': data.get('summary'),
        'counts': counts,
        'scanner_policy': {
            'mode': policy.get('mode'),
            'alpha_multiplier': policy.get('alpha_multiplier'),
            'risk_multiplier': policy.get('risk_multiplier'),
            'telegram_level': policy.get('telegram_level'),
        },
        'generated_at': data.get('generated_at'),
    }


def _merge_cache_indicators(indicators: dict[str, dict[str, Any]], *, now: datetime) -> None:
    kr_gate = _read_json_safe(MARKET_GATE_CACHE) or {}
    kr_metrics = kr_gate.get('metrics') if isinstance(kr_gate.get('metrics'), dict) else {}
    us_data = _read_json_safe(US_MARKET_DATA) or {}
    us_ts = us_data.get('timestamp')
    kr_ts = kr_gate.get('updated_at')

    if 'kospi' not in indicators:
        indicators['kospi'] = _indicator(
            'kospi',
            value=_first_number(kr_gate.get('kospi_close'), kr_metrics.get('kospi')),
            change_pct=_first_number(kr_gate.get('kospi_change_pct'), kr_metrics.get('kospi_change_pct')),
            rsi=_first_number(kr_metrics.get('rsi')),
            source='data/market_gate_cache.json',
            source_grade='A',
            fetched_at=kr_ts,
            now=now,
        )
    if 'usdkrw' not in indicators:
        usdkrw = _nested(us_data, 'currencies', 'USDKRW=X') or _nested(us_data, 'currencies', 'KRW=X') or {}
        indicators['usdkrw'] = _indicator(
            'usdkrw',
            value=_first_number(kr_metrics.get('usd_krw'), usdkrw.get('price'), usdkrw.get('current')),
            change_pct=_first_number(usdkrw.get('change'), usdkrw.get('change_pct')),
            source='us_market/output/market_data.json',
            source_grade='A',
            fetched_at=us_ts,
            now=now,
        )
    if 'vix' not in indicators:
        vix = _nested(us_data, 'volatility', '^VIX') or {}
        indicators['vix'] = _indicator(
            'vix',
            value=_first_number(vix.get('current'), vix.get('price'), _nested(us_data, 'fear_greed', 'vix')),
            change_pct=_first_number(vix.get('change'), vix.get('change_pct')),
            source='us_market/output/market_data.json',
            source_grade='A',
            fetched_at=us_ts,
            now=now,
        )
    if 'fear_greed' not in indicators:
        fg = us_data.get('fear_greed') if isinstance(us_data.get('fear_greed'), dict) else {}
        indicators['fear_greed'] = _indicator(
            'fear_greed',
            value=_first_number(fg.get('score')),
            label=fg.get('level'),
            source='us_market/output/market_data.json',
            source_grade='B',
            fetched_at=us_ts,
            now=now,
        )
    if 'sp500' not in indicators:
        spx = _nested(us_data, 'indices', 'SPY') or _nested(us_data, 'indices', '^GSPC') or {}
        indicators['sp500'] = _indicator(
            'sp500',
            value=_first_number(spx.get('current'), spx.get('price')),
            change_pct=_first_number(spx.get('change'), spx.get('change_pct')),
            source='us_market/output/market_data.json',
            source_grade='A',
            fetched_at=us_ts,
            now=now,
        )


def _merge_live_market_indicators(indicators: dict[str, dict[str, Any]], *, now: datetime) -> None:
    tickers = {
        'vix': '^VIX',
        'sp500': '^GSPC',
        'ewy': 'EWY',
        'usdkrw': 'KRW=X',
        'kospi': '^KS11',
    }
    for key, ticker in tickers.items():
        live = _fetch_yfinance_indicator(key, ticker, now=now)
        if live and _has_value(live):
            indicators[key] = live


def _fetch_yfinance_indicator(key: str, ticker: str, *, now: datetime) -> dict[str, Any] | None:
    try:
        from app.utils.yf_safe import yf_ticker_history_safe

        df = yf_ticker_history_safe(ticker, timeout=5.0, period='7d', interval='1d')
    except Exception as exc:
        logger.debug('live yfinance indicator failed for %s: %s', ticker, exc)
        return None
    if df is None or df.empty or 'Close' not in df.columns:
        return None
    close = df['Close'].dropna()
    if close.empty:
        return None
    latest = _safe_float(close.iloc[-1])
    previous = _safe_float(close.iloc[-2]) if len(close) >= 2 else None
    change_pct = ((latest - previous) / previous * 100.0) if latest is not None and previous else None
    fetched_at = _date_from_index(close.index[-1]) if hasattr(close, 'index') else now.isoformat()
    return _indicator(
        key,
        value=latest,
        change_pct=change_pct,
        source=f'yfinance:{ticker}',
        source_grade='A',
        fetched_at=fetched_at,
        now=now,
    )


def _evaluate_signal(defn: dict[str, Any], indicators: dict[str, Any]) -> dict[str, Any]:
    signal_id = str(defn['id'])
    indicator_key = str(defn['required_indicator'])
    indicator = indicators.get(indicator_key) if isinstance(indicators.get(indicator_key), dict) else {}
    value = _safe_float(indicator.get('value'))
    change_pct = _safe_float(indicator.get('change_pct'))
    rsi = _safe_float(indicator.get('rsi'))
    state = 'unknown'
    detail = 'required data unavailable'

    if signal_id == 'vix_drop_10pct':
        if change_pct is not None:
            state = 'pass' if change_pct <= -10.0 else 'fail'
            detail = f'VIX change {change_pct:.2f}%'
        elif value is not None:
            state = 'fail' if value >= 35 else 'unknown'
            detail = f'VIX level {value:.2f}; change missing'
    elif signal_id == 'fear_greed_extreme_fear':
        if value is not None:
            state = 'pass' if value <= 20 else 'fail'
            detail = f'Fear & Greed {value:.0f}'
    elif signal_id == 'put_call_above_1':
        if value is not None:
            state = 'pass' if value >= 1.0 else 'fail'
            detail = f'Put/Call {value:.2f}'
    elif signal_id == 'ewy_rebound_1pct':
        if change_pct is not None:
            state = 'pass' if change_pct >= 1.0 else 'fail'
            detail = f'EWY change {change_pct:.2f}%'
    elif signal_id == 'sp500_positive':
        if change_pct is not None:
            state = 'pass' if change_pct > 0 else 'fail'
            detail = f'S&P500 proxy change {change_pct:.2f}%'
    elif signal_id == 'insider_cluster_buy':
        state, detail = _boolean_signal(value, true_detail='insider cluster buy present')
    elif signal_id == 'foreign_flow_turn':
        if value is not None:
            state = 'pass' if value > 0 else 'fail'
            detail = f'foreign flow {value:.0f}'
    elif signal_id == 'short_balance_down':
        if change_pct is not None:
            state = 'pass' if change_pct < 0 else 'fail'
            detail = f'short balance change {change_pct:.2f}%'
    elif signal_id == 'margin_loan_flush':
        if change_pct is not None:
            state = 'pass' if change_pct <= -3.0 else 'fail'
            detail = f'margin loan change {change_pct:.2f}%'
    elif signal_id == 'hy_oas_narrowing':
        if change_pct is not None:
            state = 'pass' if change_pct < 0 else 'fail'
            detail = f'HY OAS change {change_pct:.2f}%'
    elif signal_id == 'usdkrw_down':
        if change_pct is not None:
            state = 'pass' if change_pct < 0 else 'fail'
            detail = f'USD/KRW change {change_pct:.2f}%'
    elif signal_id == 'kospi_rsi_rebound':
        if rsi is not None:
            state = 'pass' if 25 <= rsi <= 45 else 'fail'
            detail = f'KOSPI RSI {rsi:.1f}'
        elif change_pct is not None:
            state = 'pass' if change_pct >= 1.0 else 'fail'
            detail = f'KOSPI change {change_pct:.2f}%; RSI missing'
    elif signal_id == 'policy_stabilization':
        state, detail = _boolean_signal(value, true_detail='policy stabilization present')
    elif signal_id == 'news_tone_recovery':
        if value is not None:
            state = 'pass' if value > 0 else 'fail'
            detail = f'news tone score {value:.2f}'

    freshness = indicator.get('freshness') or 'unknown'
    if state == 'pass' and freshness == 'stale':
        status = 'limited'
    elif state == 'unknown':
        status = 'unknown'
    else:
        status = 'ok'

    return {
        'id': signal_id,
        'label': defn['label'],
        'state': state,
        'status': status,
        'weight': defn['weight'],
        'detail': detail,
        'source_grade': defn['source_grade'],
        'source': indicator.get('source'),
        'fetched_at': indicator.get('fetched_at'),
        'freshness': freshness,
        'confidence': indicator.get('confidence') or _confidence_for_freshness(freshness),
    }


def _classify_regime(
    score: float,
    yes_count: int,
    fail_count: int,
    unknown_count: int,
    indicators: dict[str, Any],
) -> dict[str, str]:
    vix = _safe_float(_nested(indicators, 'vix', 'value'))
    kospi_change = _safe_float(_nested(indicators, 'kospi', 'change_pct'))
    if vix is not None and vix >= 35:
        return {'status': 'crash_risk', 'label': 'Crash risk', 'confidence': 'medium'}
    if kospi_change is not None and kospi_change <= -3.0 and yes_count < 3:
        return {'status': 'risk_off', 'label': 'Risk-off', 'confidence': 'medium'}
    if score >= 70 and yes_count >= 7 and unknown_count <= 4:
        return {'status': 'recovery_confirmed', 'label': 'Recovery confirmed', 'confidence': 'high'}
    if score >= 50 and yes_count >= 5:
        return {'status': 'rebound_confirmed', 'label': 'Rebound confirmed', 'confidence': 'medium'}
    if score >= 30 and yes_count >= 3:
        return {'status': 'rebound_watch', 'label': 'Rebound watch', 'confidence': 'medium'}
    if fail_count >= 6:
        return {'status': 'caution', 'label': 'Caution', 'confidence': 'medium'}
    return {'status': 'neutral', 'label': 'Neutral', 'confidence': 'low'}


def _scanner_policy(regime: dict[str, str], score: float, coverage: float, stale_count: int) -> dict[str, Any]:
    status = regime['status']
    policy = {
        'mode': 'observe',
        'alpha_multiplier': 1.0,
        'risk_multiplier': 1.0,
        'confidence_cap_pct': 70 if coverage < 50 else 85,
        'telegram_level': 'normal',
        'reason': 'Market context is neutral or insufficiently confirmed.',
    }
    if status in {'crash_risk', 'risk_off'}:
        policy.update({
            'mode': 'risk_off',
            'alpha_multiplier': 0.94,
            'risk_multiplier': 1.18,
            'confidence_cap_pct': 60,
            'telegram_level': 'strict',
            'reason': 'Broad-market crash/risk-off pressure is still active.',
        })
    elif status == 'caution':
        policy.update({
            'mode': 'caution',
            'alpha_multiplier': 0.98,
            'risk_multiplier': 1.08,
            'confidence_cap_pct': 72,
            'telegram_level': 'normal',
            'reason': 'Mixed rebound evidence; keep risk filters tight.',
        })
    elif status == 'rebound_watch':
        policy.update({
            'mode': 'rebound_watch',
            'alpha_multiplier': 1.02,
            'risk_multiplier': 0.98,
            'confidence_cap_pct': 82,
            'telegram_level': 'normal',
            'reason': 'Early rebound evidence exists but needs flow/FX confirmation.',
        })
    elif status == 'rebound_confirmed':
        policy.update({
            'mode': 'rebound_confirmed',
            'alpha_multiplier': 1.04,
            'risk_multiplier': 0.94,
            'confidence_cap_pct': 90,
            'telegram_level': 'elevated',
            'reason': 'Several independent rebound conditions are aligned.',
        })
    elif status == 'recovery_confirmed':
        policy.update({
            'mode': 'recovery_confirmed',
            'alpha_multiplier': 1.07,
            'risk_multiplier': 0.90,
            'confidence_cap_pct': 95,
            'telegram_level': 'elevated',
            'reason': 'Strong cross-market recovery confirmation is present.',
        })
    if stale_count >= 4:
        policy['confidence_cap_pct'] = min(int(policy['confidence_cap_pct']), 70)
        policy['reason'] += ' Several inputs are stale, so confidence is capped.'
    policy['score'] = score
    policy['data_coverage_pct'] = coverage
    return policy


def _summary_text(
    regime: dict[str, str],
    score: float,
    yes_count: int,
    fail_count: int,
    unknown_count: int,
    coverage: float,
) -> str:
    return (
        f"{regime['label']} score {score:.1f}. "
        f"signals pass {yes_count}, fail {fail_count}, unknown {unknown_count}; "
        f"data coverage {coverage:.1f}%."
    )


def _persist_artifact(artifact: dict[str, Any]) -> None:
    write_json_atomic(str(LATEST_PATH), artifact, sort_keys=False)
    stamp = str(artifact.get('generated_at') or _now_utc().isoformat())
    clean_stamp = stamp.replace(':', '').replace('-', '').replace('+', 'Z').split('.')[0]
    history_path = HISTORY_ROOT / f'{clean_stamp}.json'
    write_json_atomic(str(history_path), artifact, sort_keys=False)


def _indicator(
    key: str,
    *,
    value: Any = None,
    change_pct: Any = None,
    rsi: Any = None,
    label: Any = None,
    source: str,
    source_grade: str,
    fetched_at: Any,
    now: datetime,
) -> dict[str, Any]:
    fetched_text = str(fetched_at or '')
    freshness = _freshness(fetched_text, now=now)
    return {
        'id': key,
        'value': _safe_float(value),
        'change_pct': _safe_float(change_pct),
        'rsi': _safe_float(rsi),
        'label': label,
        'source': source,
        'source_grade': source_grade,
        'fetched_at': fetched_text or None,
        'freshness': freshness,
        'confidence': _confidence_for_freshness(freshness),
        'status': 'ok' if _safe_float(value) is not None or _safe_float(change_pct) is not None else 'unavailable',
    }


def _normalize_indicator(key: str, raw: Any, *, source: str, now: datetime) -> dict[str, Any]:
    if isinstance(raw, dict):
        return _indicator(
            key,
            value=raw.get('value'),
            change_pct=raw.get('change_pct'),
            rsi=raw.get('rsi'),
            label=raw.get('label'),
            source=str(raw.get('source') or source),
            source_grade=str(raw.get('source_grade') or 'payload'),
            fetched_at=raw.get('fetched_at') or raw.get('updated_at') or now.isoformat(),
            now=now,
        )
    return _indicator(
        key,
        value=raw,
        source=source,
        source_grade='payload',
        fetched_at=now.isoformat(),
        now=now,
    )


def _freshness(value: str, *, now: datetime) -> str:
    parsed = _parse_dt(value)
    if parsed is None:
        return 'unknown'
    age = now - parsed.astimezone(timezone.utc)
    if age <= timedelta(hours=8):
        return 'fresh'
    if age <= timedelta(days=3):
        return 'recent'
    return 'stale'


def _confidence_for_freshness(freshness: str) -> str:
    if freshness == 'fresh':
        return 'high'
    if freshness == 'recent':
        return 'medium'
    if freshness == 'stale':
        return 'low'
    return 'low'


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        with path.open('r', encoding='utf-8') as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug('json read failed for %s: %s', path, exc)
        return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace('Z', '+00:00')
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:10], '%Y-%m-%d')
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _date_from_index(value: Any) -> str:
    try:
        return value.to_pydatetime().replace(tzinfo=timezone.utc).isoformat()
    except Exception:
        try:
            return value.date().isoformat()
        except Exception:
            return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _safe_float(value)
        if number is not None:
            return number
    return None


def _has_value(row: dict[str, Any]) -> bool:
    return _safe_float(row.get('value')) is not None or _safe_float(row.get('change_pct')) is not None


def _boolean_signal(value: float | None, *, true_detail: str) -> tuple[str, str]:
    if value is None:
        return 'unknown', 'required data unavailable'
    return ('pass', true_detail) if value > 0 else ('fail', 'signal absent')


def _nested(data: Any, *keys: str) -> Any:
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _live_fetch_default() -> bool:
    return _as_bool(os.getenv('MIROFISH_CRASH_REBOUND_LIVE_FETCH'), default=False)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
