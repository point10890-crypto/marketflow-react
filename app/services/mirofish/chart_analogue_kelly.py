"""Bounded, source-backed chart cohorts and Kelly research attribution.

One captured adjusted-price snapshot describes historical analogues. The
purged chronological cohorts test retrospective stability, not a historical
point-in-time trading strategy. No result in this module authorizes orders.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from datetime import date, datetime, timezone

import numpy as np

from app.services.mirofish import chart_analogue as engine
from app.services.mirofish.kelly_research import empirical_kelly

POLICY_ID = 'chart-analogue-kelly-v1'
POLICY = {'horizon_sessions': 20, 'cost_bps': 33, 'min_samples': 30,
          'min_similarity': .8, 'max_positions': 3, 'max_weight': .2,
          'max_exposure': .6, 'min_cash': .4, 'kelly_fraction': .5,
          'volatility_threshold': .03, 'max_group_samples': 120,
          'split_fraction': .6, 'split_basis': 'scoped_observed_session_calendar',
          'score_basis': 'net_expectancy_pct_plus_half_net_p10_pct',
          'confidence_z': 1.96, 'purge': 'validation_input_start_at_or_after_split'}
WARNINGS = ['prospective_validation_required', 'historical_point_in_time_unverified',
            'snapshot_retrospective_stability_not_walk_forward',
            'current_universe_survivorship_bias', 'shared_market_regime_dependence',
            'assumed_33bps_roundtrip_cost_not_executed_fill',
            'supplier_adjusted_history_can_be_revised',
            'research_weights_are_not_approved_allocations']
DAY_US = 86_400_000_000
CLOSE_UTC_US = (6 * 3600 + 30 * 60) * 1_000_000


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _timestamp_us(value):
    elapsed = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('invalid_universe')
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('invalid_universe') from error


def _scope(universe, cutoff):
    if not isinstance(universe, dict):
        raise ValueError('invalid_universe')
    today = cutoff.astimezone(engine.KST).date()
    scope_day = _day(universe.get('as_of'))
    if scope_day > today:
        raise ValueError('future_universe')
    if (today - scope_day).days > engine.STALE_DAYS:
        raise ValueError('stale_universe')
    ranking, quality = universe.get('ranking'), universe.get('quality')
    if not isinstance(ranking, dict) or not isinstance(quality, dict):
        raise ValueError('invalid_universe')
    for group in (ranking, quality):
        if group.get('as_of') is not None and _day(group['as_of']) != scope_day:
            raise ValueError('invalid_universe')
    ranked, passed = ranking.get('ranked'), quality.get('passed')
    if (not isinstance(ranked, list) or not 1 <= len(ranked) <= 100
            or not isinstance(passed, list) or len(passed) > len(ranked)):
        raise ValueError('invalid_universe')
    identities, ranks = {}, set()
    for row in ranked:
        if not isinstance(row, dict):
            raise ValueError('invalid_universe')
        symbol, rank = row.get('symbol'), row.get('rank')
        if (not isinstance(symbol, str) or not re.fullmatch(r'[0-9]{6}', symbol)
                or symbol in identities or isinstance(rank, bool) or not isinstance(rank, int)
                or not 1 <= rank <= 100 or rank in ranks
                or row.get('market') not in {'KOSPI', 'KOSDAQ'}
                or not isinstance(row.get('name'), str) or not row['name'].strip()
                or not _finite(row.get('market_cap')) or row['market_cap'] <= 0):
            raise ValueError('invalid_universe')
        identities[symbol] = row
        ranks.add(rank)
    selected, seen = [], set()
    for row in passed:
        if not isinstance(row, dict) or row.get('symbol') not in identities or row['symbol'] in seen:
            raise ValueError('invalid_universe')
        original = identities[row['symbol']]
        if any(row.get(key) != original.get(key) for key in ('symbol', 'name', 'market', 'rank', 'market_cap')):
            raise ValueError('invalid_universe')
        if row.get('quality_pass') is False:
            raise ValueError('invalid_universe')
        financial = row.get('financial') or {}
        if not isinstance(financial, dict):
            raise ValueError('invalid_universe')
        for key in ('fetched_at', 'captured_at'):
            if financial.get(key):
                try:
                    captured = engine._cutoff(financial[key])
                except ValueError as error:
                    raise ValueError('invalid_universe') from error
                if captured > cutoff:
                    raise ValueError('future_universe_capture')
        seen.add(row['symbol'])
        selected.append(dict(original))
    return ranked, sorted(selected, key=lambda row: (row['rank'], row['symbol'])), scope_day.isoformat()


def _empty(row):
    return {'rank': 0, 'symbol': row['symbol'], 'target': row['name'], 'market': row['market'],
            'market_cap': row['market_cap'], 'universe_rank': row['rank'], 'score': 0.,
            'research_status': 'insufficient', 'reasons': [], 'reference_session': None,
            'current_close': None, 'train': None, 'validation': None,
            'kelly': {'empirical_fraction': None, 'half_fraction': None, 'capped_fraction': None,
                      'research_weight': 0., 'approved_weight': None, 'volatility_guard': False,
                      'portfolio_scale': 1.},
            'chart': {'query': [], 'cases': [],
                      'future_basis': 'next_observation_close_entry_then_20_sessions'}}


def _report(cutoff):
    return {'schema_version': 1, 'policy_id': POLICY_ID, 'mode': 'research', 'status': 'blocked',
            'as_of': _iso(cutoff), 'generated_at': _iso(datetime.now(timezone.utc)), 'source': {},
            'universe': {'ranked': 0, 'quality_passed': 0, 'processed': 0, 'valid': 0, 'stable': 0,
                         'rejected': {}, 'as_of': None, 'reference_symbols': 0},
            'policy': dict(POLICY), 'candidates': [], 'leaderboard': [], 'warnings': list(WARNINGS),
            'approval': {'status': 'held', 'reasons': WARNINGS[:2], 'approved_exposure': 0.},
            'portfolio': {'research_exposure': 0., 'research_cash': 1.},
            '_audit': {'cohorts': {}, 'bank_rejections': {}, 'source_fingerprint': None}}


def _metric(rows):
    if not rows:
        return None
    returns = [row['net_return'] for row in rows]
    n = len(returns)
    wins = [value for value in returns if value > 0]
    losses = [-value for value in returns if value < 0]
    p, z = len(wins) / n, POLICY['confidence_z']
    denominator = 1 + z*z/n
    lower = (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))) / denominator
    payoff = statistics.fmean(wins)/statistics.fmean(losses) if wins and losses else None
    p10, median, p90 = np.quantile(returns, [.1, .5, .9])
    return {'sample_count': n, 'distinct_symbols': len({row['symbol'] for row in rows}),
            'period_start': min(row['start_date'] for row in rows),
            'period_end': max(row['exit_date'] for row in rows),
            'net_win_rate_pct': round(p*100, 8), 'wilson_lower_pct': round(max(0., lower)*100, 8),
            'payoff_ratio': round(payoff, 8) if payoff is not None else None,
            'expectancy_pct': round(statistics.fmean(returns)*100, 8),
            'median_pct': round(float(median)*100, 8), 'p10_pct': round(float(p10)*100, 8),
            'p90_pct': round(float(p90)*100, 8),
            'median_similarity': round(statistics.median(row['similarity'] for row in rows), 8)}


def _gate(metric, group):
    reasons = []
    if metric is None or metric['sample_count'] < POLICY['min_samples']:
        reasons.append(group+'_too_few_samples')
    if metric is None:
        return reasons
    if metric['net_win_rate_pct'] < 60:
        reasons.append(group+'_win_rate_below_60')
    if metric['wilson_lower_pct'] < 60:
        reasons.append(group+'_wilson_below_60')
    if metric['payoff_ratio'] is None:
        reasons.extend([group+'_payoff_unavailable', 'payoff_unavailable'])
    elif metric['payoff_ratio'] < 1:
        reasons.append(group+'_payoff_below_one')
    if metric['expectancy_pct'] <= 0:
        reasons.append(group+'_nonpositive_net_expectancy')
    return reasons


def _normalized(values, count=64, base=None):
    base = float(values[-1]) if base is None else base
    interpolated = np.interp(np.linspace(0, len(values)-1, count), np.arange(len(values)), values)
    result = [round(float(value/base*100), 6) for value in interpolated]
    if not all(math.isfinite(value) for value in result):
        raise ValueError('nonfinite_chart')
    return result


def _kelly(validation, volatility):
    result = {'empirical_fraction': None, 'half_fraction': None, 'capped_fraction': None,
              'research_weight': 0., 'approved_weight': None,
              'volatility_guard': volatility > POLICY['volatility_threshold'], 'portfolio_scale': 1.}
    if len(validation) >= POLICY['min_samples']:
        raw = empirical_kelly([case['net_return'] for case in validation])
        half = raw*POLICY['kelly_fraction']
        capped = min(POLICY['max_weight'], half) * (.5 if result['volatility_guard'] else 1.)
        result.update(empirical_fraction=raw, half_fraction=half, capped_fraction=capped)
    return result


def _clean(data, start, finish, cutoff_us):
    closes, days, captures = (data[key][start:finish+1] for key in ('closes', 'dates', 'captures_actual_us'))
    return bool(engine._valid_span(closes, days)
                and np.all((days+3) % 7 < 5)
                and np.all(captures >= days.astype(np.int64)*DAY_US+CLOSE_UTC_US)
                and np.all(captures <= cutoff_us))


def _bank(data, owners, cutoff_us):
    records, features, rejected = [], [], Counter()
    for candidate in np.flatnonzero(np.isin(data['candidate_symbols'], owners)):
        owner, anchor = int(data['candidate_symbols'][candidate]), int(data['candidate_ends'][candidate])
        start, entry, exit_at = anchor-engine.LOOKBACK+1, anchor+1, anchor+1+POLICY['horizon_sessions']
        begin, finish = int(data['offsets'][owner]), int(data['offsets'][owner+1])
        if start < begin or exit_at >= finish:
            rejected['cross_partition'] += 1
            continue
        if not _clean(data, start, exit_at, cutoff_us):
            rejected['invalid_or_future_case'] += 1
            continue
        entry_close, exit_close = float(data['closes'][entry]), float(data['closes'][exit_at])
        net = exit_close/entry_close-1-POLICY['cost_bps']/10000
        if not math.isfinite(net) or net <= -1:
            rejected['invalid_net_return'] += 1
            continue
        records.append({'owner': owner, 'start': start, 'anchor': anchor, 'entry': entry, 'exit': exit_at})
        features.append(engine._feature(data['closes'][start:anchor+1]))
    return records, np.array(features, dtype=np.float32).reshape(-1, 34), dict(rejected)


def _case(data, record, similarity):
    owner, start, anchor, entry, exit_at = (record[key] for key in ('owner', 'start', 'anchor', 'entry', 'exit'))
    entry_close, exit_close = float(data['closes'][entry]), float(data['closes'][exit_at])
    gross = exit_close/entry_close-1
    return {'symbol': str(data['symbols'][owner]), 'target': str(data['names'][owner]),
            'start_date': engine._date(data['dates'][start]), 'anchor_date': engine._date(data['dates'][anchor]),
            'entry_date': engine._date(data['dates'][entry]), 'exit_date': engine._date(data['dates'][exit_at]),
            'captured_at': engine._iso_us(data['captures_actual_us'][start:exit_at+1].max()),
            'similarity': round(similarity, 8), 'gross_return_pct': gross*100,
            'net_return_pct': (gross-POLICY['cost_bps']/10000)*100,
            'net_return': gross-POLICY['cost_bps']/10000,
            'entry_close': entry_close, 'exit_close': exit_close}


def _select(data, records, features, feature, owner, query_start, split):
    if not len(records):
        return [], [], []
    distances = np.mean((features-feature)**2, axis=1)
    order = sorted(range(len(records)), key=lambda i: (float(distances[i]),
                   int(data['dates'][records[i]['anchor']]), str(data['symbols'][records[i]['owner']])))
    groups, occupied, retained = {'train': [], 'validation': []}, {}, []
    for i in order:
        record = records[i]
        similarity = 1/(1+float(distances[i]))
        if similarity < POLICY['min_similarity']:
            break
        if record['owner'] == owner and record['exit'] >= query_start:
            continue
        group = ('train' if int(data['dates'][record['exit']]) < split else
                 'validation' if int(data['dates'][record['start']]) >= split else None)
        if group is None or len(groups[group]) >= POLICY['max_group_samples']:
            continue
        interval = (record['start'], record['exit'])
        if any(interval[0] <= previous[1] and previous[0] <= interval[1]
               for previous in occupied.get(record['owner'], [])):
            continue
        occupied.setdefault(record['owner'], []).append(interval)
        row = _case(data, record, similarity)
        groups[group].append(row)
        retained.append((record, row))
    return groups['train'], groups['validation'], retained


def _query(data, owner, source, cutoff_us):
    begin, finish = int(data['offsets'][owner]), int(data['offsets'][owner+1])
    # The frozen newest source session cannot silently fall back to yesterday.
    eligible = np.flatnonzero(data['dates'][begin:finish] == (date.fromisoformat(source['latest_session'])-engine.EPOCH).days)
    if not len(eligible):
        return None, 'old_target_session'
    end = begin+int(eligible[-1])
    start = end-engine.LOOKBACK+1
    if int(data['captures_actual_us'][end]) > cutoff_us:
        return None, 'future_query_capture'
    if start < begin or not _clean(data, start, end, cutoff_us):
        return None, 'insufficient_history'
    if str(data['collection_statuses'][owner]) == 'cache_preserved':
        return None, 'cached_target'
    return (start, end), None


def _fingerprint(data, owners):
    digest = hashlib.sha256(json.dumps(data['metadata'], sort_keys=True, ensure_ascii=False,
                                      allow_nan=False, separators=(',', ':')).encode())
    for owner in owners:
        digest.update(str(data['symbols'][owner]).encode())
        begin, finish = int(data['offsets'][owner]), int(data['offsets'][owner+1])
        for key in ('dates', 'closes', 'captures_actual_us'):
            digest.update(data[key][begin:finish].tobytes())
    return digest.hexdigest()


def _portfolio(rows):
    selected = {row['symbol'] for row in [row for row in rows if row['chart']['cases'] and row['score'] > 0][:POLICY['max_positions']]}
    for row in rows:
        row['kelly']['research_weight'] = (row['kelly']['capped_fraction'] or 0.) if (
            row['research_status'] == 'stable' and row['symbol'] in selected) else 0.
    total = sum(row['kelly']['research_weight'] for row in rows)
    scale = min(1., min(POLICY['max_exposure'], 1-POLICY['min_cash'])/total) if total > 0 else 1.
    for row in rows:
        row['kelly']['portfolio_scale'] = scale
        row['kelly']['research_weight'] *= scale
    exposure = sum(row['kelly']['research_weight'] for row in rows)
    return {'research_exposure': exposure, 'research_cash': 1-exposure}


def scan(universe: dict, *, as_of=None, index_root=None, progress=None) -> dict:
    """Inspect only passed large-cap targets/references, with no API or orders."""
    cutoff = engine._cutoff(as_of)
    report = _report(cutoff)
    try:
        ranked, passed, scope_day = _scope(universe, cutoff)
    except (ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, ValueError) else 'invalid_universe'
        report['warnings'].append(reason)
        return report
    report['universe'].update(ranked=len(ranked), quality_passed=len(passed), as_of=scope_day)
    report['leaderboard'] = [_empty(row) for row in passed]
    if not passed:
        report['warnings'].append('no_quality_symbols')
        return report
    data, error = engine._load(full=True, index_root=index_root)
    if error:
        report['warnings'].append(error)
        for row in report['leaderboard']:
            row['reasons'].append(error)
        return report
    source = copy.deepcopy(data['metadata']['source'])
    report['source'] = source
    try:
        if source.get('price_basis') != 'provider_adjusted':
            raise ValueError('unadjusted_index')
        if engine._cutoff(source['captured_at']) > cutoff:
            raise ValueError('future_index_capture')
        latest = date.fromisoformat(source['latest_session'])
        if latest > cutoff.astimezone(engine.KST).date():
            raise ValueError('future_index_session')
        if engine._freshness(source, cutoff) > engine.STALE_DAYS:
            raise ValueError('stale_data')
        owners = [int(np.searchsorted(data['symbols'], row['symbol'])) for row in passed]
        owners = sorted({owner for owner, row in zip(owners, passed)
                         if owner < len(data['symbols']) and str(data['symbols'][owner]) == row['symbol']})
        cutoff_us = _timestamp_us(cutoff)
        calendar = np.unique(np.concatenate([data['dates'][int(data['offsets'][owner]):int(data['offsets'][owner+1])]
                        for owner in owners])) if owners else np.empty(0, dtype=np.int32)
        calendar = calendar[calendar <= (cutoff.astimezone(engine.KST).date()-engine.EPOCH).days]
        if not len(calendar):
            raise ValueError('insufficient_reference_calendar')
        # Predeclared 60% of observed session dates; never inspect outcomes or
        # optimise the split to improve a score. Purging spans the full input.
        split = int(calendar[min(len(calendar)-1, int(len(calendar)*POLICY['split_fraction']))])
        records, features, bank_rejections = _bank(data, owners, cutoff_us)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        reason = str(error) if isinstance(error, ValueError) else 'invalid_index'
        report['warnings'].append(reason)
        for row in report['leaderboard']:
            row['reasons'].append(reason)
        return report
    report['source'].update(split_date=engine._date(split),
                            validation_design='purged_retrospective_snapshot_stability',
                            query_lookback_sessions=engine.LOOKBACK)
    report['universe']['reference_symbols'] = len(owners)
    report['_audit'].update(source_fingerprint=_fingerprint(data, owners), bank_rejections=bank_rejections)
    rejected = Counter()
    if progress:
        progress(0, len(passed))
    for row in report['leaderboard']:
        owner = int(np.searchsorted(data['symbols'], row['symbol']))
        issue = 'symbol_missing' if owner >= len(data['symbols']) or str(data['symbols'][owner]) != row['symbol'] else None
        query, query_issue = _query(data, owner, source, cutoff_us) if issue is None else (None, issue)
        if query is None:
            row['reasons'].append(query_issue)
            rejected[query_issue] += 1
        else:
            start, end = query
            query_closes = data['closes'][start:end+1]
            row.update(reference_session=engine._date(data['dates'][end]), current_close=float(query_closes[-1]))
            row['chart']['query'] = _normalized(query_closes)
            train, validation, retained = _select(data, records, features, engine._feature(query_closes), owner, start, split)
            row.update(train=_metric(train), validation=_metric(validation))
            row['reasons'] = list(dict.fromkeys(_gate(row['train'], 'train')+_gate(row['validation'], 'validation')))
            row['research_status'] = ('stable' if not row['reasons'] else
                                      'insufficient' if any('too_few_samples' in reason for reason in row['reasons']) else 'watch')
            if retained:
                report['universe']['valid'] += 1
                # Selection uses shape only; score uses observed costed outcome
                # and explicitly penalises the lower tail for WATCH ordering.
                metric = row['validation'] or row['train']
                row['score'] = round(metric['expectancy_pct']+.5*metric['p10_pct'], 8)
                if row['score'] <= 0:
                    row['reasons'].append('nonpositive_watch_score')
                for record, case in sorted(retained, key=lambda item: (-item[1]['similarity'], item[1]['anchor_date'], item[1]['symbol']))[:3]:
                    shown = {key: value for key, value in case.items() if key not in {'net_return', 'start_date'}}
                    shown.update(input=_normalized(data['closes'][record['start']:record['anchor']+1]),
                                 future=_normalized(data['closes'][record['entry']:record['exit']+1], count=21,
                                                    base=float(data['closes'][record['anchor']])))
                    row['chart']['cases'].append(shown)
            else:
                row['reasons'].append('no_similar_cases')
            volatility = float(np.std(np.diff(query_closes)/query_closes[:-1]))
            row['current_volatility'] = volatility
            row['kelly'] = _kelly(validation, volatility)
            report['_audit']['cohorts'][row['symbol']] = {'train': train, 'validation': validation,
                                                        'query_start_date': engine._date(data['dates'][start])}
            if row['research_status'] == 'stable':
                report['universe']['stable'] += 1
            for reason in row['reasons']:
                rejected[reason] += 1
        report['universe']['processed'] += 1
        if progress:
            progress(report['universe']['processed'], len(passed))
    report['leaderboard'].sort(key=lambda row: (0 if row['research_status'] == 'stable' else 1,
              0 if row['chart']['cases'] else 1, -row['score'],
              -(row['validation'] or row['train'] or {}).get('median_similarity', 0), row['universe_rank'], row['symbol']))
    for rank, row in enumerate(report['leaderboard'], 1):
        row['rank'] = rank
    report['portfolio'] = _portfolio(report['leaderboard'])
    shortlisted = [row for row in report['leaderboard'] if row['chart']['cases'] and row['score'] > 0][:POLICY['max_positions']]
    report['candidates'] = [dict(row, rank=rank) for rank, row in enumerate(shortlisted, 1)]
    report['universe']['rejected'] = dict(rejected)
    report['status'] = 'ready'
    # Final JSON finiteness check includes the full audit; no NaN can silently
    # become a WATCH metric, reference chart, Kelly fraction or API response.
    json.dumps(report, ensure_ascii=False, allow_nan=False)
    return report
