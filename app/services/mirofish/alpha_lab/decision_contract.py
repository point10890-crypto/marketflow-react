"""Read-only source audit beside the existing frozen research stock desk.

These twelve roles are deterministic task contracts, never model calls. A
passed source audit says nothing about forward profit or independent strategy
validation. M0, unavailable probabilities and manual approval remain held.

``evidence`` is optional trusted server input, indexed by exact symbol. Each
record requires symbol, opportunity_id, role, claim_id, core (bool), kind
(market/disclosure/official_news/news/social), explicit source_grade (S/A/B/C),
lineage_id, origin_ids (explicit upstream IDs),
source, source_at, available_at, fetched_at, valid_until, status='ready' and
confidence (finite 0 < x <= 1). Timestamps must carry a timezone. Source,
availability and capture must precede the original decision cutoff. Websites
and record count never supply implicit independent origins. Overlapping origin
chains are one lineage. Required core claims are direction and risk, each with
at least two independent S/A market, disclosure or official-news lineages. B/C
and general news are supporting information. No collector, IO or fitting runs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re


POLICY_VERSION = 'evidence-account-v1'
CORE_CLAIMS = ('direction', 'risk')
SOURCE_ROLES = ('regime', 'fx_liquidity', 'flow', 'disclosure', 'sector', 'event', 'micro', 'sentiment')
ROLE_TITLES = {
    'regime': '시장 국면', 'fx_liquidity': '환율·유동성', 'flow': '외국인 수급',
    'disclosure': '공시·재무', 'sector': '업종', 'event': '일정·이벤트',
    'micro': '시세·진입 조건', 'sentiment': '뉴스·심리', 'auditor': '출처 감사',
    'leader': '판단 조정', 'risk_guard': '계좌 위험', 'review': '성과 검토',
}
# Expiry alone cannot make an old capture current. These are source-age ceilings,
# not promises that any provider or published claim meets the contract.
MAX_SOURCE_AGE = dict(regime=7*86400, fx_liquidity=86400, flow=86400,
    disclosure=90*86400, sector=7*86400, event=7*86400, micro=420, sentiment=86400)
MAX_RECORDS = 100
MAX_ORIGINS = 16
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def _timestamp(value):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if isinstance(value, datetime) and value.utcoffset() is not None:
            return value.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z') if value is not None else None


def _token(value):
    if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}', value):
        return value.lower()
    return None


def _hash_valid(value):
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _candidate_rows(board):
    """Only the existing projected board can supply identity, never a raw report."""
    candidates = board.get('candidates')
    if (type(board.get('schema_version')) is not int or board['schema_version'] != 1
            or board.get('policy_version') != 'profit-opportunity-v1'
            or not all(_hash_valid(board.get(key)) for key in
                       ('decision_id', 'input_fingerprint', 'source_audit_hash'))
            or not isinstance(candidates, list) or len(candidates) > 3):
        return []
    seen = set()
    for rank, row in enumerate(candidates, 1):
        if not isinstance(row, dict):
            return []
        symbol, strategy = row.get('symbol'), row.get('strategy_id')
        if (not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None
                or symbol == '000000' or symbol in seen or row.get('market') != 'KR'
                or strategy not in ('momentum', 'liquidity_breakout', 'mean_reversion')
                or type(row.get('rank')) is not int or row['rank'] != rank
                or not isinstance(row.get('name'), str) or not 1 <= len(row['name']) <= 200
                or re.search(r'[A-Za-z]:[\\/]', row['name'])
                or any(row.get(key) != board.get(key) for key in
                       ('decision_id', 'input_fingerprint', 'source_audit_hash'))):
            return []
        identity = dict(decision_id=board['decision_id'], symbol=symbol, strategy_id=strategy)
        expected = hashlib.sha256(json.dumps(identity, sort_keys=True,
            separators=(',', ':')).encode('utf-8')).hexdigest()
        if row.get('opportunity_id') != expected:
            return []
        seen.add(symbol)
    return candidates


def _record(raw, row, cutoff, current):
    """Reject absent metadata instead of inventing identity, freshness or lineage."""
    if not isinstance(raw, dict):
        return None, 'evidence_record_invalid'
    if raw.get('symbol') != row['symbol'] or raw.get('opportunity_id') != row['opportunity_id']:
        return None, 'evidence_identity_mismatch'
    role, kind, claim = raw.get('role'), raw.get('kind'), raw.get('claim_id')
    if not isinstance(role, str) or role not in SOURCE_ROLES:
        return None, 'evidence_role_invalid'
    if not isinstance(kind, str) or kind not in ('market', 'disclosure', 'official_news', 'news', 'social'):
        return None, 'evidence_kind_invalid'
    grade = raw.get('source_grade')
    if not isinstance(grade, str) or grade not in ('S', 'A', 'B', 'C'):
        return None, 'evidence_source_grade_invalid'
    if (not isinstance(claim, str) or re.fullmatch(r'[a-z][a-z0-9_]{0,63}', claim) is None
            or not isinstance(raw.get('core'), bool)
            or raw['core'] != (claim in CORE_CLAIMS)):
        return None, 'evidence_claim_invalid'
    lineage = _token(raw.get('lineage_id'))
    origins = raw.get('origin_ids')
    if (lineage is None or not isinstance(origins, list) or not 1 <= len(origins) <= MAX_ORIGINS
            or any(_token(origin) is None for origin in origins)):
        return None, 'evidence_lineage_missing'
    if not isinstance(raw.get('source'), str) or not 1 <= len(raw['source']) <= 300:
        return None, 'evidence_source_missing'
    if raw.get('status') != 'ready':
        return None, 'evidence_unavailable'
    confidence = _number(raw.get('confidence'))
    if confidence is None or not 0 < confidence <= 1:
        return None, 'evidence_confidence_invalid'
    published, available, fetched, expires = [
        _timestamp(raw.get(key)) for key in ('source_at', 'available_at', 'fetched_at', 'valid_until')]
    if None in (published, available, fetched, expires):
        return None, 'evidence_timestamp_invalid'
    if cutoff is None or cutoff > current:
        return None, 'evidence_cutoff_invalid'
    if any(moment > cutoff for moment in (published, available, fetched)):
        return None, 'evidence_after_decision'
    if not published <= available <= fetched < expires:
        return None, 'evidence_time_order_invalid'
    if current >= expires:
        return None, 'evidence_expired'
    if (current-published).total_seconds() >= MAX_SOURCE_AGE[role]:
        return None, 'evidence_stale'
    # Source labels and URLs are never substituted for explicitly supplied IDs.
    return dict(role=role, kind=kind, source_grade=grade, claim_id=claim, core=raw['core'],
        origins={lineage, *(_token(origin) for origin in origins)},
        fresh_until=min(expires, published+timedelta(seconds=MAX_SOURCE_AGE[role]))), None


def _core_usable(record):
    # A sentiment wrapper cannot disguise social/search interest as market data.
    return (record['core'] and record['source_grade'] in ('S', 'A')
            and record['kind'] in ('market', 'disclosure', 'official_news')
            and record['role'] != 'sentiment')


def _role_usable(record):
    role = record['role']
    if role in ('fx_liquidity', 'flow'):
        required = 'fx' if role == 'fx_liquidity' else 'foreign_flow'
        return (record['source_grade'] in ('S', 'A') and record['kind'] == 'market'
                and record['claim_id'] == required)
    return (record['source_grade'] in ('S', 'A')
            and record['kind'] in ('market', 'disclosure', 'official_news'))


def _components(records):
    """Count connected upstream origins, including transitive copied chains."""
    groups = []
    for record in records:
        origins = set(record['origins'])
        members = [record]
        remaining = []
        for group in groups:
            if origins & group['origins']:
                origins.update(group['origins'])
                members.extend(group['records'])
            else:
                remaining.append(group)
        # Updating a union can connect an earlier previously disjoint group.
        while True:
            matching = [group for group in remaining if origins & group['origins']]
            if not matching:
                break
            for group in matching:
                origins.update(group['origins']); members.extend(group['records'])
                remaining.remove(group)
        groups = [*remaining, dict(origins=origins, records=members)]
    return groups


def _entry(row, board, current):
    plan = _mapping(row.get('plan'))
    stop, low, high, target = [_number(plan.get(key)) for key in
                               ('stop_price', 'entry_low', 'entry_high', 'target_price')]
    until = _timestamp(row.get('valid_until'))
    board_until = _timestamp(board.get('valid_until'))
    invalidation = dict(price_below=stop if stop is not None and stop > 0 else None,
        price_above=high if high is not None and high > 0 else None,
        valid_until=_stamp(until),
        detail='진입 상한·손절·진입 창이 무효화 기준입니다. 갭 손실은 계획 손실보다 커질 수 있습니다.')
    reasons = []
    if None in (stop, low, high, target) or not 0 < stop < low <= high < target:
        reasons.append('plan_unavailable')
    if until is None or board_until is None or until != board_until:
        reasons.append('entry_window_unavailable')
    if until is not None and current >= until:
        reasons.append('entry_window_expired')
    if row.get('action') != 'entry_candidate' or board.get('status') != 'ready':
        reasons.append('entry_not_current')
    price = _number(row.get('current_price'))
    quote, fetched = _timestamp(row.get('quote_at')), _timestamp(row.get('fetched_at'))
    if (price is None or price <= 0 or quote is None or fetched is None
            or row.get('quote_source') != QUOTE_SOURCE):
        reasons.append('quote_unavailable')
    elif (not quote <= fetched <= current or (current-quote).total_seconds() >= 420
          or (current-fetched).total_seconds() >= 420 or (fetched-quote).total_seconds() > 120):
        reasons.append('quote_stale_or_future')
    elif None not in (stop, high, target) and not stop < price <= high < target:
        reasons.append('quote_outside_entry')
    if until is not None and quote is not None and fetched is not None and not any(
            reason in reasons for reason in ('quote_unavailable', 'quote_stale_or_future')):
        invalidation['valid_until'] = _stamp(min(until, quote+timedelta(seconds=420),
                                                    fetched+timedelta(seconds=420)))
    return invalidation, reasons


def _audit(row, board, raw_records, cutoff, current):
    records, reasons = [], []
    if raw_records is None:
        raw_records = []
    if not isinstance(raw_records, list):
        reasons.append('evidence_records_invalid'); raw_records = []
    elif len(raw_records) > MAX_RECORDS:
        reasons.append('evidence_records_limit'); raw_records = []
    for raw in raw_records:
        record, reason = _record(raw, row, cutoff, current)
        if reason:
            reasons.append(reason)
        else:
            records.append(record)
    groups = _components(records)
    independent = [group for group in groups if any(_core_usable(record) for record in group['records'])]
    for claim in CORE_CLAIMS:
        count = sum(any(record['claim_id'] == claim and _core_usable(record)
                        for record in group['records']) for group in groups)
        if count < 2:
            reasons.append(claim+'_independent_sources_missing')
    if (not independent and any(record['core'] and record['kind'] == 'social' for record in records)):
        reasons.append('social_only_core_claims')
    roles = {record['role'] for record in records if _role_usable(record)}
    if not {'fx_liquidity', 'flow'} & roles:
        reasons.append('fx_and_flow_missing')
    invalidation, entry_reasons = _entry(row, board, current)
    deadline = _timestamp(invalidation['valid_until'])
    if records and deadline is not None:
        invalidation['valid_until'] = _stamp(min(deadline, *(record['fresh_until'] for record in records)))
    reasons.extend(entry_reasons)
    if cutoff is None or cutoff > current:
        reasons.append('evidence_cutoff_invalid')
    if 'quote_unavailable' not in entry_reasons and 'quote_stale_or_future' not in entry_reasons:
        # Existing bound quotes remain observations; they supply no new lineage.
        roles.add('micro')
    if any(record['role'] == 'sentiment' for record in records):
        roles.add('sentiment')
    reasons = list(dict.fromkeys(reasons))
    missing = [role for role in SOURCE_ROLES if role not in roles]
    missing.extend(claim+'_independent_sources' for claim in CORE_CLAIMS
                   if claim+'_independent_sources_missing' in reasons)
    missing.append('calibrated_probability')
    state = 'No-trade' if row.get('action') == 'skip' or 'entry_window_expired' in reasons else 'Watch'
    result = dict(opportunity_id=row['opportunity_id'], symbol=row['symbol'], name=row['name'],
        state=state, audit=dict(status='held' if reasons else 'passed', reasons=reasons,
                               independent_sources=len(independent)),
        probability=dict(kind='unavailable', bull=None, base=None, bear=None,
            reason='사전 선언한 별도 OOS와 확률 보정 검증이 없습니다. 과거 승률은 미래 확률이 아닙니다.'),
        invalidation=invalidation, missing=missing)
    return result, roles


def _roles(candidates, available):
    count = len(candidates)
    roles = []
    for role in SOURCE_ROLES:
        found = sum(role in items for items in available)
        status = 'passed' if count and found == count else 'held' if found else 'unavailable'
        detail = f'현재 후보 {count}개 중 {found}개의 유효한 출처 계약을 확인했습니다.'
        if role == 'micro':
            detail = f'현재 후보 {count}개 중 {found}개의 저장된 시세 관측을 확인했습니다. 독립 검증 출처로 세지 않습니다.'
        if role == 'sentiment':
            status = 'held' if found else 'unavailable'
            detail = '뉴스·사회 관심은 보조 정보이며 단독 방향 또는 계좌 계획을 승인하지 않습니다.'
        roles.append(dict(id=role, title=ROLE_TITLES[role], status=status, detail=detail))
    passed = bool(candidates) and all(row['audit']['status'] == 'passed' for row in candidates)
    roles.extend([
        dict(id='auditor', title=ROLE_TITLES['auditor'], status='passed' if passed else 'held',
             detail='방향·위험 주장마다 S/A 등급 독립 원본 2개와 공개·확보 시각, 만료, 환율·수급을 검사합니다.'),
        dict(id='leader', title=ROLE_TITLES['leader'], status='held',
             detail='기존 연구 TOP3를 유지합니다. CIO 수동 검토와 계좌 계획은 별도로 필요합니다.'),
        dict(id='risk_guard', title=ROLE_TITLES['risk_guard'], status='held',
             detail='확인된 계좌·보유 종목과 현금·테마·손실 한도로 요청별 계산이 필요합니다.'),
        dict(id='review', title=ROLE_TITLES['review'], status='held',
             detail='M0: 사전 선언한 별도 OOS와 확률 보정 검증 전입니다. 기존 탐색 순위를 인증하지 않습니다.'),
    ])
    return roles


def build_agent_desk(status, *, now=None, evidence=None):
    """Return the exact additive AgentDesk view; never mutate or persist inputs."""
    current = datetime.now(timezone.utc) if now is None else _timestamp(now)
    if current is None:
        raise ValueError('timezone_required')
    board = _mapping(_mapping(status).get('opportunity_engine'))
    rows = _candidate_rows(board)
    cutoff = _timestamp(board.get('generated_at'))
    evidence = _mapping(evidence)
    candidates, available = [], []
    for row in rows:
        candidate, roles = _audit(row, board, evidence.get(row['symbol']), cutoff, current)
        candidates.append(candidate); available.append(roles)
    return dict(schema_version=1, policy_version=POLICY_VERSION, generated_at=_stamp(current),
        order_allowed=False, roles=_roles(candidates, available), candidates=candidates,
        promotion=dict(stage='M0', reasons=['predeclared_oos_pending', 'calibration_pending', 'manual_approval_required']))


def empirical_cvar(net_returns, *, confidence=.95):
    """Diagnostic lower-tail loss from actual completed net-return arrays only.

    The caller must supply the observed closed-trade net returns including costs.
    Historical summaries and win-rates are rejected; no assumed two-point or
    synthetic distribution is generated. Fractional empirical tail mass avoids
    rounding a small tail to an arbitrary sample count. This utility never
    changes rankings or forecasts.
    """
    level = _number(confidence)
    result = dict(status='unavailable', basis='observed_net_returns_not_forecast',
        confidence=level, samples=0, tail_mean_net_return=None, cvar_loss=None)
    if (level is None or not .5 <= level < 1 or not isinstance(net_returns, (list, tuple))
            or not 1 <= len(net_returns) <= 5000):
        return result
    values = [_number(value) for value in net_returns]
    if any(value is None or value < -1 for value in values):
        return result
    values.sort()
    tail_mass = (1-level)*len(values)
    whole = int(tail_mass)
    fractional = tail_mass-whole
    terms = [value/tail_mass for value in values[:whole]]
    if fractional:
        terms.append(values[whole]*(fractional/tail_mass))
    try:
        tail_mean = math.fsum(terms)
    except (OverflowError, ValueError):
        return result
    if not math.isfinite(tail_mean):
        return result
    result.update(status='available', samples=len(values), tail_mean_net_return=tail_mean,
                  cvar_loss=max(0., -tail_mean))
    return result
