"""Offline-only chronological ridge baseline; never used by live ranking.

Metrics describe independent selection cohorts, NOT a compounded portfolio.
Execution/benchmark/fee labels must be supplied from a verified external ledger.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.services.mirofish.semantic_decisions import _instant


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError('finite_number_required')
    return float(value)


def train_evaluate(rows: list[dict], *, train_before: str, test_from: str, as_of: str,
                   embargo_days: int = 3, ridge: float = 1.0) -> dict:
    import numpy as np
    train_cutoff, test_cutoff, now = map(_instant, (train_before, test_from, as_of))
    if not train_cutoff < test_cutoff < now or embargo_days < 0 or not math.isfinite(ridge) or ridge <= 0:
        raise ValueError('invalid_split_or_regularization')
    seen, valid, excluded = set(), [], 0
    for row in rows:
        identity = (row.get('market'), row.get('symbol'), row.get('decision_at'))
        if identity in seen:
            raise ValueError('duplicate_identity')
        seen.add(identity)
        try:
            decision = _instant(row.get('decision_at'))
            available = _instant(row.get('available_at'))
            end = _instant(row.get('label_end_at'))
            if (available > decision or end <= decision or end > now
                    or row.get('execution_status') != 'filled'
                    or not row.get('symbol') or not row.get('market') or not row.get('event_id')):
                raise ValueError('unusable_row')
            cost = _number(row.get('cost_bps'))
            if cost < 0:
                raise ValueError('negative_cost')
            target = _number(row.get('gross_return')) - _number(row.get('benchmark_return')) - cost / 10000
            baseline = _number(row.get('baseline_score'))
            features = {k: _number(v) for k, v in row['features'].items()}
            if not features:
                raise ValueError('missing_features')
            valid.append({**row, 'decision': decision, 'end': end,
                          'target': target, 'features': features, 'baseline_score': baseline})
        except (ValueError, TypeError, KeyError, AttributeError):
            excluded += 1
    train = [r for r in valid if r['end'] < train_cutoff
             and r['end'] < test_cutoff - timedelta(days=embargo_days)]
    test = [r for r in valid if test_cutoff <= r['decision'] < now]
    def events(row):
        return set(row.get('event_ids') or [row['event_id']])
    test_events = {event for r in test for event in events(r)}
    purged = sum(bool(events(r) & test_events) for r in train)
    train = [r for r in train if not events(r) & test_events]
    if len(train) < 10 or not test:
        raise ValueError('insufficient_mature_rows')
    columns = sorted(train[0]['features'])
    if any(sorted(r['features']) != columns for r in train + test):
        raise ValueError('feature_schema_mismatch')
    x = np.array([[r['features'][k] for k in columns] for r in train])
    y = np.array([r['target'] for r in train])
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale == 0] = 1
    z = (x - mean) / scale
    intercept = float(y.mean())
    weights = np.linalg.solve(z.T @ z + ridge * np.eye(len(columns)), z.T @ (y - intercept))
    groups = defaultdict(list)
    for row in test:
        score = intercept + ((np.array([row['features'][k] for k in columns])-mean)/scale) @ weights
        groups[row['decision'].isoformat()].append({**row, 'research_score': float(score)})
    cohorts = []
    for instant, candidates in sorted(groups.items()):
        def select(field):
            return sorted(candidates, key=lambda r: (-r[field], r['market'], r['symbol']))[:3]
        predicted, baseline = select('research_score'), select('baseline_score')
        cohorts.append({'decision_at': instant, 'candidate_count': len(candidates),
            'selected_count': len(predicted),
            'research_symbols': [r['market'] + ':' + r['symbol'] for r in predicted],
            'baseline_symbols': [r['market'] + ':' + r['symbol'] for r in baseline],
            'research_excess_return': sum(r['target'] for r in predicted) / len(predicted),
            'baseline_excess_return': sum(r['target'] for r in baseline) / len(baseline)})
    daily = defaultdict(list)
    for cohort in cohorts:
        day = _instant(cohort['decision_at']).astimezone(ZoneInfo('Asia/Seoul')).date().isoformat()
        daily[day].append(cohort['research_excess_return'] - cohort['baseline_excess_return'])
    delta = [sum(v)/len(v) for _,v in sorted(daily.items())]
    # No confidence claim for a tiny sample. Consecutive five-day blocks retain
    # short-range dependence; this is exploratory, not a promotion gate.
    interval = None
    if len(delta) >= 30:
        rng = np.random.default_rng(0)
        samples = []
        for _ in range(2000):
            starts = rng.integers(0, len(delta)-4, size=math.ceil(len(delta)/5))
            values = [v for start in starts for v in delta[start:start+5]][:len(delta)]
            samples.append(float(np.mean(values)))
        interval = [float(v) for v in np.quantile(samples, [.025, .975])]
    return {'version': 'semantic-ridge-v1', 'ranking_effect': 'none', 'promotion': 'not_authorized',
        'train_rows': len(train), 'test_rows': len(test), 'excluded_rows': excluded,
        'purged_event_rows': purged, 'unused_valid_rows': len(valid)-len(train)-len(test)-purged,
        'split': {'train_before': train_before, 'test_from': test_from, 'as_of': as_of,
                  'embargo_calendar_days': embargo_days},
        'model': {'columns': columns, 'mean': mean.tolist(), 'scale': scale.tolist(),
                  'weights': weights.tolist(), 'intercept': intercept, 'ridge': ridge},
        'metrics': {'mean_excess_return_at3': sum(c['research_excess_return'] for c in cohorts)/len(cohorts),
                    'baseline_mean_excess_return_at3': sum(c['baseline_excess_return'] for c in cohorts)/len(cohorts),
                    'mean_daily_difference': sum(delta)/len(delta),
                    'exploratory_5day_block_ci95': interval, 'days': len(delta),
                    'metric_scope': 'independent selection cohorts, not compounded portfolio'},
        'cohorts': cohorts}
