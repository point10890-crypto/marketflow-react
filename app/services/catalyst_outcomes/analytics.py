"""Frozen v1 descriptive close observations, never causal or execution claims."""
from bisect import bisect_right
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import math
from statistics import fmean

from app.services.surge_trace.common import clock, stamp

POLICY = 'catalyst-close-followthrough-v1'
HORIZONS = (5, 10, 20)
ENTRY_COST = .001  # fee5 + slippage5 bps
EXIT_COST = .003   # fee5 + slippage5 + tax20 bps


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def usable(rows, now):
    today=clock(now).date().isoformat()
    result={}
    for row in rows:
        try:
            value=row['close'];day=row['date']
            if (day>=today or stamp(day+'T00:00:00+09:00').date().isoformat()!=day
                    or isinstance(value,bool) or not math.isfinite(value) or value<=0
                    or row.get('fetched_at') and stamp(row['fetched_at'])>now):
                continue
            result[day]=row
        except (ValueError,KeyError,TypeError,OverflowError):
            continue
    return result


def evaluate_case(event, closes, calendar, now, *, previous=None, prepared_rows=None, verified_days=None):
    now=clock(now); rows=usable(closes,now) if prepared_rows is None else prepared_rows
    days=sorted({d for d in calendar if d<now.date().isoformat()})
    anchor=stamp(event['anchor_at']).date().isoformat()
    index=bisect_right(days,anchor)
    case={**event,'horizons':{},'price_source':'naver_closed_daily',
          'price_fetched_at':max((r.get('fetched_at') or '' for r in rows.values()),default='') or None}
    for horizon in HORIZONS:
        outcome=dict(status='pending',entry_date=None,exit_date=None,entry_price=None,exit_price=None,
                     net_return=None,gross_return=None,mfe=None,mae=None,source_revision=False)
        if days and anchor<days[0]:
            outcome['status']='missing'
        elif index<len(days):
            window=days[index:index+horizon+1]
            outcome['entry_date']=window[0]
            if len(window)==horizon+1:
                outcome['exit_date']=window[-1]
                anchor_date=stamp(event['anchor_at']).date()
                end_date=stamp(window[-1]+'T00:00:00+09:00').date()
                calendar_ok=verified_days is None or all((anchor_date+timedelta(days=i)).isoformat() in verified_days
                         for i in range((end_date-anchor_date).days+1))
                if not calendar_ok:
                    outcome['status']='blocked'
                elif any(day not in rows for day in window):
                    outcome['status']='missing'
                else:
                    values=[rows[day]['close'] for day in window]
                    # Hash consumed prices and calendar only; later fetch clocks do not revise results.
                    fingerprint=digest([(day,rows[day]['close'],rows[day].get('source'),rows[day].get('price_basis')) for day in window])
                    outcome.update(status='completed',entry_price=values[0],exit_price=values[-1],
                                   gross_return=values[-1]/values[0]-1,
                                   net_return=values[-1]*(1-EXIT_COST)/(values[0]*(1+ENTRY_COST))-1,
                                   mfe=max(values)/values[0]-1,mae=min(values)/values[0]-1,
                                   source_hash=fingerprint)
        old=(previous or {}).get('horizons',{}).get(str(horizon),{})
        if old.get('status') in {'completed','revised','blocked'} and old.get('source_hash'):
            current_hash=outcome.get('source_hash')
            different=current_hash is not None and current_hash!=old.get('source_hash')
            outcome=deepcopy(old)
            if different or old.get('source_revision'):
                outcome.update(status='revised',source_revision=True)
            else:
                outcome.update(status='completed' if current_hash else 'blocked',source_revision=False)
        case['horizons'][str(horizon)]=outcome
    return case


def support(cases, now):
    """One stock/receipt-day cohort, including losses; no news retry win inflation."""
    groups=defaultdict(list)
    now=clock(now)
    for case in cases:
        if case.get('analysis_basis')!='received' or case.get('exclusion'):
            continue
        try:
            if stamp(case['anchor_at'])>now:
                continue
            groups[case['symbol']].append(case)
        except (KeyError,TypeError,ValueError):
            continue
    result={}
    for symbol,items in groups.items():
        cohorts={}
        for case in sorted(items,key=lambda row:(row['anchor_at'],row['id'])):
            cohorts.setdefault(stamp(case['anchor_at']).date().isoformat(),case)
        matured=[c['horizons']['10']['net_return'] for c in cohorts.values()
                 if c['horizons']['10']['status']=='completed' and not c['horizons']['10']['source_revision']]
        latest=max(items,key=lambda row:(row['anchor_at'],row['id']))
        result[symbol]=dict(matured=len(matured),positive=sum(v>0 for v in matured),
                            mean_net_return=fmean(matured) if matured else None,latest=latest)
    return result


def _trend(rows, now, calendar=None):
    values=usable(rows,now);days=sorted(values)
    if len(days)<61:
        return None
    latest=days[-1]
    if (clock(now).date()-stamp(latest+'T00:00:00+09:00').date()).days>7:
        return None
    if calendar:
        expected=sorted(d for d in set(calendar) if d<=latest)[-61:]
        if latest!=max(calendar) or len(expected)<61 or days[-61:]!=expected:
            return None
    tail=[values[d] for d in days[-61:]]
    closes=[r['close'] for r in tail]
    sma20=fmean(closes[-20:]);sma60=fmean(closes[-60:]);p=closes[-1]
    if not p>sma20>sma60 or p<=closes[-6]:
        return None
    return dict(rows=tail,price=p,sma20=sma20,sma60=sma60,momentum=p/closes[-21]-1,
                session=latest,return5=p/closes[-6]-1)


def shortlist(cases, closes, now, *, limit=30):
    now=clock(now);ranked=[]
    for symbol,stat in support(cases,now).items():
        if not stat['positive'] or now-stamp(stat['latest']['anchor_at'])>timedelta(days=30):
            continue
        trend=_trend(closes.get(symbol,[]),now)
        if trend:
            ranked.append((trend['momentum'],symbol))
    return [s for _,s in sorted(ranked,key=lambda row:(-row[0],row[1]))[:limit]]


def rank_candidates(cases, prices, now, calendar, *, limit=3):
    now=clock(now);candidates=[]
    for symbol,stat in support(cases,now).items():
        saved=prices.get(symbol)
        if not stat['positive'] or not saved or now-stamp(stat['latest']['anchor_at'])>timedelta(days=30):
            continue
        try:
            captured=stamp(saved['captured_at'])
            if captured>now or now-captured>timedelta(hours=96):
                continue
            trend=_trend(saved['bars'],now,calendar)
            if not trend or any(row.get('quality_flags') or row.get('volume',0)<=0 for row in trend['rows']):
                continue
            tail=trend['rows'];vol=fmean(r['volume'] for r in tail[-21:-1]);relative=tail[-1]['volume']/vol
            turnover=fmean(r.get('traded_value',0) for r in tail[-20:])
            if not math.isfinite(turnover) or turnover<1_000_000_000 or not math.isfinite(relative):
                continue
            atr=fmean(max(tail[i]['high']-tail[i]['low'],abs(tail[i]['high']-tail[i-1]['close']),
                          abs(tail[i]['low']-tail[i-1]['close'])) for i in range(len(tail)-14,len(tail)))
            price=trend['price'];risk=min(atr*2,price*.08)
            if risk<=0 or not math.isfinite(risk):
                continue
            # Fixed descriptive priorities, deliberately not a calibrated profit probability.
            score=round(40*min(max(trend['momentum'],0)/.2,1)+30*min(relative/2,1)
                        +20*stat['positive']/stat['matured']+10*min(stat['matured']/10,1),2)
            latest=stat['latest']
            candidates.append(dict(symbol=symbol,name=latest['name'],rank=0,score=score,
                reasons=[f"과거 수신일 기준 10거래일 비용차감 상승 {stat['positive']}/{stat['matured']}개 관측",
                         f"종가 > 20일 평균 > 60일 평균 · 최근 5거래일 {trend['return5']*100:+.1f}%",
                         f"최근 거래량/직전 20일 평균 {relative:.2f}배"],
                invalidation=[f"종가가 20일 평균 {trend['sma20']:,.0f}원 아래로 내려가면 추세 재검토",
                              '새 부정 공시·재료 정정 또는 참고 손절 이탈 시 후보 무효'],
                price=price,price_session=trend['session'],price_fetched_at=captured.isoformat(),
                plan=dict(entry_price=price,stop_price=round(price-risk,2),target_price=round(price+2*risk,2)),
                historical={k:stat[k] for k in ('matured','positive','mean_net_return')},
                latest_event={k:latest.get(k) for k in ('title','url','first_seen_at','verification')}))
        except (ValueError,TypeError,KeyError,ZeroDivisionError):
            continue
    result=sorted(candidates,key=lambda row:(-row['score'],row['symbol']))[:limit]
    for rank,row in enumerate(result,1):
        row['rank']=rank
    return result
