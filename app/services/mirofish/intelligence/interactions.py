"""L2 feature-interaction profit miner — lookahead-safe, deterministic, no LLM/network."""

import os
import json
import itertools
from datetime import datetime, timezone

from app.utils.atomic_json import write_json_atomic
from app.services.mirofish.intelligence import dataset

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
INTERACTION_MAP_PATH = os.path.join(REPO_ROOT, 'data', 'admin_mirofish', 'intelligence', 'interaction_map.json')

MIN_COMBO_SAMPLES = 5
TOP_K = 15


def _num(value):
    try:
        if value is None or value == '':
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _row_conditions(row):
    conditions = []

    for tag in (row.get('tags') or []):
        conditions.append(f'tag:{tag}')

    alpha = _num((row.get('features') or {}).get('alpha_score'))
    if alpha >= 80:
        conditions.append('alpha:80+')
    elif alpha >= 70:
        conditions.append('alpha:70-80')
    else:
        conditions.append('alpha:lt70')

    cats = row.get('categoricals') or {}

    regime_val = cats.get('regime')
    if regime_val:
        conditions.append(f'regime:{regime_val}')

    quality_val = cats.get('signal_quality')
    if quality_val:
        conditions.append(f'quality:{quality_val}')

    action_val = cats.get('scanner_action')
    if action_val:
        conditions.append(f'action:{action_val}')

    seen = set()
    deduped = []
    for cond in conditions:
        if cond not in seen:
            seen.add(cond)
            deduped.append(cond)
    return deduped


def build_interaction_map(dataset_obj=None, *, max_order=3, write=True):
    if dataset_obj is None:
        dataset_obj = dataset.build_training_dataset(write=False)

    rows = dataset_obj.get('rows') or []

    by_combo = {}

    for row in rows:
        conds = sorted(_row_conditions(row))
        label = row.get('label') or {}
        hit = label.get('hit') is True
        ret = _num(label.get('forward_return_pct'))

        for order in range(2, max_order + 1):
            for combo in itertools.combinations(conds, order):
                key = ' & '.join(combo)
                entry = by_combo.setdefault(key, {'n': 0, 'hits': 0, 'ret_sum': 0.0})
                entry['n'] += 1
                if hit:
                    entry['hits'] += 1
                entry['ret_sum'] += ret

    summarized = {}
    for key, entry in by_combo.items():
        n = entry['n']
        insufficient = n < MIN_COMBO_SAMPLES
        summarized[key] = {
            'n': n,
            'hit_rate': round(entry['hits'] / n, 4) if n else 0.0,
            'expectancy_pct': round(entry['ret_sum'] / n, 4) if n else 0.0,
            'insufficient': insufficient,
        }

    sufficient = [
        {'combo': k, 'n': v['n'], 'hit_rate': v['hit_rate'], 'expectancy_pct': v['expectancy_pct']}
        for k, v in summarized.items() if not v['insufficient']
    ]

    top_positive = sorted(sufficient, key=lambda x: x['expectancy_pct'], reverse=True)[:TOP_K]
    top_negative = sorted(sufficient, key=lambda x: x['expectancy_pct'])[:TOP_K]

    envelope = {
        'schema_version': 'mirofish.interaction_map.v1',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'lookahead_safe': True,
        'evaluated_count': len(rows),
        'max_order': max_order,
        'min_combo_samples': MIN_COMBO_SAMPLES,
        'by_combo': summarized,
        'top_positive': top_positive,
        'top_negative': top_negative,
    }

    if write:
        os.makedirs(os.path.dirname(INTERACTION_MAP_PATH), exist_ok=True)
        write_json_atomic(INTERACTION_MAP_PATH, envelope, sort_keys=False)

    return envelope


def read_interaction_map():
    if not os.path.exists(INTERACTION_MAP_PATH):
        return None
    try:
        with open(INTERACTION_MAP_PATH, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception:
        return None
