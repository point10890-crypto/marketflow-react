"""Read-only research view of the latest sealed Candidate Desk.

The desk's costed contextual rank is authoritative. The legacy compatibility
path uses a separate research ordering:

Score = 70 * saved-metric percentile + 20 * saved leadership-check fraction
      + 5 * verified filing availability + 5 * verified price availability.
Percentiles compare only rows with the SAME metric (score, ranking.score, or
trend_quality); ties use midranks and a singleton is .5. This is a transparent
research ordering of a small selected sample, never a payoff probability.
Evidence points measure completeness, not positive sentiment. News counts and
negative/unverified news add NO points. No entry, plan, Kelly, or approval is
recomputed. Poll clocks do not alter the substantive content fingerprint.

The saved-evidence module's private _article_input/_source helpers are reused
for its bounded, validated source representation, with stricter per-symbol
citation permissions here. Only independent marketflow_rss ingestion is used.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path
import re
import sqlite3

from app.services import evidence_review as evidence
from . import candidate_store, decision_engine, opportunity_store, store
from .desk_selection import directory as select_desk_directory


POLICY_VERSION = 'top3-advisor-input-v1'
MAX_CANDIDATES = 6
MAX_SOURCES = 80
MAX_AGE = timedelta(hours=72)
DESK_BASES = ('candidate-regular-v1', 'candidate-desk')
REGULAR_PRICE_BASIS = 'KRX_regular_0900_1530_OHLC'
REGULAR_ACQUISITION_POLICY = 'krx-regular-ohlc-v1'
METRIC_KEYS = ('score', 'ranking.score', 'trend_quality')
ORIGINAL_KEYS = ('symbol', 'name', 'market', 'rank', 'strategy_id', 'score', 'plan', 'ranking',
    'risk', 'kelly', 'reference_weight', 'reasons', 'hold_reasons', 'entry_status', 'entry_eligible',
    'status', 'setup_active', 'reference_price', 'last_close', 'source_at', 'checks', 'points',
    'available_checks', 'trend_quality', 'ret_21', 'ret_63', 'from_high_252', 'why_stock',
    'audit', 'risk_flags', 'signals')


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) else None


def _identity(row, *, max_name=100):
    symbol, name, market = row.get('symbol'), row.get('name'), row.get('market', 'KR')
    if (not isinstance(symbol, str) or not re.fullmatch(r'[0-9A-Z]{6}', symbol) or symbol == '000000'
            or not isinstance(name, str) or not 1 <= len(name) <= max_name or not name.isprintable()
            or market != 'KR'):
        raise ValueError('invalid_candidate_identity')
    return symbol, name, market


def _reasons(*rows):
    result = []
    for row in rows:
        for key in ('reasons', 'hold_reasons'):
            values = row.get(key, [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError('invalid_hold_reasons')
            for value in values:
                if not isinstance(value, str) or len(value) > 300:
                    raise ValueError('invalid_hold_reasons')
                if value not in result:
                    result.append(value)
    return result


def _finish(result, *, binding=None, pool=None):
    stable = {key: value for key, value in result.items() if key not in ('fingerprint', 'source_cutoff_at')}
    # Source capture refreshes have no billing meaning when the source content,
    # verification, identity, and original-decision availability are unchanged.
    stable['sources'] = [{key: value for key, value in row.items() if key != 'fetched_at'}
                         for row in result['sources']]
    result['fingerprint'] = evidence._hash(dict(policy=POLICY_VERSION, input=stable,
        original_binding=binding, candidate_pool=pool))
    return result


def _empty(current, status='missing', reason='no_current_candidates', **identity):
    return _finish(dict(targets=[], sources=[], candidates=[], coverage=dict(inspected=0, pool=0,
        shortlisted=0, with_recent_news=0, with_verified_filings=0, with_verified_prices=0, source_count=0),
        warnings=[reason], **{'decision_id': None, 'source_input_fingerprint': None, 'source_origin_at': None, **identity},
        source_cutoff_at=evidence._stamp(current), status=status))


def _decision(alpha_root, current):
    saved = store.read_status(alpha_root, now=evidence._stamp(current))
    if saved.get('state') == 'missing':
        return None
    report = saved.get('report')
    if (saved.get('state') not in ('ready', 'held') or not isinstance(report, dict)
            or report.get('schema_version') != 1 or report.get('mode') != 'research'):
        raise ValueError('saved_decision_unavailable')
    board = report.get('opportunity_board')
    binding = opportunity_store._binding(board)
    if report.get('input_fingerprint') != binding['input_fingerprint']:
        raise ValueError('report_binding_mismatch')
    scan = report.get('opportunity_scan') or {}
    audits = [value for value in (report.get('source_audit_hash'), scan.get('audit_hash')) if value is not None]
    if not audits or any(value != binding['source_audit_hash'] for value in audits):
        raise ValueError('report_binding_mismatch')
    if (report.get('latest_session') != board.get('latest_session')
            or (scan and scan.get('latest_session') != board.get('latest_session'))):
        raise ValueError('report_session_mismatch')
    if decision_engine._stable_identity(binding['input_fingerprint'], binding['source_audit_hash'],
            board.get('latest_session'), board['candidates'], policy=board['policy_version']) != board['decision_id']:
        raise ValueError('board_content_binding_mismatch')
    report_at = evidence._clock(report['decision_at'])
    board_at = evidence._clock(board['generated_at'])
    board_origin = evidence._clock(board.get('origin_at') or board['generated_at'])
    if max(report_at, board_at, board_origin, evidence._clock(saved['generated_at'])) > current:
        raise ValueError('future_decision')
    issued = board
    # Even a held report must not hide a recovered/corrupt issued journal.
    journal, recovered = opportunity_store._journal(alpha_root)
    if recovered:
        raise ValueError('opportunity_store_recovered')
    matching = next((row['board'] for row in journal['issued'] if row['decision_id'] == board['decision_id']), None)
    if board['candidates'] or matching is not None:
        if matching is None or opportunity_store._stable(matching) != opportunity_store._stable(board):
            raise ValueError('unsealed_opportunity_board')
        issued = matching
    issued_at = evidence._clock(issued['generated_at'])
    issued_origin = evidence._clock(issued.get('origin_at') or issued['generated_at'])
    if max(issued_at, issued_origin) > current:
        raise ValueError('future_decision')
    origin = min(report_at, issued_origin)
    latest = date.fromisoformat(board['latest_session'])
    if latest > min(origin.astimezone(evidence.articles.KST).date(), current.astimezone(evidence.articles.KST).date()):
        raise ValueError('future_decision_session')
    contexts = [ctx for ctx in (board.get('leadership_context'), report.get('leadership_context')) if ctx is not None]
    for ctx in contexts:
        if (not isinstance(ctx, dict) or any(ctx.get(key) != binding[key] for key in ('input_fingerprint', 'source_audit_hash'))
                or ctx.get('latest_session') != board.get('latest_session')):
            raise ValueError('leadership_binding_mismatch')
    if len(contexts) == 2 and contexts[0] != contexts[1]:
        raise ValueError('leadership_binding_mismatch')
    return saved, report, board, issued, (contexts[0] if contexts else {}), origin


def _pool(report, board, issued, leadership, origin):
    by_symbol = {}
    groups = [('issued_opportunities', issued['candidates']), ('research_watchlist', report.get('candidates', [])),
              ('leadership_watchlist', leadership.get('watchlist', []))]
    for basis, rows in groups:
        if not isinstance(rows, list) or len(rows) > 64:
            raise ValueError('candidate_pool_capacity')
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('invalid_candidate_identity')
            symbol, name, market = _identity(row)
            captured = row.get('source_at') or (report.get('provenance') or {}).get('captured_at')
            if not captured or evidence._clock(captured) > origin:
                raise ValueError('source_after_original_decision')
            facts = {key: deepcopy(row[key]) for key in ORIGINAL_KEYS if key in row}
            if len(evidence._encode(facts)) > 24000:
                raise ValueError('candidate_source_capacity')
            existing = by_symbol.get(symbol)
            if existing and (existing['name'], existing['market']) != (name, market):
                raise ValueError('conflicting_candidate_identity')
            if existing is None:
                risk = row.get('risk') or {}
                if not isinstance(risk, dict):
                    raise ValueError('invalid_candidate_risk')
                reasons = _reasons(board, row, risk)
                original_status = row.get('entry_status') or risk.get('status') or board.get('status') or 'held'
                entry_status = str(original_status)
                if basis != 'issued_opportunities' or board.get('status') != 'ready' or row.get('entry_eligible') is False:
                    entry_status = 'held'
                if basis == 'leadership_watchlist':
                    reasons.append('leadership_watchlist_not_entry_approval')
                plan = deepcopy(row.get('plan'))
                if plan is not None and not isinstance(plan, dict):
                    raise ValueError('invalid_original_plan')
                reference = next((value for value in (row.get('reference_price'), row.get('last_close'),
                    (plan or {}).get('entry_price')) if _number(value) is not None and value > 0), None)
                existing = dict(symbol=symbol, name=name, market=market, basis=basis, entry_status=entry_status,
                    hold_reasons=reasons, plan=plan, reference_price=reference, source_at=evidence._stamp(captured),
                    original_sources={}, leadership={})
                by_symbol[symbol] = existing
            existing['original_sources'][basis] = facts
            if basis == 'leadership_watchlist':
                existing['leadership'] = facts
    return sorted(by_symbol.values(), key=lambda row: row['symbol'])


def _articles(article_root, current, symbols, warnings):
    """Use only saved snapshots and read-only verification transactions."""
    path = Path(article_root)/'snapshot.json'
    if not path.is_file():
        warnings.append('article_source_unavailable')
        return []
    try:
        if path.stat().st_size > store.MAX_BYTES:
            raise ValueError('article_source_capacity')
        raw = evidence.articles._read(Path(article_root))
        rows = raw['items']
        if not isinstance(rows, list) or len(rows) > evidence.articles.MAX_CANDIDATES:
            raise ValueError('article_source_capacity')
    except (OSError, ValueError, KeyError, TypeError):
        warnings.append('article_source_unavailable')
        return []
    try:
        verified = evidence.verification.read_dashboard(article_root, now=current)['items']
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        verified = []
        warnings.append('verification_source_unavailable')
    items = []
    for row in rows:
        try:
            if row.get('withdrawn') or row.get('provenance') != 'marketflow_rss':
                continue
            if not any(entity.get('symbol') in symbols for entity in row['entities']):
                continue
            published = evidence._clock(row['published_at'])
            if not timedelta(0) <= current-published <= MAX_AGE:
                continue
            if (not isinstance(row.get('id'), str) or not re.fullmatch(r'\d{1,20}', row['id'])
                    or not isinstance(row.get('title'), str) or not 1 <= len(row['title']) <= 1200):
                continue
            item = evidence._article_input(row, verified, current)
            if item:
                item['event_type'] = (row.get('event') or {}).get('type')
                receipt = max(published, evidence._clock(row['first_seen_at']))
                for source in item['sources']:
                    if source['source'] != 'KIS_saved_post_receipt_prices' or source['verification_status'] != 'verified':
                        continue
                    price = json.loads(source['text'])
                    observed, latest = (evidence._clock(price[key]) for key in ('observed_at','latest_observed_at'))
                    if observed < receipt or current-latest > MAX_AGE:
                        source.update(text=evidence._encode(dict(status='unavailable', reason='post_receipt_price_window_invalid')),
                            fetched_at=None, verification_status='unavailable')
                        warnings.append('post_receipt_price_window_invalid')
                items.append(item)
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError):
            warnings.append('invalid_article_evidence_excluded')
    return sorted(items, key=lambda item: (item['source_origin_at'], item['article_id']), reverse=True)


def _source(identifier, content, symbol, origin, *, source='AlphaLab_saved_evidence_availability', fetched=None):
    row = evidence._source(identifier, evidence._encode(content), title=f'{symbol} 저장된 근거 상태',
        source=source, fetched=fetched, status='research_not_independent_validation' if source.startswith('AlphaLab_sealed') else 'unavailable')
    row['target_symbols'] = [symbol]
    row['available_at_original_decision'] = bool(fetched and evidence._clock(fetched) <= origin)
    return row


def _sources(row, articles, origin):
    symbol = row['symbol']
    related = [item for item in articles if any(t['symbol'] == symbol for t in item['targets'])][:2]
    result = [_source(f'candidate:{symbol}', row['original_sources'], symbol, origin,
        source='AlphaLab_sealed_candidate_desk' if row['basis'] in DESK_BASES else 'AlphaLab_sealed_current_report',
        fetched=row['source_at'])]
    for item in related:
        identifier = item['article_id']
        for source in item['sources']:
            key = source['evidence_id']
            if (key.startswith(f'article:{identifier}') or key in (f'price:{identifier}:{symbol}', f'verification:{identifier}:{symbol}')
                    or key.startswith(f'filing:{symbol}:')):
                source = deepcopy(source)
                if key.startswith(f'filing:{symbol}:'):
                    # A filing can be checked against different article claims;
                    # keep both comparisons and their capture clocks distinct.
                    source['evidence_id'] = f'filing:{identifier}:{key[len("filing:"):]}'
                source['target_symbols'] = [symbol]
                source['available_at_original_decision'] = bool(source.get('fetched_at')
                    and evidence._clock(source['fetched_at']) <= origin)
                result.append(source)
        if not any(s['evidence_id'] == f'verification:{identifier}:{symbol}' for s in result):
            result.append(_source(f'verification:{identifier}:{symbol}',
                dict(status='unavailable', reason='official_verification_unavailable'), symbol, origin))
    if not related:
        result.extend([
            _source(f'news_status:{symbol}', dict(status='unavailable', reason='no_recent_articles'), symbol, origin),
            _source(f'verification_status:{symbol}', dict(status='unavailable', reason='official_verification_unavailable'), symbol, origin),
            _source(f'price_status:{symbol}', dict(status='unavailable', reason='saved_price_evidence_missing'), symbol, origin),
        ])
    return result, related


def _verified_filing(source):
    if source['source'] != 'OpenDART_saved_verification' or source['verification_status'] != 'verified_numeric_claims':
        return False
    claims = json.loads(source['text']).get('claims')
    return bool(claims) and all(claim.get('verified') is True for claim in claims)


def _score(pool, articles, origin, *, sealed=False):
    for row in pool:
        facts = row['original_sources'][row['basis']]
        if sealed:
            row['metric'] = 'model_evidence.expected_stress_net_return'
            row['metric_value'] = facts['model_evidence']['expected_stress_net_return']
            continue
        metrics = {'score': facts.get('score'), 'ranking.score': (facts.get('ranking') or {}).get('score'),
                   'trend_quality': facts.get('trend_quality')}
        metric = next((key for key in METRIC_KEYS if _number(metrics[key]) is not None), 'none')
        row['metric'], row['metric_value'] = metric, metrics.get(metric)
    for row in pool:
        metric, value = row['metric'], row['metric_value']
        peers = [r['metric_value'] for r in pool if r['metric'] == metric] if not sealed and metric != 'none' else []
        percentile = (sum(v < value for v in peers)+.5*(sum(v == value for v in peers)-1))/(len(peers)-1) if len(peers)>1 else .5 if peers else 0
        checks = row['leadership'].get('checks') or {}
        fraction = sum(checks.get(key) is True for key in ('top3','fresh','trend','near_high'))/4
        sources, related = _sources(row, articles, origin)
        official = any(_verified_filing(source) for source in sources)
        prices = any(s['source'] == 'KIS_saved_post_receipt_prices' and s['verification_status']=='verified' for s in sources)
        completeness = 5*int(official)+5*int(prices)
        row['score_components'] = dict(saved_metric_name=metric, saved_metric_value=value,
            official_evidence_available=official, price_evidence_available=prices,
            news_count=len(related),
            unverified_news_count=len(related), negative_news_count=sum(item['event_type']=='risk' for item in related))
        if sealed:
            row['score'] = value
        else:
            row['score_components'].update(saved_metric_percentile=percentile, leadership_checks_fraction=fraction,
                                           evidence_completeness_score=completeness)
            row['score'] = round(70*percentile+20*fraction+completeness, 8)
        row['sources'] = sources
    return sorted(pool, key=lambda row: row['rank']) if sealed else sorted(
        pool, key=lambda row: (-row['score'], row['symbol'], row['name'], row['market']))


def _shortlist(pool, article_root, current, origin, identity, warnings, inspected, *, sealed=False, ready=False):
    articles = _articles(article_root, current, {row['symbol'] for row in pool}, warnings)
    shortlisted = _score(pool, articles, origin, sealed=sealed)[:MAX_CANDIDATES]
    sources = {}
    all_sources = [s for row in shortlisted for s in row['sources']]
    # Retain one verified filing per covered symbol before optional filings.
    required_filings = {next((s['evidence_id'] for s in row['sources'] if _verified_filing(s)), None)
                        for row in shortlisted}
    for source in sorted(all_sources, key=lambda s: (s['evidence_id'].startswith('filing:'),
            s['evidence_id'] not in required_filings, s['evidence_id'])):
        key = source['evidence_id']
        if key in sources:
            previous = sources[key]
            if {k:v for k,v in previous.items() if k!='target_symbols'} != {k:v for k,v in source.items() if k!='target_symbols'}:
                raise ValueError('conflicting_evidence_identity')
            previous['target_symbols'] = sorted(set(previous['target_symbols']+source['target_symbols']))
        elif len(sources) < MAX_SOURCES:
            sources[key] = deepcopy(source)
        else:
            warnings.append('source_capacity_truncated')
    candidates = []
    for rank, row in enumerate(shortlisted, 1):
        candidate = {key: deepcopy(row[key]) for key in ('symbol', 'name', 'market', 'score', 'score_components',
            'basis', 'entry_status', 'hold_reasons', 'plan', 'source_at', 'reference_price')}
        if sealed:
            candidate['risk'] = deepcopy(row['risk'])
        candidate.update(rank=row['rank'] if sealed else rank,
            evidence_ids=sorted(key for key, source in sources.items() if row['symbol'] in source['target_symbols']))
        candidates.append(candidate)
    if any(not r['score_components']['news_count'] for r in candidates):
        warnings.append('recent_independent_news_missing')
    if sealed and any(not r['score_components']['official_evidence_available'] for r in candidates):
        warnings.append('recent_official_filing_verification_missing')
    return dict(**identity, source_cutoff_at=evidence._stamp(current), candidates=candidates,
        targets=[{key:r[key] for key in ('symbol','name','market')} for r in candidates],
        sources=sorted(sources.values(), key=lambda s:s['evidence_id']), warnings=sorted(set(warnings)),
        status='ready' if ready and all(r['entry_status']=='ready' for r in candidates) else 'held',
        coverage=dict(inspected=inspected, pool=len(pool), shortlisted=len(candidates), source_count=len(sources),
            with_recent_news=sum(r['score_components']['news_count']>0 for r in candidates),
            with_verified_filings=sum(r['score_components']['official_evidence_available'] for r in candidates),
            with_verified_prices=sum(r['score_components']['price_evidence_available'] for r in candidates)))


def _desk_input(directory, article_root, current):
    identity = dict(source_basis=directory.name)
    try:
        attempt = candidate_store._load(directory/'attempt.json') or {}
        if attempt and (attempt['state'] != 'complete' or evidence._clock(attempt['at']) > current):
            return _empty(current, 'unavailable', 'candidate_desk_refresh_unavailable', **identity)
        records = candidate_store.read_decisions(directory)['records']
        if not records:
            raise ValueError('missing_candidate_journal')
        record = max(records, key=lambda item: item['desk']['latest_session'])
        desk = candidate_store.read_public(directory, now=evidence._stamp(current))
        if desk is None or desk['decision_id'] != record['desk']['decision_id']:
            raise ValueError('candidate_current_pointer_mismatch')
        source = desk['source']
        regular = directory.name == DESK_BASES[0]
        if (desk['policy_version'] != candidate_store.POLICY or source['provider'] != 'KIS'
                or source['venue'] != 'KRX' or source['adjusted_requested'] is not True
                or desk['approved_exposure'] != 0 or desk['live_orders'] is not False):
            raise ValueError('invalid_candidate_desk_policy')
        if regular and (source.get('regular_session_verified') is not True
                or source.get('price_basis') != REGULAR_PRICE_BASIS
                or source.get('acquisition_policy') != REGULAR_ACQUISITION_POLICY):
            raise ValueError('regular_session_evidence_missing')
        origin = evidence._clock(desk['generated_at'])
        captured = evidence._clock(source['captured_at'])
        session = desk['latest_session']
        session_close = datetime.combine(date.fromisoformat(session), time(15, 30), candidate_store.KST)
        if not session_close <= captured <= origin <= current or evidence._clock(record['created_at']) != origin:
            raise ValueError('candidate_source_clock_mismatch')
        identity.update(decision_id=desk['decision_id'], source_input_fingerprint=desk['input_fingerprint'],
            source_origin_at=evidence._stamp(origin), source_session=session,
            source_price_basis=source['price_basis'] if regular else 'KIS:J:D:adjusted_requested',
            source_policy=source['acquisition_policy'] if regular else desk['policy_version'])
        if desk['state'] in ('failed', 'running') or 'source_revision' in desk['reasons']:
            return _empty(current, 'unavailable', 'candidate_desk_refresh_unavailable'
                if desk['state'] in ('failed', 'running') else 'source_revision', **identity)
        if current-session_close > MAX_AGE:
            return _empty(current, 'stale', 'candidate_price_session_older_than_72_hours', **identity)
        if 'entry_window_unavailable' in desk['reasons'] and desk['valid_until'] is not None:
            return _empty(current, 'stale', 'candidate_entry_window_expired', **identity)
        if not desk['candidates']:
            return _empty(current, 'missing', 'candidate_desk_cash', **identity)
        if desk['state'] != 'ready':
            return _empty(current, 'unavailable', 'candidate_desk_held', **identity)
        if (len(desk['candidates']) > 3
                or sorted(row['rank'] for row in desk['candidates']) != list(range(1, len(desk['candidates'])+1))):
            raise ValueError('invalid_candidate_ranks')
        pool, symbols = [], set()
        for row in desk['candidates']:
            symbol, name, market = _identity(row, max_name=120)
            if (not symbol.isascii() or not symbol.isdecimal() or symbol in symbols or row['quote_session'] != session
                    or row['risk']['approved_exposure'] != 0 or row['risk']['live_orders'] is not False
                    or _number(row['model_evidence']['expected_stress_net_return']) is None):
                raise ValueError('invalid_candidate_desk_row')
            symbols.add(symbol)
            facts = {key: deepcopy(row[key]) for key in ('symbol', 'name', 'rank', 'quote_session', 'strength_score',
                                                        'reason_facts', 'model_evidence', 'plan', 'risk')}
            facts.update(price_basis=identity['source_price_basis'], source_policy=identity['source_policy'])
            if len(evidence._encode(facts)) > 12000:
                raise ValueError('candidate_source_capacity')
            pool.append(dict(symbol=symbol, name=name, market=market, rank=row['rank'], basis=directory.name,
                entry_status='held', hold_reasons=[*_reasons(desk, row), 'candidate_desk_research_only'],
                reference_price=row['plan']['entry_price'], plan=row['plan'], risk=row['risk'],
                source_at=evidence._stamp(captured), original_sources={directory.name: facts}, leadership={}))
        inspected = next((row['count'] for row in desk['funnel'] if row['id']=='inspected'), len(pool))
        warnings = ['research_order_not_profit_probability', 'news_alone_never_approves_entry',
                    'experimental_context_model_not_holdout_validated']
        if not regular:
            warnings.append('legacy_daily_session_basis_unverified')
        if source.get('historical_vintage_verified') is not True:
            warnings.append('historical_vintage_unverified')
        if source.get('corporate_action_adjustment_verified') is not True:
            warnings.append('price_adjustment_unverified')
        result = _shortlist(pool, article_root, current, origin, identity, warnings, inspected, sealed=True)
        return _finish(result, binding=dict(policy=desk['policy_version'], source_contract_hash=record['source_contract_hash']))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return _empty(current, 'unavailable', 'candidate_source_unavailable', **identity)


def build_input(*, alpha_root, article_root, now=None):
    """Return the bounded spec contract. Empty statuses never contain current picks.

    ready/held carry a usable research shortlist; missing/unavailable/stale do
    not. Source text remains private untrusted data for the debate validator.
    This function performs no acquisition, inference, repair, or file writes.
    """
    current = evidence._clock(now)
    try:
        directory = select_desk_directory(alpha_root)
        if any((directory/name).exists() for name in ('current.json', 'attempt.json', 'decisions.json')):
            return _desk_input(directory, article_root, current)
        loaded = _decision(alpha_root, current)
        if loaded is None:
            return _empty(current)
        saved, report, board, issued, leadership, origin = loaded
        identity = dict(decision_id=board['decision_id'], source_input_fingerprint=board['input_fingerprint'],
                        source_origin_at=evidence._stamp(origin))
        if current-origin > MAX_AGE:
            return _empty(current, 'stale', 'decision_older_than_72_hours', **identity)
        pool = _pool(report, board, issued, leadership, origin)
        if not pool:
            return _empty(current, **identity)
        warnings = ['research_order_not_profit_probability', 'news_alone_never_approves_entry']
        provenance = report.get('provenance') or {}
        for flag, warning in (('price_adjustment_verified','price_adjustment_unverified'),
                ('historical_vintage_verified','historical_vintage_unverified'),
                ('point_in_time_universe_verified','point_in_time_universe_unverified'),
                ('analysis_ready','analysis_not_ready')):
            if provenance.get(flag) is False:
                warnings.append(warning)
        if provenance.get('current_cohort_bias') is True:
            warnings.append('current_cohort_bias')
        inspected = (board.get('coverage') or {}).get('inspected', (leadership.get('cohort') or {}).get('inspected', len(pool)))
        if type(inspected) is not int or inspected < 0:
            inspected = len(pool)
        result = _shortlist(pool, article_root, current, origin, identity, warnings, inspected,
                            ready=saved['state']=='ready')
        binding = dict(board={key:deepcopy(board.get(key)) for key in ('decision_id','input_fingerprint','source_audit_hash','policy_version','status','reasons')},
            provenance=deepcopy(report.get('provenance')), approval=deepcopy(report.get('approval')))
        pool_facts = [{key:row[key] for key in ('symbol','name','market','basis','entry_status','hold_reasons','original_sources')}
                      for row in sorted(pool,key=lambda row:row['symbol'])]
        return _finish(result, binding=binding, pool=pool_facts)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
        return _empty(current, 'unavailable', 'candidate_source_unavailable')
