"""L0 training dataset builder — lookahead-safe, deterministic, no LLM/network."""

import os
import json
from datetime import datetime, timezone

from app.utils.atomic_json import write_json_atomic
from app.services.mirofish import edge_map, outcome_tracker
from app.services.mirofish.intelligence import regime

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
TRAINING_DATASET_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'training_dataset.json')

NUMERIC_FEATURES = (
    'alpha_score', 'risk_score', 'ranking_score', 'goal_fit_score',
    'source_count', 'trend_20d_pct', 'volume_ratio', 'cio_confidence_pct',
)


def _num(value):
    try:
        if value is None or value == '':
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_training_dataset(*, limit_workflows=200, items=None, timeline=None, write=True):
    if items is None:
        items = edge_map._evaluated_items(limit_workflows)

    if timeline is None:
        timeline = regime.read_regime_timeline()
        if timeline is None:
            timeline = regime.build_regime_timeline(write=False)
    if not isinstance(timeline, dict):
        timeline = {'by_date': {}}

    rows = []
    regime_distribution = {}

    for item in (items or []):
        feature = item.get('feature_snapshot') or {}

        features = {name: _num(feature.get(name)) for name in NUMERIC_FEATURES}

        entry_date = str(item.get('entry_date') or '')
        regime_label = regime.classify_regime(entry_date, timeline)

        categoricals = {
            'signal_quality': str(feature.get('signal_quality') or ''),
            'scanner_action': str(feature.get('scanner_action') or ''),
            'market': outcome_tracker._infer_market(str(item.get('symbol') or '')),
            'regime': regime_label,
        }

        tags = [str(t).strip() for t in (feature.get('strategy_tags') or []) if str(t or '').strip()]

        hit_val = item.get('hit')
        label = {
            'hit': bool(hit_val) if hit_val is not None else None,
            'forward_return_pct': _num(item.get('forward_return_pct')),
        }

        meta = {
            'symbol': str(item.get('symbol') or ''),
            'entry_date': entry_date,
        }

        rows.append({
            'features': features,
            'categoricals': categoricals,
            'tags': tags,
            'label': label,
            'meta': meta,
        })

        regime_distribution[regime_label] = regime_distribution.get(regime_label, 0) + 1

    envelope = {
        'schema_version': 'mirofish.training_dataset.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'row_count': len(rows),
        'feature_names': list(NUMERIC_FEATURES),
        'regime_distribution': regime_distribution,
        'rows': rows,
    }

    if write:
        try:
            os.makedirs(os.path.dirname(TRAINING_DATASET_PATH), exist_ok=True)
            write_json_atomic(TRAINING_DATASET_PATH, envelope, sort_keys=False)
        except Exception:
            pass

    return envelope


def read_training_dataset():
    if not os.path.isfile(TRAINING_DATASET_PATH):
        return None
    try:
        with open(TRAINING_DATASET_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None


def dataset_summary():
    data = read_training_dataset()
    if data is None:
        try:
            data = build_training_dataset(write=False)
        except Exception:
            data = None

    if not isinstance(data, dict):
        return {'row_count': 0, 'hit_count': 0, 'hit_rate': 0.0, 'regime_distribution': {}}

    rows = data.get('rows') or []
    row_count = len(rows)
    hit_count = sum(1 for r in rows if isinstance(r, dict) and (r.get('label') or {}).get('hit') is True)
    hit_rate = round(hit_count / row_count, 4) if row_count else 0.0

    return {
        'row_count': row_count,
        'hit_count': hit_count,
        'hit_rate': hit_rate,
        'regime_distribution': data.get('regime_distribution') or {},
    }
