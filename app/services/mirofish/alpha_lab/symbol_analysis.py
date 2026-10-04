"""Isolated administrator symbol research using the unchanged AlphaLab policy.

GET reads saved projections only. POST owns one bounded worker across symbols;
the member scan, prospective journals and operational monitor are never written.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import threading

from filelock import FileLock, Timeout

from . import discovery, store
from .execution import build_bracket_plan
from .proposals import present_status, _timestamp, KST

ROOT = Path(__file__).resolve().parents[4] / 'data' / 'admin_mirofish' / 'symbol_alpha'
POLICY_VERSION = 'admin-symbol-alpha-v1'


def resolve_target(symbol):
    from ..live_data import _load_ticker_map
    if not isinstance(symbol, str) or re.fullmatch(r'[0-9]{6}', symbol) is None or symbol == '000000':
        raise ValueError('invalid_symbol')
    row = _load_ticker_map().get(symbol)
    if not row or row.get('market') not in {'KR', 'KOSPI', 'KOSDAQ', 'KOSDAQ GLOBAL', ''}:
        raise ValueError('unknown_symbol')
    return dict(symbol=symbol, name=str(row.get('name') or symbol), market='KR')


def search(query, *, limit=8):
    from ..live_data import search_target_candidates
    if not isinstance(query, str) or len(query) > 80 or isinstance(limit, bool) or not isinstance(limit,int) or not 1 <= limit <= 20:
        raise ValueError('invalid_search')
    candidates = []
    for row in search_target_candidates(query.strip(), limit=30):
        try:
            candidates.append(resolve_target(row['symbol']))
        except ValueError:
            continue
        if len(candidates) == limit:
            break
    return dict(candidates=candidates)


def acquire_inputs(target, *, root, now):
    from .symbol_sources import acquire_inputs as acquire
    return acquire(target, root=root, now=now)


def _directory(root, symbol):
    return (Path(root) if root is not None else ROOT) / symbol


def _empty(target, state='missing', *, now=None, error=None):
    return dict(schema_version=1, policy_version=POLICY_VERSION, state=state, target=target,
                generated_at=store.timestamp(now) if state != 'missing' else None, error=error, result=None)


def _save(directory, value):
    store._write(directory/'status.json', dict(status=value, sha256=store._hash(value)))
    return value


def _read(directory, target, now):
    try:
        saved = store._read(directory/'status.json')
        if saved is None:
            return _empty(target)
        status = saved['status']
        if (saved['sha256'] != store._hash(status) or status['schema_version'] != 1
                or status['policy_version'] != POLICY_VERSION or status['target'] != target
                or status['state'] not in {'missing','running','ready','held','failed'}):
            raise ValueError('saved_integrity')
        if status['state'] == 'running':
            started = _timestamp(status.get('generated_at'))
            if started is None or (_timestamp(store.timestamp(now))-started).total_seconds() > 900:
                status = dict(status,state='failed',error='analysis_interrupted')
        return status
    except (OSError,ValueError,KeyError,TypeError):
        return _empty(target,'failed',now=now,error='saved_analysis_unavailable')


def _project(status, now=None):
    value = deepcopy(status)
    report = value.pop('_report', None)
    if value.get('result') is None or report is None:
        return value
    current=_timestamp(store.timestamp(now))
    checked=_timestamp(report.get('calendar_confirmed_at'))
    calendar_stale=(checked is None or checked>current or checked.astimezone(KST).date()!=current.astimezone(KST).date())
    if calendar_stale:
        report['opportunity_scan']['status']='held'
        for stage in value['result']['stages']:
            if stage['id']=='session':stage['state']='held'
    viewed = present_status(dict(state=value['state'],report=report),now=store.timestamp(now))['report']
    candidate = viewed['buy_candidates'][0]
    if candidate['proposal']['action'] != 'buy':
        if value.get('error')=='analysis_busy':
            candidate['proposal']['reason']='다른 종목 분석이 진행 중입니다. 저장된 가격을 참고하고 완료 후 다시 분석하세요.'
        elif value['state'] in {'running','failed'}:
            candidate['proposal']['reason'] = ('새 분석이 진행 중입니다. 이전 가격 계획을 참고하고 완료 결과를 기다리세요.'
                if value['state']=='running' else '가격·출처 갱신에 실패했습니다. 이전 가격 계획을 보존하고 매수 제안을 보류합니다.')
        elif 'official_calendar_revision' in report.get('warnings',[]):
            candidate['proposal']['reason']='공식 거래일 정보가 최초 제안과 달라졌습니다. 가격 계획을 보존하고 새 종가가 확인될 때까지 진입을 보류합니다.'
        elif calendar_stale:
            candidate['proposal']['reason']='오늘의 공식 거래일 확인이 필요합니다. 가격 계획을 참고하고 분석을 갱신하세요.'
        elif value['result']['quality']['status']!='passed':
            candidate['proposal']['reason'] = ('현재 공시의 재무 품질 기준을 통과하지 못해 신규 진입을 보류합니다.'
                if value['result']['quality']['status']=='blocked' else '현재 재무 자료의 출처를 확인하지 못해 신규 진입을 기다립니다.')
        elif candidate.get('strategy_id')=='reference_only':
            reasons=candidate.get('reasons',[])
            candidate['proposal']['reason'] = ('같은 정책을 평가할 1,260거래일 이력이 부족합니다. 계산 가능한 ATR 가격 계획만 표시합니다.'
                if 'insufficient_union_history' in reasons else '현재 활성화된 진입 조건과 비용을 반영한 양수 과거 순손익 근거를 함께 충족하지 못했습니다.')
        elif not viewed.get('proposal_window', {}).get('entry_session'):
            candidate['proposal']['reason'] = '공식 다음 거래일과 제안 유효기간을 확인하지 못해 진입을 기다립니다.'
    value['result']['candidate'] = candidate
    return value


def read_status(symbol, *, root=None, now=None):
    target = resolve_target(symbol)
    return _project(_read(_directory(root,symbol),target,now),now)


def _fallback(target, rows, scan):
    reasons = list(dict.fromkeys([*scan.get('reasons',[]),
        *(reason for audit in scan.get('audit',[]) for reason in audit.get('reasons',[]))]))
    if not reasons:
        reasons=['no_positive_current_setup_evidence']
    plan=build_bracket_plan(rows)
    return dict(symbol=target['symbol'],name=target['name'],strategy_id='reference_only',score=0.,
        last_close=rows[-1]['close'],quote_session=rows[-1]['date'],setup_active=False,
        plan=plan if plan['status']=='ready' else None,
        risk=dict(weight=0.,status='held',research_weight=0.,p=None,kelly_raw=None,reasons=reasons),reasons=reasons)


def _origins(directory):
    raw=store._read(directory/'origins.json')
    if raw is None:return {}
    if (not isinstance(raw,dict) or raw.get('schema_version')!=1 or not isinstance(raw.get('origins'),dict)
            or raw.get('sha256')!=store._hash(raw['origins']) or len(raw['origins'])>128):
        raise ValueError('origin_integrity')
    for identity,record in raw['origins'].items():
        if (not isinstance(identity,str) or re.fullmatch('[0-9a-f]{64}',identity) is None
                or not isinstance(record,dict) or not isinstance(record.get('calendar_revision',False),bool)):
            raise ValueError('origin_integrity')
        decision,capture=(_timestamp(record.get(key)) for key in ('decision_at','captured_at'))
        window=record.get('proposal_window')
        if (decision is None or capture is None or capture>decision or window is not None and not isinstance(window,dict)):
            raise ValueError('origin_integrity')
        if window is not None:
            origin=_timestamp(window.get('origin_at'))
            if (origin is None or not capture<=origin<=decision or window.get('calendar_source')!='KIS:CTCA0903R'
                    or window.get('policy_version')!='next-session-proposal-v1'):
                raise ValueError('origin_integrity')
    return raw['origins']


def _save_origins(directory,origins):
    store._write(directory/'origins.json',dict(schema_version=1,origins=origins,sha256=store._hash(origins)))


def _report(target, inputs, previous, now, directory):
    symbol=target['symbol']; rows=inputs['prices_by_symbol'].get(symbol) or []
    if not rows or not isinstance(inputs.get('input_fingerprint'),str) or re.fullmatch('[0-9a-f]{64}',inputs['input_fingerprint']) is None:
        raise ValueError('symbol_inputs_unavailable')
    scan=discovery.discover_opportunities({symbol:rows},names={symbol:target['name']},
        as_of=inputs['latest_session'],reference_calendar=inputs.get('reference_calendar'))
    audit_hash=store._hash(scan)
    candidate=deepcopy(scan['candidates'][0]) if scan['candidates'] else _fallback(target,rows,scan)
    candidate['name']=target['name']
    quality=deepcopy(inputs.get('quality') or dict(status='unavailable',reasons=['financial_quality_unavailable']))
    if quality.get('status') not in {'passed','blocked','unavailable'} or not isinstance(quality.get('reasons'),list):
        raise ValueError('quality_unavailable')
    fingerprint=inputs['input_fingerprint']
    origins=_origins(directory)
    origin_identity=inputs.get('origin_identity') or store._hash(dict(symbol=symbol,rows=rows,
        calendar=inputs.get('reference_calendar'),quality=quality))
    original=origins.get(origin_identity)
    if original is None:
        if (previous.get('_report') or {}).get('origin_identity')==origin_identity:
            raise ValueError('origin_evidence_missing')
        original=dict(decision_at=inputs.get('decision_at') or now,proposal_window=deepcopy(inputs.get('proposal_window')),
                      captured_at=inputs['provenance'].get('captured_at'))
        if len(origins)>=128:raise ValueError('origin_capacity')
        origins[origin_identity]=original
        _save_origins(directory,origins)
    incoming=inputs.get('proposal_window')
    first_window=original.get('proposal_window') or {}
    if (first_window.get('entry_session') and isinstance(incoming,dict) and incoming.get('entry_session')
            and any(first_window.get(key)!=incoming.get(key) for key in ('entry_session','valid_until'))):
        original['calendar_revision']=True
        _save_origins(directory,origins)
    if (not (original.get('proposal_window') or {}).get('entry_session') and isinstance(incoming,dict)
            and incoming.get('entry_session') and incoming.get('valid_until')):
        sealed=deepcopy(incoming)
        sealed['origin_at']=original['decision_at']
        original['proposal_window']=sealed
        _save_origins(directory,origins)
    window=deepcopy(original.get('proposal_window'))
    if not isinstance(window,dict):
        window=dict(policy_version='next-session-proposal-v1',input_fingerprint=fingerprint,
            origin_at=original['decision_at'],entry_session=None,valid_until=None,calendar_source='KIS:CTCA0903R')
    # Rebind the separately audited calculation to an inherited sealed source
    # window, preserving its first origin and deadline instead of extending it.
    window['opportunity_audit_hash']=audit_hash
    window['input_fingerprint']=fingerprint
    public_scan={key:deepcopy(value) for key,value in scan.items() if key not in {'candidates','audit'}}
    confirmed=inputs.get('calendar_confirmed_at') or inputs.get('official_calendar',{}).get('captured_at')
    checked=_timestamp(confirmed)
    calendar_current=checked is not None and checked<=_timestamp(now) and checked.astimezone(KST).date()==_timestamp(now).astimezone(KST).date()
    public_scan.update(audit_hash=audit_hash,status='ready' if inputs.get('status')=='ready' and quality['status']=='passed'
        and not original.get('calendar_revision') and calendar_current else 'held')
    proposal_provenance=deepcopy(inputs['provenance'])
    proposal_provenance['captured_at']=original.get('captured_at') or proposal_provenance.get('captured_at')
    report=dict(schema_version=1,mode='research',decision_at=original['decision_at'],latest_session=inputs['latest_session'],
        input_fingerprint=fingerprint,universe=deepcopy(inputs['universe']),provenance=proposal_provenance,
        candidates=[],buy_candidates=[candidate],opportunity_scan=public_scan,proposal_window=window,
        calendar_confirmed_at=confirmed,origin_identity=origin_identity,
        warnings=list(dict.fromkeys([*inputs.get('warnings',[]),*inputs.get('reasons',[])])))
    if original.get('calendar_revision'):report['warnings'].append('official_calendar_revision')
    diagnostics=[]
    for item in scan['audit']:
        if item.get('strategy_id') not in discovery.STRATEGIES:continue
        diagnostics.append(dict(strategy_id=item['strategy_id'],setup_active=item['setup_active'],reasons=item['reasons'],
            calibration=deepcopy(item['calibration']['summary']) if item.get('calibration') else None,
            confirmation=deepcopy(item['confirmation']['summary']) if item.get('confirmation') else None))
    provenance=inputs['provenance']
    if _timestamp(provenance.get('captured_at')) is None:raise ValueError('source_capture_unavailable')
    result=dict(candidate=candidate,latest_session=inputs['latest_session'],analyzed_at=now,input_fingerprint=fingerprint,
        source=dict(mode=inputs.get('source_mode','saved_snapshot'),captured_at=provenance['captured_at'],
            price_basis=provenance.get('price_basis','unknown'),price_adjustment_verified=provenance.get('price_adjustment_verified') is True,
            historical_vintage_verified=provenance.get('historical_vintage_verified') is True,
            point_in_time_universe_verified=provenance.get('point_in_time_universe_verified') is True),
        quality=quality,diagnostics=diagnostics,warnings=list(dict.fromkeys([*report['warnings'],*scan['warnings']])),
        stages=[dict(id='identity',label='종목 확인',state='complete'),
            dict(id='sources',label='가격·출처 확인',state='complete' if inputs.get('status')=='ready' else 'held'),
            dict(id='quality',label='현재 재무 품질',state='complete' if quality['status']=='passed' else 'held'),
            dict(id='setup',label='조건별 과거 순손익',state='complete' if scan['candidates'] else 'held'),
            dict(id='risk',label='ATR·켈리 비중',state='complete' if scan['candidates'] else 'held'),
            dict(id='session',label='공식 진입 거래일',state='complete' if window.get('entry_session') and calendar_current
                and not original.get('calendar_revision') else 'held')])
    state='ready' if present_status(dict(state='held',report=report),now=now)['report']['buy_candidates'][0]['proposal']['action']=='buy' else 'held'
    status=_empty(target,state,now=now);status.update(result=result,_report=report)
    return status


def _execute(target, directory, now, *, live_clock=False):
    previous=_read(directory,target,now)
    try:
        inputs=acquire_inputs(target,root=directory,now=now)
        if live_clock:now=store.timestamp()
        status=_report(target,inputs,previous,now,directory)
        _save(directory,status)
    except Exception:
        status=dict(previous,state='failed',generated_at=now,error='symbol_analysis_unavailable')
        _save(directory,status)
    return _project(status,now)


def _lock(root):
    base=Path(root) if root is not None else ROOT
    base.mkdir(parents=True,exist_ok=True)
    return FileLock(str(base/'analysis.lock'),thread_local=False)


def _running(target,directory,now):
    previous=_read(directory,target,now)
    status=dict(previous,state='running',generated_at=now,error=None)
    _save(directory,status)
    return _project(status,now)


def analyze_once(symbol, *, root=None, now=None):
    target=resolve_target(symbol);stamp=store.timestamp(now);directory=_directory(root,symbol)
    try:
        with _lock(root).acquire(timeout=0):
            return _execute(target,directory,stamp,live_clock=now is None)
    except Timeout:
        return _busy(target,directory,stamp)


def _busy(target,directory,now):
    status=_read(directory,target,now)
    if status['state']!='running':status=dict(status,state='failed',error='analysis_busy')
    return _project(status,now)


def start_analysis(symbol):
    target=resolve_target(symbol);directory=_directory(None,symbol);lock=_lock(None)
    try:lock.acquire(timeout=0)
    except Timeout:return _busy(target,directory,store.timestamp())
    try:
        status=_running(target,directory,store.timestamp())
        def run():
            try:_execute(target,directory,store.timestamp(),live_clock=True)
            finally:lock.release()
        threading.Thread(target=run,name='admin-symbol-alpha',daemon=True).start()
        return status
    except Exception:
        lock.release()
        raise
