"""Deterministic market fear index for MiroFish dashboards.

Score direction is explicit: 0 = low fear / risk appetite, 100 = extreme fear.
The index is read-only context for alpha filtering. It must not be treated as a
standalone buy/sell signal.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app.services.mirofish.crash_rebound_gate as crash_rebound_gate
from app.utils.atomic_json import write_json_atomic

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 'mirofish.fear_index.v1'

REPO_ROOT = Path(__file__).resolve().parents[3]
ARTIFACT_ROOT = REPO_ROOT / 'data' / 'admin_mirofish' / 'market' / 'fear_index'
LATEST_PATH = ARTIFACT_ROOT / 'latest.json'
HISTORY_ROOT = ARTIFACT_ROOT / 'history'

COMPONENTS: tuple[dict[str, Any], ...] = (
    {
        'id': 'fear_greed',
        'label': 'Fear & Greed inverse',
        'weight': 30,
        'source_grade': 'B',
        'description': 'CNN-style Fear & Greed score inverted into fear pressure.',
    },
    {
        'id': 'vix',
        'label': 'VIX stress',
        'weight': 30,
        'source_grade': 'A',
        'description': 'Equity volatility stress from VIX level.',
    },
    {
        'id': 'usdkrw',
        'label': 'USD/KRW pressure',
        'weight': 15,
        'source_grade': 'S/A',
        'description': 'KRW weakness pressure through USD/KRW change.',
    },
    {
        'id': 'kospi',
        'label': 'KOSPI price stress',
        'weight': 15,
        'source_grade': 'A',
        'description': 'Domestic index drawdown/rebound pressure.',
    },
    {
        'id': 'sp500',
        'label': 'S&P500 risk appetite',
        'weight': 10,
        'source_grade': 'A',
        'description': 'Global equity direction pressure.',
    },
)


def get_fear_index_schema() -> dict[str, Any]:
    return {
        'schema_version': SCHEMA_VERSION,
        'score_direction': '0=low fear, 100=extreme fear',
        'buy_signal': False,
        'components': [dict(item) for item in COMPONENTS],
        'rules': {
            'deterministic_inputs_only': True,
            'missing_component_excluded_from_weighted_score': True,
            'llm_may_explain_not_invent': True,
            'news_social_secondary_only': True,
        },
    }


def read_latest_fear_index() -> dict[str, Any]:
    latest = _read_json_safe(LATEST_PATH)
    if latest:
        return latest
    inputs = crash_rebound_gate.collect_crash_rebound_inputs(live_fetch=False)
    return evaluate_fear_index(inputs, persist=False)


def run_fear_index(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    live = _as_bool(payload.get('live'), default=False)
    inputs = crash_rebound_gate.collect_crash_rebound_inputs(payload, live_fetch=live)
    return evaluate_fear_index(inputs, persist=True)


def evaluate_fear_index(inputs: dict[str, Any] | None = None, *, persist: bool = False) -> dict[str, Any]:
    now = _now_utc()
    inputs = inputs or crash_rebound_gate.collect_crash_rebound_inputs(live_fetch=False)
    indicators = inputs.get('indicators') if isinstance(inputs.get('indicators'), dict) else {}
    components = [_component_score(item, indicators) for item in COMPONENTS]
    available = [item for item in components if item.get('status') != 'unknown']
    available_weight = sum(float(item.get('weight') or 0) for item in available)
    weighted = sum(float(item.get('score') or 0) * float(item.get('weight') or 0) for item in available)
    score = round(weighted / available_weight, 1) if available_weight else None
    total_weight = sum(float(item['weight']) for item in COMPONENTS)
    coverage_pct = round((available_weight / total_weight) * 100, 1) if total_weight else 0.0
    level = _fear_level(score)
    top_component = _top_component(available)
    stale_count = sum(1 for item in available if item.get('freshness') == 'stale')
    artifact = {
        'schema_version': SCHEMA_VERSION,
        'generated_at': now.isoformat(),
        'score': score,
        'level': level['id'],
        'level_label': level['label'],
        'tone': level['tone'],
        'confidence': _confidence(coverage_pct, stale_count),
        'coverage_pct': coverage_pct,
        'summary': _summary(score, level, coverage_pct, top_component, stale_count),
        'components': components,
        'dashboard': {
            'display_score': '--' if score is None else str(int(round(score))),
            'display_label': level['label'],
            'color': level['color'],
            'primary_driver': top_component.get('label') if top_component else None,
            'primary_detail': top_component.get('detail') if top_component else None,
        },
        'source_packet': {
            'generated_at': inputs.get('generated_at'),
            'live_fetch': bool(inputs.get('live_fetch')),
            'indicators': indicators,
        },
        'non_goals': [
            'not a standalone buy or sell signal',
            'does not originate market prices',
            'used as market risk context for Top3 filtering',
        ],
    }
    if persist:
        _persist(artifact)
    return artifact


def compact_fear_index(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    data = snapshot or read_latest_fear_index()
    return {
        'schema_version': data.get('schema_version') or SCHEMA_VERSION,
        'score': data.get('score'),
        'level': data.get('level'),
        'level_label': data.get('level_label'),
        'tone': data.get('tone'),
        'confidence': data.get('confidence'),
        'coverage_pct': data.get('coverage_pct'),
        'summary': data.get('summary'),
        'dashboard': data.get('dashboard') if isinstance(data.get('dashboard'), dict) else {},
        'generated_at': data.get('generated_at'),
    }


def _component_score(defn: dict[str, Any], indicators: dict[str, Any]) -> dict[str, Any]:
    component_id = str(defn['id'])
    indicator = indicators.get(component_id) if isinstance(indicators.get(component_id), dict) else {}
    value = _num(indicator.get('value'))
    change_pct = _num(indicator.get('change_pct'))
    score: float | None = None
    detail = 'required data unavailable'

    if component_id == 'fear_greed':
        if value is not None:
            score = _clamp(100.0 - value)
            detail = f'Fear & Greed {value:.0f} -> fear {score:.0f}'
    elif component_id == 'vix':
        if value is not None:
            score = _vix_to_fear(value)
            detail = f'VIX {value:.1f}'
            if change_pct is not None:
                detail += f', change {change_pct:+.2f}%'
    elif component_id == 'usdkrw':
        if change_pct is not None:
            score = _clamp(50.0 + change_pct * 12.0)
            detail = f'USD/KRW change {change_pct:+.2f}%'
        elif value is not None:
            score = 50.0
            detail = f'USD/KRW {value:.2f}; change missing'
    elif component_id == 'kospi':
        if change_pct is not None:
            score = _clamp(50.0 - change_pct * 10.0)
            detail = f'KOSPI change {change_pct:+.2f}%'
    elif component_id == 'sp500':
        if change_pct is not None:
            score = _clamp(50.0 - change_pct * 10.0)
            detail = f'S&P500 proxy change {change_pct:+.2f}%'

    freshness = str(indicator.get('freshness') or 'unknown')
    status = 'unknown' if score is None else 'ok'
    if score is not None and freshness == 'stale':
        status = 'limited'
    return {
        'id': component_id,
        'label': defn['label'],
        'score': None if score is None else round(score, 1),
        'weight': defn['weight'],
        'status': status,
        'detail': detail,
        'source': indicator.get('source'),
        'source_grade': indicator.get('source_grade') or defn['source_grade'],
        'fetched_at': indicator.get('fetched_at'),
        'freshness': freshness,
        'confidence': indicator.get('confidence') or ('low' if freshness in {'stale', 'unknown'} else 'medium'),
    }


def _vix_to_fear(vix: float) -> float:
    if vix <= 12:
        return 10.0
    if vix <= 20:
        return _linear(vix, 12, 20, 10, 45)
    if vix <= 30:
        return _linear(vix, 20, 30, 45, 75)
    if vix <= 40:
        return _linear(vix, 30, 40, 75, 95)
    return 98.0


def _fear_level(score: float | None) -> dict[str, str]:
    if score is None:
        return {'id': 'unknown', 'label': '데이터 부족', 'tone': 'unknown', 'color': '#94a3b8'}
    if score >= 80:
        return {'id': 'extreme_fear', 'label': '극단 공포', 'tone': 'danger', 'color': '#fb7185'}
    if score >= 60:
        return {'id': 'fear', 'label': '공포', 'tone': 'warning', 'color': '#f59e0b'}
    if score >= 40:
        return {'id': 'neutral', 'label': '중립', 'tone': 'neutral', 'color': '#a3a3a3'}
    if score >= 20:
        return {'id': 'low_fear', 'label': '낮은 공포', 'tone': 'calm', 'color': '#34d399'}
    return {'id': 'complacent', 'label': '탐욕 과열', 'tone': 'risk', 'color': '#22d3ee'}


def _top_component(components: list[dict[str, Any]]) -> dict[str, Any]:
    if not components:
        return {}
    return max(components, key=lambda item: float(item.get('score') or 0))


def _summary(score: float | None, level: dict[str, str], coverage: float, top: dict[str, Any], stale_count: int) -> str:
    if score is None:
        return '공포지수 계산에 필요한 시장 데이터가 부족합니다.'
    driver = top.get('label') or 'market components'
    suffix = ' 일부 입력이 stale 상태라 신뢰도는 제한됩니다.' if stale_count else ''
    return f"공포지수 {score:.1f} ({level['label']}). 주요 요인: {driver}. 데이터 커버리지 {coverage:.1f}%.{suffix}"


def _confidence(coverage: float, stale_count: int) -> str:
    if coverage >= 80 and stale_count == 0:
        return 'high'
    if coverage >= 50 and stale_count <= 2:
        return 'medium'
    return 'low'


def _persist(artifact: dict[str, Any]) -> None:
    write_json_atomic(str(LATEST_PATH), artifact, sort_keys=False)
    stamp = str(artifact.get('generated_at') or _now_utc().isoformat())
    clean = stamp.replace(':', '').replace('-', '').replace('+', 'Z').split('.')[0]
    write_json_atomic(str(HISTORY_ROOT / f'{clean}.json'), artifact, sort_keys=False)


def _read_json_safe(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.debug('fear index read failed for %s: %s', path, exc)
        return None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _linear(value: float, x1: float, x2: float, y1: float, y2: float) -> float:
    if x2 == x1:
        return y1
    return y1 + (value - x1) * (y2 - y1) / (x2 - x1)


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
