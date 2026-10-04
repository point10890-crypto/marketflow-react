"""Audited cached-first inputs and bounded acquisition of one selected KR stock.

The selected security has its own current listing/financial check. It is never
represented as TOP100 membership; collection writes only the admin symbol root.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from importlib import import_module
import hashlib
from pathlib import Path

from . import service, store
from .opportunities import proposal_window
from .proposals import _timestamp, KST


def _fresh(inputs, now):
    current=_timestamp(now)
    capture=_timestamp(inputs.get('provenance',{}).get('captured_at'))
    try:
        session=date.fromisoformat(inputs['latest_session'])
        scope=date.fromisoformat(inputs['universe']['scope_date'])
    except (ValueError,TypeError,KeyError):return False
    today=current.astimezone(KST).date()
    return (capture is not None and capture<=current and current-capture<=timedelta(days=7)
        and 0<=(today-session).days<=7 and 0<=(today-scope).days<=7
        and inputs.get('status')=='ready' and not inputs.get('reasons'))


def _canonical(now):
    try:
        inputs=service.load_inputs(*service.resolve_inputs(service.ROOT),as_of=_timestamp(now).astimezone(KST).date().isoformat())
        attempt=store._read(service.ROOT/'inputs'/'last_attempt.json')
        if isinstance(attempt,dict) and attempt.get('status')=='failed':
            inputs['status']='held';inputs['reasons'].append('source_refresh_failed')
        return inputs
    except (OSError,ValueError,KeyError,TypeError):return None


def acquire_inputs(target, *, root, now):
    inputs=_canonical(now);symbol=target['symbol']
    if inputs and symbol in inputs['prices_by_symbol'] and _fresh(inputs,now):
        value=deepcopy(inputs)
        value['reference_calendar']=sorted({row['date'] for rows in inputs['prices_by_symbol'].values() for row in rows})
        value['prices_by_symbol']={symbol:deepcopy(inputs['prices_by_symbol'][symbol])}
        value['names']={symbol:target['name']};value['quality']=dict(status='passed',reasons=[])
        value['source_mode']='saved_snapshot'
        value.pop('proposal_window',None)
        try:
            report=(service.read_status() or {}).get('report') or {}
            if report.get('input_fingerprint')==inputs['input_fingerprint']:
                value['decision_at']=report.get('decision_at')
                origin,until=proposal_window(report)
                if origin is not None and until is not None:
                    value['proposal_window']=deepcopy(report['proposal_window'])
                    value['calendar_confirmed_at']=now
        except (OSError,ValueError,KeyError,TypeError):pass
        current=_timestamp(now).astimezone(KST)
        weekday_closed=current.date() if current.time().replace(tzinfo=None)>=time(15,30) else current.date()-timedelta(days=1)
        while weekday_closed.weekday()>=5:weekday_closed-=timedelta(days=1)
        if not value.get('proposal_window') or inputs['latest_session']<weekday_closed.isoformat():
            try:
                calendar,closed=_calendar(now)
            except Exception:
                value['status']='held'
                value['reasons']=list(dict.fromkeys([*value.get('reasons',[]),'official_calendar_unavailable']))
                value['warnings']=list(dict.fromkeys([*value.get('warnings',[]),'official_calendar_unavailable']))
            else:
                if closed!=inputs['latest_session']:
                    return _collect(target,root=root,now=now,canonical=inputs,calendar_context=(calendar,closed))
                value['decision_at']=value.get('decision_at') or now
                value['proposal_window']=_window(calendar,inputs['latest_session'],value['decision_at'],inputs['input_fingerprint'])
                value['official_calendar']=calendar
                value['calendar_confirmed_at']=calendar['captured_at']
                store._write(Path(root)/'sources'/'calendar.json',dict(data=calendar,sha256=store._hash(calendar)))
        return value
    try:
        saved=store._read(Path(root)/'sources'/'inputs.json')
        cached=saved['inputs'] if isinstance(saved,dict) and 'inputs' in saved else None
        if not (cached is not None and saved.get('sha256')==store._hash(cached)
                and set(cached.get('prices_by_symbol',{}))=={symbol} and _fresh(cached,now)
                and cached.get('quality',{}).get('status')=='passed'):cached=None
    except (OSError,ValueError,KeyError,TypeError):cached=None
    if cached is not None:
        current=_timestamp(now).astimezone(KST)
        calendar=cached.get('official_calendar') or {}
        captured=_timestamp(calendar.get('captured_at'))
        if captured is None or captured>_timestamp(now) or captured.astimezone(KST).date()!=current.date():
            try:calendar,closed=_calendar(now)
            except Exception:
                held=deepcopy(cached);held['status']='held'
                held['reasons']=list(dict.fromkeys([*held.get('reasons',[]),'official_calendar_unavailable']))
                return held
        else:
            cutoff=current.date() if current.time().replace(tzinfo=None)>=time(15,30) else current.date()-timedelta(days=1)
            closed=max((row['date'] for row in calendar.get('days',[]) if row['is_open'] and row['date']<=cutoff.isoformat()),default=None)
        if closed==cached['latest_session']:
            value=deepcopy(cached);value['official_calendar']=calendar;value['calendar_confirmed_at']=calendar['captured_at']
            value['proposal_window']=_window(calendar,value['latest_session'],value['decision_at'],value['input_fingerprint'])
            store._write(Path(root)/'sources'/'inputs.json',dict(inputs=value,sha256=store._hash(value)))
            return value
        return _collect(target,root=root,now=now,canonical=inputs,calendar_context=(calendar,closed))
    return _collect(target,root=root,now=now,canonical=inputs)


def _calendar(now):
    from .market_provider import KISMarketProvider, CALENDAR_SOURCE
    current=_timestamp(now);today=current.astimezone(KST).date();base=today-timedelta(days=10)
    raw=KISMarketProvider().fetch_calendar(base.isoformat(),now)
    capture=_timestamp(raw.get('captured_at'))
    if raw.get('source')!=CALENDAR_SOURCE or capture is None or capture>current or capture.astimezone(KST).date()!=today:
        raise ValueError('calendar_unavailable')
    rows=raw.get('days')
    if not isinstance(rows,list) or not rows or len(rows)>370:raise ValueError('calendar_unavailable')
    dates={}
    for row in rows:
        day=date.fromisoformat(row['date'])
        if day.isoformat()!=row['date'] or day in dates or not isinstance(row['is_open'],bool):raise ValueError('calendar_invalid')
        dates[day]=row['is_open']
    last_closed=today if current.astimezone(KST).time().replace(tzinfo=None)>=time(15,30) else today-timedelta(days=1)
    possible=[day for day,opened in dates.items() if opened and day<=last_closed]
    if not possible or min(dates)>base or max(dates)<today:raise ValueError('calendar_unavailable')
    first,last=min(dates),max(dates)
    if len(dates)!=(last-first).days+1:raise ValueError('calendar_gap')
    return raw,max(possible).isoformat()


def _window(calendar, latest, now, fingerprint):
    current=_timestamp(now);origin=current.astimezone(KST).date()
    dates={date.fromisoformat(row['date']):row['is_open'] for row in calendar['days']}
    next_session=None
    for offset in range(1,8):
        day=date.fromisoformat(latest)+timedelta(days=offset)
        if day not in dates:break
        if dates[day]:next_session=day;break
    if next_session is None or next_session<=origin:return None
    return dict(policy_version='next-session-proposal-v1',input_fingerprint=fingerprint,
        opportunity_audit_hash='0'*64,origin_at=now,entry_session=next_session.isoformat(),
        valid_until=datetime.combine(next_session,time(15,30),KST).astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
        calendar_source='KIS:CTCA0903R')


def _stable_quality(result):
    financial=deepcopy(result.get('financial'))
    if isinstance(financial,dict):financial.pop('fetched_at',None)
    return dict(status=result.get('quality_pass'),reason=result.get('reason'),debt_ratio=result.get('debt_ratio'),financial=financial)


def _price_capture(prices, symbol, params, root, now):
    """Keep a completed exact-request price stage while retrying missing stages."""
    directory=Path(root)/'sources'/'prices'
    try:
        previous=store._read(directory/'capture.json')
        if isinstance(previous,dict) and previous.get('request_params')==params:
            captured=_timestamp(previous.get('captured_at'))
            raw_hash=previous.get('raw_sha256')
            if (captured is not None and timedelta(0)<=_timestamp(now)-captured<timedelta(days=1)
                    and isinstance(raw_hash,str) and len(raw_hash)==64
                    and all(char in '0123456789abcdef' for char in raw_hash)):
                path=directory/f'{raw_hash}.txt'
                if path.is_file() and path.stat().st_size<=5*1024*1024:
                    payload=path.read_bytes()
                    if hashlib.sha256(payload).hexdigest()==raw_hash:
                        return dict(payload=payload,captured_at=previous['captured_at'],http_status=previous.get('http_status'))
    except (OSError,ValueError,KeyError,TypeError):pass
    capture=prices.fetch_payload(symbol,params)
    if (not isinstance(capture,dict) or not isinstance(capture.get('payload'),bytes)
            or len(capture['payload'])>5*1024*1024 or _timestamp(capture.get('captured_at')) is None
            or _timestamp(capture['captured_at'])>_timestamp(store.timestamp())):
        raise ValueError('price_capture_invalid')
    raw_hash=hashlib.sha256(capture['payload']).hexdigest()
    prices.atomic_write(directory/f'{raw_hash}.txt',capture['payload'])
    store._write(directory/'capture.json',dict(request_params=params,raw_sha256=raw_hash,
        captured_at=capture['captured_at'],http_status=capture.get('http_status')))
    return capture


def _collect(target, *, root, now, canonical=None, calendar_context=None):
    # Existing collectors use fixed public URLs and sanitize DART transport
    # failures. Credential configuration remains internal to that collector.
    prices=import_module('scripts.collect_large_cap_price_history')
    screening=import_module('scripts.screen_large_cap_kelly')
    refresh=import_module('scripts.refresh_alpha_lab_inputs')
    from ..large_cap_universe import evaluate_quality
    root=Path(root);symbol=target['symbol'];current=_timestamp(now)
    calendar=None;calendar_reason=[]
    try:calendar,as_of=calendar_context or _calendar(now)
    except Exception:
        as_of=refresh.latest_closed_weekday(current)
        calendar_reason=['official_calendar_unavailable']
    start='2005-01-01'
    params=dict(symbol=symbol,requestType='1',startTime=start.replace('-',''),endTime=as_of.replace('-',''),timeframe='day')
    capture=_price_capture(prices,symbol,params,root,now)
    fetched=_timestamp(capture.get('captured_at'))
    if fetched is None or fetched>_timestamp(store.timestamp()):raise ValueError('price_capture_invalid')
    parsed=prices.parse_payload(capture['payload'],start,as_of)
    raw_hash=hashlib.sha256(capture['payload']).hexdigest()
    bars=[];excluded=0
    for raw in parsed['bars']:
        if (min(raw['open'],raw['high'],raw['low'],raw['close'])<=0
                or not raw['low']<=min(raw['open'],raw['close'])<=max(raw['open'],raw['close'])<=raw['high']):
            excluded+=1;continue
        bars.append(dict(symbol=symbol,**{key:raw[key] for key in ('date','open','high','low','close','volume')}))
    if not bars:raise ValueError('price_history_unavailable')
    latest=bars[-1]['date']
    selected=[];listing_reason=None
    try:
        listing_path=screening.fetch_listing(as_of,root)
        if listing_path.stat().st_size>5*1024*1024:raise ValueError('listing_capacity')
        listing,_=screening.load_listing(listing_path,as_of)
        selected=[row for row in listing if row['symbol']==symbol]
        if len(selected)!=1:raise ValueError('listing_identity_unavailable')
    except Exception:
        selected=[];listing_reason='current_listing_unavailable'
    year,report_code=refresh._period(as_of,None,None)
    repo=Path(__file__).resolve().parents[4]
    quality=dict(status='unavailable',reasons=[listing_reason or 'financial_quality_unavailable']);quality_evidence={}
    financial_capture=[]
    try:
        if not selected:raise ValueError('current_listing_unavailable')
        financials,evidence=screening.fetch_financials({symbol},mapping_path=repo/'data'/'dart_corp_codes.json',
            env_file=repo/'.env',year=year,report_code=report_code,out=root)
        checked=evaluate_quality(selected,financials,as_of)['results'][0]
        quality=dict(status='passed' if checked['quality_pass'] else 'blocked',
            reasons=[] if checked['quality_pass'] else [checked['reason']])
        quality_evidence=_stable_quality(checked);financial_capture=evidence.get('fetched_at_by_batch',[])
        if quality['status']=='passed' and (not financial_capture or any(_timestamp(value) is None for value in financial_capture)):
            quality=dict(status='unavailable',reasons=['financial_source_capture_invalid'])
    except Exception:pass
    reference=sorted({row['date'] for rows in (canonical or {}).get('prices_by_symbol',{}).values() for row in rows if row['date']<=latest})
    if not reference:
        reference=[row['date'] for row in bars];calendar_reason.append('historical_calendar_unverified')
    else:
        reference=sorted(set(reference)|{row['date'] for row in bars})
    if calendar:
        reference=sorted(set(reference)|{row['date'] for row in calendar['days'] if row['is_open'] and row['date']<=latest})
    origin_identity=store._hash(dict(symbol=symbol,bars=bars,calendar=reference,quality=quality_evidence))
    fingerprint=store._hash(dict(raw_sha256=raw_hash,listing=selected,quality=quality_evidence))
    actual_capture=store.timestamp()
    reasons=list(calendar_reason)
    if latest!=as_of:reasons.append('stale_prices')
    if fetched<datetime.combine(date.fromisoformat(latest),time(15,30),KST).astimezone(timezone.utc):
        reasons.append('price_capture_before_session_close')
    capture_times=[fetched,*[_timestamp(value) for value in financial_capture]]
    capture_times=[value for value in capture_times if value is not None]
    if any(value>_timestamp(actual_capture) for value in capture_times):raise ValueError('future_source_capture')
    provenance=dict(price_basis=prices.PRICE_BASIS,price_adjustment_verified=False,historical_vintage_verified=False,
        point_in_time_universe_verified=False,analysis_ready=False,current_cohort_bias=False,
        captured_at=max(capture_times).isoformat().replace('+00:00','Z'),price_source=prices.SOURCE)
    value=dict(status='held' if reasons else 'ready',reasons=reasons,latest_session=latest,prices_by_symbol={symbol:bars},
        names={symbol:target['name']},input_fingerprint=fingerprint,origin_identity=origin_identity,
        reference_calendar=reference,quality=quality,provenance=provenance,source_mode='targeted_collection',
        universe=dict(scope_date=as_of,selection='administrator_selected_symbol',inspected_count=1),
        warnings=['historical_vintage_unverified','corporate_action_adjustment_unverified','administrator_selected_cohort_retrospective'],
        decision_at=actual_capture,official_calendar=calendar or {},calendar_confirmed_at=(calendar or {}).get('captured_at'))
    if excluded:value['warnings'].append('invalid_ohlcv_excluded')
    if calendar:value['proposal_window']=_window(calendar,latest,actual_capture,fingerprint)
    store._write(root/'sources'/'inputs.json',dict(inputs=value,sha256=store._hash(value)))
    return value
