"""Pure retrospective opportunity ranking and saved-quote guidance.

No IO, provider, account fills or future probability estimation occurs here.
The 1.96 standard-error subtraction is a conservative ranking heuristic;
screened, correlated trades do not establish a nominal confidence interval.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import re
from statistics import fmean, stdev

from ..kelly_position import two_point_kelly

POLICY = 'profit-opportunity-v1'
KST = timezone(timedelta(hours=9))
CALENDAR_SOURCE = 'KIS:CTCA0903R'
QUOTE_SOURCE = 'KIS:J:FHKST03010200+FHKST01010100'
SETUPS = dict(momentum='모멘텀', liquidity_breakout='유동성 돌파', mean_reversion='평균회귀')
LABELS = dict(entry_candidate='진입 후보', wait_next_session='다음 거래일 대기', data_check='데이터 확인', skip='이번 진입 건너뛰기')
BOARD_KEYS = ('schema_version', 'policy_version', 'decision_id', 'input_fingerprint', 'source_audit_hash',
    'generated_at', 'latest_session', 'entry_session', 'valid_until', 'status', 'research_only', 'live_orders',
    'coverage', 'candidates', 'alternatives', 'stages', 'reasons', 'evaluation')
CANDIDATE_KEYS = ('opportunity_id', 'decision_id', 'input_fingerprint', 'source_audit_hash', 'symbol', 'name',
    'market', 'strategy_id', 'rank', 'action', 'label', 'why_stock', 'why_now', 'next_action', 'quote_session',
    'source_at', 'current_price', 'quote_at', 'fetched_at', 'quote_source', 'valid_until', 'reference_weight',
    'plan', 'ranking', 'kelly', 'audit', 'reasons')
PLAN_KEYS = ('basis','entry_low','entry_high','stop_price','target_price','horizon_sessions')
RANKING_KEYS = ('stress_mean_net_return','standard_error','conservative_score','correlation_penalty',
                'score','calibration_samples','confirmation_samples')
KELLY_KEYS = ('raw_fraction','fraction','cap','account_risk_cap')
BLOCKERS = {'opportunity_engine_unavailable','opportunity_store_recovered','opportunity_store_unavailable',
            'entry_window_changed','source_identity_mismatch','source_stale_or_future','source_unavailable',
            'source_refresh_failed','discovery_policy_mismatch','source_identity_unavailable','source_report_mismatch'}


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


def _day(value):
    try:
        return value if isinstance(value, str) and date.fromisoformat(value).isoformat() == value else None
    except ValueError:
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


def _now(value):
    current = datetime.now(timezone.utc) if value is None else _timestamp(value)
    if current is None:
        raise ValueError('timezone_required')
    return current


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z') if value else None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()


def _hash_valid(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _codes(value):
    return [code for code in value if isinstance(code,str) and re.fullmatch('[a-z][a-z0-9_]{0,95}',code)] if isinstance(value,list) else []


def _text(value, limit=300):
    """Only bounded scalar prose crosses the public projection boundary."""
    if not isinstance(value,str) or re.search(r'[A-Za-z]:[\\/]',value):
        return ''
    return value[:limit]


def _public_stages(value):
    stages = []
    for row in value[:20] if isinstance(value,list) else []:
        row = _mapping(row)
        stage_id = _codes([row.get('id')])
        count = row.get('count')
        if (not stage_id or row.get('status') not in ('passed','held','unavailable')
                or isinstance(count,bool) or not isinstance(count,int) or not 0 <= count <= 100):
            continue
        stages.append(dict(id=stage_id[0],status=row['status'],detail=_text(row.get('detail')),count=count))
    return stages


def _public_alternatives(value):
    rows = []
    for row in value[:10] if isinstance(value,list) else []:
        row = _mapping(row)
        symbol, strategy = row.get('symbol'),row.get('strategy_id')
        reason = _codes([row.get('reason')])
        score = _number(row.get('score'))
        if (not isinstance(symbol,str) or re.fullmatch('[0-9]{6}',symbol) is None
                or not isinstance(strategy,str) or strategy not in SETUPS or not reason or not isinstance(row.get('name'),str)):
            continue
        rows.append(dict(symbol=symbol,name=_text(row['name'],200),strategy_id=strategy,
                         score=score,reason=reason[0]))
    return rows


def _stable_identity(fingerprint, audit_hash, latest, candidates):
    rows = []
    for row in candidates:
        value = {key:row[key] for key in ('symbol','strategy_id','rank','reference_weight')}
        for key,keys in (('plan',PLAN_KEYS),('ranking',RANKING_KEYS),('kelly',KELLY_KEYS)):
            value[key] = {name:row[key][name] for name in keys}
        rows.append(value)
    return _hash(dict(policy_version=POLICY,input_fingerprint=fingerprint,source_audit_hash=audit_hash,
                      latest_session=latest,candidates=rows))


def _saved_candidate_valid(row, board, rank):
    if not isinstance(row,dict):
        return False
    symbol = row.get('symbol')
    if (not isinstance(symbol,str) or re.fullmatch('[0-9]{6}',symbol) is None or symbol == '000000'
            or not isinstance(row.get('strategy_id'),str) or row.get('strategy_id') not in SETUPS or row.get('rank') != rank or row.get('market') != 'KR'
            or not isinstance(row.get('name'),str) or not 1 <= len(row['name']) <= 200
            or row.get('quote_session') != board.get('latest_session')
            or any(row.get(key) != board.get(key) for key in ('decision_id','input_fingerprint','source_audit_hash'))
            or row.get('opportunity_id') != _hash(dict(decision_id=board['decision_id'],symbol=symbol,strategy_id=row['strategy_id']))):
        return False
    plan, ranking, kelly, audit = map(_mapping,(row.get('plan'),row.get('ranking'),row.get('kelly'),row.get('audit')))
    numbers = [_number(plan.get(key)) for key in ('stop_price','entry_low','entry_high','target_price')]
    stop,low,high,target = numbers
    weight,raw_fraction = _number(row.get('reference_weight')),_number(kelly.get('raw_fraction'))
    if (None in numbers or not 0 < stop < low <= high < target or plan.get('horizon_sessions') != 10
            or plan.get('basis') != 'last_closed_price_reference'
            or not math.isclose(high,min(low*1.02,target-(target-low)*1e-6),rel_tol=1e-9)
            or weight is None or raw_fraction is None or raw_fraction <= 0
            or not 0 < weight <= min(.05,.25*raw_fraction,.01/(1-stop/low))+1e-10
            or kelly.get('fraction') != .25 or kelly.get('cap') != .05 or kelly.get('account_risk_cap') != .01
            or audit.get('status') != 'passed' or audit.get('independent_validation') is not False):
        return False
    mean,error,conservative,penalty,score = [_number(ranking.get(key)) for key in RANKING_KEYS[:5]]
    if (None in (mean,error,conservative,penalty,score) or mean <= 0 or error < 0 or not 0 <= penalty <= .01+1e-10
            or not math.isclose(conservative,mean-1.96*error,rel_tol=1e-9,abs_tol=1e-10)
            or not math.isclose(score,conservative-penalty,rel_tol=1e-9,abs_tol=1e-10)):
        return False
    for key,minimum in (('calibration_samples',30),('confirmation_samples',10)):
        value = ranking.get(key)
        if isinstance(value,bool) or not isinstance(value,int) or not minimum <= value <= 5000:
            return False
    return True


def _public_candidate(row):
    result = {key:deepcopy(row[key]) for key in CANDIDATE_KEYS if key in row}
    for key,keys in (('plan',PLAN_KEYS),('ranking',RANKING_KEYS),('kelly',KELLY_KEYS)):
        result[key] = {name:deepcopy(row[key][name]) for name in keys}
    result['audit'] = dict(status=row['audit']['status'],reasons=_codes(row['audit'].get('reasons')),independent_validation=False)
    result['reasons'] = _codes(row.get('reasons'))
    action = result.get('action')
    result['action'] = action if isinstance(action,str) and action in LABELS else 'data_check'
    for key in ('name','label','why_stock','why_now','next_action'):
        result[key] = _text(result.get(key),500 if key == 'why_stock' else 300)
    for key in ('source_at','quote_at','fetched_at','valid_until'):
        result[key] = _stamp(_timestamp(result.get(key)))
    result['current_price'] = _number(result.get('current_price'))
    result['quote_source'] = QUOTE_SOURCE if result.get('quote_source') == QUOTE_SOURCE else None
    return result


def _source_reasons(report, latest, origin, current):
    scan, provenance = _mapping(report.get('opportunity_scan')), _mapping(report.get('provenance'))
    reasons = []
    if not _hash_valid(report.get('input_fingerprint')) or not _hash_valid(scan.get('audit_hash')):
        reasons.append('source_identity_unavailable')
    if report.get('schema_version') != 1 or report.get('mode') != 'research' or report.get('latest_session') != latest:
        reasons.append('source_report_mismatch')
    capture = _timestamp(provenance.get('captured_at'))
    scope = _day(_mapping(report.get('universe')).get('scope_date'))
    today = current.astimezone(KST).date()
    if (origin is None or origin > current or capture is None or capture > origin or latest is None or scope is None
            or date.fromisoformat(latest) > origin.astimezone(KST).date()
            or not 0 <= (today-date.fromisoformat(latest)).days <= 7
            or not 0 <= (today-date.fromisoformat(scope)).days <= 7
            or not 0 <= (today-capture.astimezone(KST).date()).days <= 7):
        reasons.append('source_stale_or_future')
    flags = _mapping(_mapping(report.get('diagnostics')).get('source_flags'))
    if scan.get('status') != 'ready' or any(flags.get(key) for key in ('future_source_capture','capture_timezone_unverified')):
        reasons.append('source_unavailable')
    values = [*scan.get('reasons', [])] if isinstance(scan.get('reasons'), list) else []
    if any('refresh_failed' in str(value) for value in values):
        reasons.append('source_refresh_failed')
    return reasons


def _phase(value, minimum, latest):
    """Recompute qualified completed outcomes, never trust descriptive means."""
    value = _mapping(value)
    summary, trades = _mapping(value.get('summary')), value.get('trades')
    start, end = _day(summary.get('start')), _day(summary.get('end'))
    if (start is None or end is None or start > end or end > latest
            or not isinstance(trades, list) or not minimum <= len(trades) <= 5000
            or summary.get('samples') != len(trades)):
        return None
    net, stress, previous = [], [], None
    for trade in trades:
        trade = _mapping(trade)
        signal, entry, exit_day = (_day(trade.get(key)) for key in ('signal_date','entry_date','exit_date'))
        normal, doubled = _number(trade.get('net_return')), _number(trade.get('stress_net_return'))
        if (trade.get('status') != 'closed' or None in (signal,entry,exit_day,normal,doubled)
                or not start <= signal < entry <= exit_day <= end
                or previous is not None and entry <= previous or min(normal,doubled) <= -1
                or doubled > normal+1e-10):
            return None
        net.append(normal); stress.append(doubled); previous = exit_day
    if (not any(v > 0 for v in net) or not any(v < 0 for v in net)
            or fmean(net) <= 0 or fmean(stress) <= 0
            or sum(math.log1p(v) for v in net) <= 0 or sum(math.log1p(v) for v in stress) <= 0):
        return None
    return dict(net=net, stress=stress, start=start, end=end)


def _price_returns(raw, symbol, latest):
    if not isinstance(raw, list):
        return {}, None
    rows, previous = [], None
    for row in raw:
        row = _mapping(row)
        day = _day(row.get('date'))
        if day is None:
            return {}, None
        if day > latest:  # Exclude the future before inspecting its values.
            continue
        close = _number(row.get('close'))
        if (previous is not None and day <= previous or row.get('symbol', symbol) != symbol
                or close is None or close <= 0 or row.get('quality_flags')):
            return {}, None
        rows.append((day,close)); previous = day
    if not rows or rows[-1][0] != latest:
        return {}, None
    window = rows[-61:]
    returns = {(a[0],b[0]):b[1]/a[1]-1 for a,b in zip(window,window[1:])}
    return returns, rows[-1][1]


def _correlation(left, right):
    days = sorted(set(left).intersection(right))
    if len(days) < 30:
        return None
    x, y = [left[d] for d in days], [right[d] for d in days]
    mx, my = fmean(x), fmean(y)
    xx, yy = sum((v-mx)**2 for v in x), sum((v-my)**2 for v in y)
    if xx <= 0 or yy <= 0:
        return None
    return max(-1.,min(1.,sum((a-mx)*(b-my) for a,b in zip(x,y))/math.sqrt(xx*yy)))


def _penalty(row, selected):
    correlations = [_correlation(row['_returns'], other['_returns']) for other in selected]
    unknown = any(value is None for value in correlations)
    penalty = .01*max([0., *(value for value in correlations if value is not None)])
    return max(penalty,.005 if unknown else 0.), unknown


def _valid_plan(row):
    plan = _mapping(row.get('plan'))
    reference, stop, target = (_number(plan.get(key)) for key in ('entry_price','stop_price','target_price'))
    close = _number(row.get('last_close'))
    if (None in (reference,stop,target,close) or not 0 < stop < reference < target
            or not math.isclose(reference,close,rel_tol=1e-9)
            or plan.get('status') != 'ready'):
        return None
    loss = 1-stop/reference
    if not 0 < loss <= .08+1e-10:
        return None
    return dict(basis='last_closed_price_reference',entry_low=reference,
        entry_high=min(reference*1.02,target-(target-reference)*1e-6),stop_price=stop,target_price=target,horizon_sessions=10)


def _action(row, action, reason, *, detail=None):
    row['action'], row['label'] = action, LABELS[action]
    row['why_now'] = detail or dict(entry_candidate='공식 거래일의 새 시세가 진입 상한·손절·목표 안에 있습니다.',
        wait_next_session='확정된 다음 거래일의 진입 시각을 기다립니다.',
        data_check='출처·거래일·시세와 고정 진입 창을 확인해야 합니다.',skip='가격 또는 진입 창 조건을 벗어났습니다.')[action]
    row['next_action'] = dict(entry_candidate='현재 시세 기준 계획을 검토하세요. 실제 체결이나 주문 승인이 아닙니다.',
        wait_next_session='다음 거래일에 새 시세로 진입 조건을 다시 확인하세요.',
        data_check='출처와 저장된 시세를 갱신한 뒤 조건을 다시 확인하세요.',
        skip='가격을 추격하지 말고 다음 독립 분석 결과를 기다리세요.')[action]
    if reason and reason not in row['reasons']:
        row['reasons'].append(reason)


def build_opportunity_board(discovery, prices_by_symbol, report, *, now=None):
    """Rank every qualified survivor on causal calibration evidence only."""
    current = _now(now)
    discovery, report, prices_by_symbol = map(_mapping,(discovery,report,prices_by_symbol))
    latest = _day(discovery.get('latest_session'))
    origin = _timestamp(report.get('decision_at'))
    reasons = _source_reasons(report,latest,origin,current)
    if (discovery.get('policy_version') != 'quality-setup-opportunity-v1'
            or discovery.get('selection_basis') != 'calibration_stress_mean_then_confirmation'
            or discovery.get('horizon_sessions') != 10 or discovery.get('cost_stress_multiplier') != 2.):
        reasons.append('discovery_policy_mismatch')
    audit_rows = discovery.get('audit') if isinstance(discovery.get('audit'),list) else []
    audits = {}
    for row in audit_rows:
        if isinstance(row,dict) and row.get('selected') is True and row.get('eligible') is True:
            key = (row.get('symbol'),row.get('strategy_id'))
            audits[key] = row if key not in audits else None
    candidates = discovery.get('candidates') if isinstance(discovery.get('candidates'),list) else []
    survivors, rejected, seen = [], [], set()
    for raw in candidates[:100]:
        raw = _mapping(raw)
        symbol, strategy = raw.get('symbol'),raw.get('strategy_id')
        if (not isinstance(symbol,str) or re.fullmatch('[0-9]{6}',symbol) is None
                or symbol == '000000' or symbol in seen or strategy not in SETUPS):
            continue
        seen.add(symbol)
        name = raw.get('name') if isinstance(raw.get('name'),str) else symbol
        evidence, audit = _mapping(raw.get('evidence')), _mapping(audits.get((symbol,strategy)))
        cal = _phase(audit.get('calibration'),30,latest) if latest else None
        conf = _phase(audit.get('confirmation'),10,latest) if latest else None
        plan = _valid_plan(raw)
        returns, close = _price_returns(prices_by_symbol.get(symbol),symbol,latest) if latest else ({},None)
        if (cal is None or conf is None or cal['end'] >= conf['start'] or conf['end'] != latest
                or evidence.get('independent_validation') is not False or evidence.get('retrospective') is not True
                or raw.get('setup_active') is not True or raw.get('quote_session') != latest or plan is None
                or close is None or not math.isclose(close,raw['last_close'],rel_tol=1e-9)):
            rejected.append(dict(symbol=symbol,name=name,strategy_id=strategy,score=None,reason='evidence_or_plan_unavailable'))
            continue
        diagnostic = two_point_kelly(cal['net'])
        fraction = _number(diagnostic.get('raw_fraction'))
        if diagnostic.get('status') != 'ready' or fraction is None or fraction <= 0:
            rejected.append(dict(symbol=symbol,name=name,strategy_id=strategy,score=None,reason='nonpositive_calibration_kelly'))
            continue
        mean, error = fmean(cal['stress']),stdev(cal['stress'])/math.sqrt(len(cal['stress']))
        score = mean-1.96*error
        if not math.isfinite(score):
            continue
        row_reasons = ['retrospective_challenger_not_independent_validation', 'research_reference_not_order_approval',
                       'current_cohort_and_source_vintage_limitations']
        if score <= 0:
            row_reasons.append('uncertainty_adjusted_score_nonpositive')
        survivors.append(dict(symbol=symbol,name=name,market='KR',strategy_id=strategy,
            rank=0,opportunity_id='',decision_id='',input_fingerprint=report.get('input_fingerprint',''),
            source_audit_hash=_mapping(report.get('opportunity_scan')).get('audit_hash',''),
            action='data_check',label=LABELS['data_check'],
            why_stock=f"{SETUPS[strategy]} 조건 · 앞 구간 {len(cal['net'])}건, 확인 구간 {len(conf['net'])}건의 비용 2배 순수익이 양수입니다."
                + (' 불확실성 차감 점수는 0 이하이며, 수익 우위가 검증되지 않은 탐색적 참고입니다.' if score <= 0 else ' 과거 선별 결과의 탐색적 참고이며 미래 수익 우위는 검증되지 않았습니다.'),
            why_now='',next_action='',quote_session=latest,source_at=_stamp(_timestamp(_mapping(report.get('provenance')).get('captured_at'))),
            current_price=None,quote_at=None,fetched_at=None,quote_source=None,valid_until=None,
            reference_weight=min(.25*fraction,.05,.01/(1-plan['stop_price']/plan['entry_low'])),plan=plan,
            ranking=dict(stress_mean_net_return=mean,standard_error=error,conservative_score=score,
                correlation_penalty=0.,score=score,calibration_samples=len(cal['net']),confirmation_samples=len(conf['net'])),
            kelly=dict(raw_fraction=fraction,fraction=.25,cap=.05,account_risk_cap=.01),
            audit=dict(status='passed',reasons=['screened_correlated_outcomes_not_nominal_confidence_interval',
                *(['uncertainty_adjusted_score_nonpositive'] if score <= 0 else [])],independent_validation=False),
            reasons=row_reasons,_returns=returns))
    remaining, selected = list(survivors), []
    while remaining and len(selected) < 3:
        for row in remaining:
            penalty, unknown = _penalty(row,selected)
            row['ranking']['correlation_penalty'] = penalty
            row['ranking']['score'] = row['ranking']['conservative_score']-penalty
            row['_unknown'] = unknown
        remaining.sort(key=lambda row:(-row['ranking']['score'],row['symbol']))
        row = remaining.pop(0)
        row['rank'] = len(selected)+1
        if row['_unknown']:
            row['reasons'].append('correlation_unavailable')
        selected.append(row)
    if not selected:
        reasons.append('no_qualified_survivors')
    for row in selected:
        row.pop('_returns',None); row.pop('_unknown',None)
        _action(row,'data_check','entry_window_unavailable')
    fingerprint = report.get('input_fingerprint','')
    audit_hash = _mapping(report.get('opportunity_scan')).get('audit_hash','')
    identity = _stable_identity(fingerprint,audit_hash,latest,selected)
    for row in selected:
        row['decision_id'] = identity
        row['opportunity_id'] = _hash(dict(decision_id=identity,symbol=row['symbol'],strategy_id=row['strategy_id']))
    alternatives = [dict(symbol=row['symbol'],name=row['name'],strategy_id=row['strategy_id'],score=row['ranking']['score'],
                         reason='lower_calibration_uncertainty_diversification_rank') for row in remaining]
    stages = [dict(id='data',status='held' if reasons else 'passed',detail='저장된 출처와 원본 분석 식별자 검사',count=len(prices_by_symbol)),
        dict(id='setup',status='passed' if survivors else 'held',detail='현재 활성 설정과 완료 순수익 조건 검사',count=len(survivors)),
        dict(id='critic',status='passed' if survivors else 'held',detail='확인 구간은 통과 여부만 사용 · 1.96 표준오차는 순위 휴리스틱',count=len(survivors)),
        dict(id='diversification',status='passed' if selected else 'unavailable',detail='관측 가능한 과거 일간 수익 상관 페널티 · 미확인은 별도 표시',count=len(selected)),
        dict(id='risk',status='passed' if selected else 'held',detail='1/4 켈리 참고 · 종목 5%와 계획 손실 1% 상한',count=len(selected)),
        dict(id='entry',status='held',detail='공식 거래일과 저장된 당일 새 시세 확인 대기',count=0)]
    return dict(schema_version=1,policy_version=POLICY,decision_id=identity,input_fingerprint=fingerprint,source_audit_hash=audit_hash,
        generated_at=_stamp(origin or current),latest_session=latest,entry_session=None,valid_until=None,status='held',
        research_only=True,live_orders=False,coverage=dict(inspected=int(discovery.get('inspected_count',len(prices_by_symbol))),
        eligible=len(survivors),selected=len(selected)),candidates=selected,alternatives=(alternatives+rejected)[:10],
        stages=stages,reasons=list(dict.fromkeys([*reasons,'entry_window_unavailable'])),origin_at=_stamp(origin))


def _window(report, raw):
    window = _mapping(report.get('proposal_window'))
    origin = _timestamp(window.get('origin_at'))
    original = _timestamp(raw.get('origin_at',raw.get('generated_at')))
    capture = _timestamp(_mapping(report.get('provenance')).get('captured_at'))
    session = _day(window.get('entry_session'))
    until = _timestamp(window.get('valid_until'))
    if (window.get('policy_version') != 'next-session-proposal-v1' or window.get('calendar_source') != CALENDAR_SOURCE
            or window.get('input_fingerprint') != raw.get('input_fingerprint')
            or window.get('opportunity_audit_hash') != raw.get('source_audit_hash')
            or None in (origin,original,capture,session,until) or not capture <= origin <= original):
        return None,None
    entry_day = date.fromisoformat(session)
    expected = datetime.combine(entry_day,time(15,30),KST).astimezone(timezone.utc)
    if (not origin.astimezone(KST).date() < entry_day <= origin.astimezone(KST).date()+timedelta(days=7)
            or until != expected or raw.get('valid_until') not in (None,_stamp(until))
            or raw.get('entry_session') not in (None,session)):
        return None,None
    return session,until


def _snapshot_reason(snapshot, board, session, until, current):
    if any(snapshot.get(key) != board.get(key) for key in ('decision_id','input_fingerprint','source_audit_hash')):
        return 'quote_identity_mismatch'
    observed = _timestamp(snapshot.get('observed_at'))
    calendar = _mapping(snapshot.get('calendar'))
    checked = _timestamp(calendar.get('checked_at'))
    today = current.astimezone(KST).date()
    if (observed is None or observed > current or not 0 <= (current-observed).total_seconds() <= 420
            or observed.astimezone(KST).date() != today):
        return 'quote_snapshot_stale_or_future'
    if (calendar.get('status') != 'ready' or calendar.get('source') != CALENDAR_SOURCE
            or checked is None or checked > current or checked.astimezone(KST).date() != today
            or calendar.get('entry_session') != session or calendar.get('valid_until') != _stamp(until)):
        return 'calendar_unavailable_or_changed'
    if calendar.get('market_state') != 'open':
        return 'market_closed'
    return None


def _quote_reason(quote, symbol, current, observed):
    price = _number(quote.get('price'))
    at, fetched = _timestamp(quote.get('quote_at')),_timestamp(quote.get('fetched_at'))
    if (quote.get('symbol') != symbol or quote.get('source') != QUOTE_SOURCE or quote.get('status','ready') != 'ready'
            or price is None or price <= 0 or at is None or fetched is None):
        return 'quote_unavailable'
    if not at <= fetched <= observed <= current:
        return 'quote_future'
    today = current.astimezone(KST).date()
    if (at.astimezone(KST).date() != today or fetched.astimezone(KST).date() != today
            or not 0 <= (current-fetched).total_seconds() <= 420 or (current-at).total_seconds() > 420
            or (fetched-at).total_seconds() > 120
            or not time(9) <= at.astimezone(KST).time().replace(tzinfo=None) < time(15,30)):
        return 'quote_stale'
    return None


def project_opportunity_board(status, *, now=None, quote_snapshot=None):
    """Deep-copy the saved status and expose conditional research guidance only."""
    result = deepcopy(status)
    report = _mapping(result.get('report'))
    # The caller's immutable report is untouched; no unfiltered raw board can
    # cross any return branch of this public projection.
    raw = _mapping(report.pop('opportunity_board',None))
    if not raw:
        return result
    current = _now(now)
    if (raw.get('schema_version') != 1 or raw.get('policy_version') != POLICY
            or not all(_hash_valid(raw.get(key)) for key in ('decision_id','input_fingerprint','source_audit_hash'))
            or not isinstance(raw.get('candidates'),list) or len(raw['candidates']) > 3):
        result.pop('opportunity_engine',None)
        return result
    board = {key:deepcopy(raw[key]) for key in BOARD_KEYS if key in raw}
    board.update(generated_at=_stamp(_timestamp(raw.get('generated_at'))),latest_session=_day(raw.get('latest_session')),
        entry_session=_day(raw.get('entry_session')),valid_until=_stamp(_timestamp(raw.get('valid_until'))),
        research_only=True,live_orders=False,status='ready' if raw.get('status') == 'ready' else 'held')
    board['stages'] = _public_stages(raw.get('stages'))
    board['alternatives'] = _public_alternatives(raw.get('alternatives'))
    board['reasons'] = _codes(raw.get('reasons'))
    valid_rows = all(_saved_candidate_valid(row,raw,i+1) for i,row in enumerate(raw['candidates']))
    valid_rows = valid_rows and len({row['symbol'] for row in raw['candidates']}) == len(raw['candidates'])
    if valid_rows:
        valid_rows = _stable_identity(raw['input_fingerprint'],raw['source_audit_hash'],raw.get('latest_session'),raw['candidates']) == raw['decision_id']
    board['candidates'] = [_public_candidate(row) for row in raw['candidates']] if valid_rows else []
    board['coverage'] = {key:value for key in ('inspected','eligible','selected')
        if isinstance((value:=_mapping(raw.get('coverage')).get(key)),int) and not isinstance(value,bool) and 0 <= value <= 100}
    if len(board['coverage']) != 3:
        board['coverage'] = dict(inspected=0,eligible=0,selected=0)
        valid_rows = False
        board['candidates'] = []
    board['coverage']['selected'] = len(board['candidates'])
    # Retain only a canonical original-plan view for safe repeated projection.
    # In particular, the observed current-price plan below never overwrites it.
    public_raw = deepcopy(board)
    public_raw['origin_at'] = _stamp(_timestamp(raw.get('origin_at',raw.get('generated_at'))))
    public_raw.pop('evaluation',None)
    report['opportunity_board'] = public_raw
    reasons = _source_reasons(report,_day(raw.get('latest_session')),_timestamp(raw.get('origin_at',raw.get('generated_at'))),current)
    reasons.extend(code for code in _codes(raw.get('reasons')) if code in BLOCKERS)
    reasons.extend(code for code in _codes(_mapping(quote_snapshot).get('reasons')) if code in {'calendar_revision','opportunity_store_unavailable'})
    if not valid_rows:
        reasons.append('saved_board_invalid')
    if result.get('state') not in ('ready','held'):
        reasons.append('scan_unavailable')
    if any(report.get(key) != raw.get(key) for key in ('input_fingerprint','latest_session')) or _mapping(report.get('opportunity_scan')).get('audit_hash') != raw.get('source_audit_hash'):
        reasons.append('source_identity_mismatch')
    session,until = _window(report,raw)
    prior = _mapping(result.get('opportunity_engine'))
    if prior.get('decision_id') == raw.get('decision_id') and prior.get('valid_until'):
        pinned = _timestamp(prior.get('valid_until'))
        if until != pinned or session != prior.get('entry_session'):
            reasons.append('entry_window_changed')
        session,until = prior.get('entry_session'),pinned
    board['entry_session'],board['valid_until'] = session,_stamp(until)
    if session is None or until is None:
        reasons.append('entry_window_unavailable')
    snapshot = _mapping(quote_snapshot)
    quotes = snapshot.get('quotes')
    if isinstance(quotes,list):
        quotes = {row.get('symbol'):row for row in quotes if isinstance(row,dict)}
    quotes = _mapping(quotes)
    local = current.astimezone(KST)
    before = session is not None and (local.date().isoformat() < session or local.time().replace(tzinfo=None) < time(9))
    expired = until is not None and current >= until
    snapshot_problem = _snapshot_reason(snapshot,board,session,until,current) if not reasons and not before and not expired else None
    if snapshot_problem and snapshot_problem != 'market_closed':
        reasons.append(snapshot_problem)
    for row in board['candidates']:
        row.update(current_price=None,quote_at=None,fetched_at=None,quote_source=None,valid_until=_stamp(until))
        row['reasons'] = [r for r in row.get('reasons',[]) if r != 'entry_window_unavailable']
        if reasons:
            _action(row,'data_check',reasons[0])
        elif expired:
            _action(row,'skip','entry_window_expired')
        elif before or snapshot_problem == 'market_closed':
            _action(row,'wait_next_session','before_entry_session' if before else 'market_closed')
        elif local.date().isoformat() != session:
            _action(row,'data_check','entry_session_mismatch')
        else:
            quote = _mapping(quotes.get(row.get('symbol')))
            problem = _quote_reason(quote,row.get('symbol'),current,_timestamp(snapshot.get('observed_at')))
            if problem:
                _action(row,'data_check',problem)
                continue
            price,plan = float(quote['price']),row['plan']
            row.update(current_price=price,quote_at=_stamp(_timestamp(quote['quote_at'])),
                       fetched_at=_stamp(_timestamp(quote['fetched_at'])),quote_source=QUOTE_SOURCE)
            if price > plan['entry_high']:
                _action(row,'skip','above_chase_cap')
            elif price <= plan['stop_price']:
                _action(row,'skip','below_stop')
            elif price >= plan['target_price']:
                _action(row,'skip','target_reached')
            else:
                row['plan'] = dict(plan,basis='observed_quote_reference',entry_low=price)
                row['reference_weight'] = min(row['reference_weight'],.05,.01/(1-plan['stop_price']/price))
                _action(row,'entry_candidate','fresh_saved_current_quote_reference_not_fill')
    count = sum(row['action'] == 'entry_candidate' for row in board['candidates'])
    board['status'] = 'ready' if count and not reasons else 'held'
    board['reasons'] = list(dict.fromkeys([*[r for r in _codes(raw.get('reasons')) if r != 'entry_window_unavailable'],*reasons,
        *(['entry_window_expired'] if expired else [])]))
    for stage in board.get('stages',[]):
        if stage.get('id') == 'entry':
            stage.update(status='passed' if count else 'held',count=count)
    evaluation = _mapping(raw.get('evaluation'))
    counts = {key:evaluation.get(key,0) for key in ('issued','pending','expired','observed','unobserved')}
    if not all(isinstance(value,int) and not isinstance(value,bool) and value >= 0 for value in counts.values()):
        counts = dict(issued=0,pending=0,expired=0,observed=0,unobserved=0)
    if not evaluation:
        counts.update(issued=len(board['candidates']),pending=0 if expired else len(board['candidates']),
                      expired=len(board['candidates']) if expired else 0)
    board['evaluation'] = dict(basis='issued_opportunities_not_fills',**counts)
    public_raw['evaluation'] = deepcopy(board['evaluation'])
    result['opportunity_engine'] = board
    return result
