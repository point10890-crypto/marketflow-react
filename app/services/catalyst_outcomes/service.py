"""Resumable twice-daily research snapshots; GET never acquires or fits."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
import time

from filelock import FileLock, Timeout
from app.utils.paths import DATA_DIR
from app.services.surge_trace.common import clock
from . import analytics

ROOT=Path(DATA_DIR)/'catalyst_outcomes'
KST=timezone(timedelta(hours=9))
LIMITATIONS=[
    '보존된 기사·검증 기록만 조사합니다. 시장의 모든 과거 뉴스가 아닙니다.',
    '과거 수익은 수신일 다음 거래일 종가 기준 관측입니다. 재료가 상승 원인임을 입증하지 않습니다.',
    '수수료·슬리피지 각각 5bp, 매도세금 20bp 가정. 실제 체결·계좌 수익이 아닙니다.',
    '과거 가격은 제공자 수정종가이며 당시 데이터·기업행사 검증은 미완료입니다.',
    '과거 NAVER 수정종가와 현재 KIS 일봉은 가격 기준이 달라 동일 날짜의 가격도 다를 수 있습니다.',
    '현재 종목 목록에 연결되는 보존 자료만 사용하므로 상장폐지·이름 변경 종목의 생존 편향이 남습니다.',
    '기사 중복과 같은 종목의 중첩 관측은 독립 표본이 아닙니다. 선정 점수는 상승 확률이 아닙니다.',
    '현재 후보는 KIS의 마지막 완료 일봉 참고값이며 실시간 시세·주문·승인을 제공하지 않습니다.',
]


def schedule(now=None):
    current=clock(now);date=current.date()
    slots=[datetime.combine(date+timedelta(days=offset),datetime.min.time(),KST).replace(hour=hour)
           for offset in (-1,0,1) for hour in (10,15)]
    return dict(timezone='Asia/Seoul',times=['10:00','15:00'],
                slot=max(s for s in slots if s<=current).isoformat(),
                next_run_at=min(s for s in slots if s>current).isoformat())


def _json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))


def _connect(root, *, write=False):
    path=Path(root)/'outcomes.sqlite3'
    if write:
        Path(root).mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(path,timeout=2)
        db.executescript('''CREATE TABLE IF NOT EXISTS cases (
            id TEXT PRIMARY KEY,symbol TEXT NOT NULL,anchor TEXT NOT NULL,
            positive INTEGER NOT NULL,matured INTEGER NOT NULL,payload TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS cases_page ON cases(positive,anchor DESC,id);
            CREATE INDEX IF NOT EXISTS cases_symbol ON cases(symbol,anchor DESC);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (slot TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY,slot TEXT NOT NULL,payload TEXT NOT NULL);''')
        return db
    if not path.exists():
        return None
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.5)
    db.execute('PRAGMA query_only=ON')
    return db


def _meta(db,key,default=None):
    row=db.execute('SELECT payload FROM meta WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(db,key,value):
    db.execute('INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',(key,_json(value)))


def _empty(now):
    return dict(schema_version=1,status='missing',generated_at=None,as_of_session=None,schedule=schedule(now),
                coverage=dict(events_total=0,symbols_total=0,priced_symbols=0,matured_events=0,positive_events=0,
                              unpriced_events=0,excluded_events=0,source_counts={}),
                operation=dict(state='waiting',last_attempt_at=None,pending_symbols=0,error=None),
                candidates=[],cases=[],pagination=dict(page=1,page_size=10,total=0,pages=0),limitations=LIMITATIONS)


def read_view(*,root=ROOT,now=None,page=1,page_size=10,symbol=None,filter='rising'):
    if (type(page)!=int or page<1 or page>1000000 or type(page_size)!=int or not 1<=page_size<=50
            or filter not in {'all','rising'} or symbol is not None and re.fullmatch(r'[0-9]{6}',symbol) is None):
        raise ValueError('invalid_catalyst_outcome_query')
    now=clock(now);view=_empty(now);view['pagination'].update(page=page,page_size=page_size)
    db=_connect(root)
    if db is None:
        return view
    try:
        saved=_meta(db,'snapshot')
        if saved:
            view.update(saved)
        view['schedule']=schedule(now)
        view['operation']=_meta(db,'attempt',view['operation'])
        if view['operation']['state']=='failed':
            view['status']='failed'
        elif saved and saved.get('schedule',{}).get('slot')!=view['schedule']['slot']:
            view['status']='stale'
        clauses=[];args=[]
        if filter=='rising': clauses.append('positive=1')
        if symbol: clauses.append('symbol=?');args.append(symbol)
        where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        total=db.execute('SELECT COUNT(*) FROM cases'+where,args).fetchone()[0]
        rows=db.execute('SELECT payload FROM cases'+where+' ORDER BY anchor DESC,id LIMIT ? OFFSET ?',
                        [*args,page_size,(page-1)*page_size]).fetchall()
        view['cases']=[json.loads(row[0]) for row in rows]
        # Private hashes exist only in the ledger, never the wire representation.
        for case in view['cases']:
            for horizon in case['horizons'].values(): horizon.pop('source_hash',None)
        view['pagination']=dict(page=page,page_size=page_size,total=total,pages=(total+page_size-1)//page_size)
        return view
    finally:
        db.close()


def _reconcile(previous,events,diagnostics,tombstones):
    from .sources import event_keys, is_withdrawn
    merged={key:{k:v for k,v in row.items() if k not in {'horizons','price_source','price_fetched_at'}}
            for key,row in previous.items()}
    aliases={}
    for identity,event in merged.items():
        keys=event.get('_aliases',[])+event_keys(event)
        event['_aliases']=list({tuple(k) for k in keys})
        for key in event['_aliases']: aliases.setdefault(tuple(key),set()).add(identity)
    for event in events:
        keys=diagnostics.get('identity_aliases',{}).get(event['id'],event_keys(event))
        matches=set().union(*(aliases.get(tuple(key),set()) for key in keys)) if keys else set()
        canonical=min(matches,key=lambda key:(merged[key]['anchor_at'],key)) if matches else event['id']
        prior=merged.get(canonical)
        if prior:
            # First observed identity/clock is fixed even if a later archive supplies earlier receipts.
            original=('id','symbol','name','title','url','source','event_type','published_at',
                      'anchor_at','first_seen_at','analysis_basis')
            update={**event,**{k:prior[k] for k in original if k in prior}}
            if prior.get('exclusion'): update['exclusion']=prior['exclusion']
            if ' '.join(prior['title'].split())!=' '.join(event['title'].split()):
                update['exclusion']='source_revised'
        else:
            update=dict(event)
        allkeys=set(map(tuple,keys))
        for identity in matches:
            allkeys.update(map(tuple,merged[identity].get('_aliases',[])))
            if identity!=canonical: merged[identity]['exclusion']='duplicate'
        update['_aliases']=list(allkeys);merged[canonical]=update
        for key in allkeys: aliases[key]={canonical}
    for event in merged.values():
        if is_withdrawn(event,{'withdrawn_keys':tombstones}): event['exclusion']='withdrawn'
    return list(merged.values())


def _calculate(db,project,root,now,provider,deadline,live=False):
    from . import sources,prices
    events,source_diagnostics=sources.load_events(project,now)
    previous={row[0]:json.loads(row[1]) for row in db.execute('SELECT id,payload FROM cases')}
    tombstones=list(set(map(tuple,_meta(db,'withdrawn_keys',[])+source_diagnostics.get('withdrawn_keys',[]))))
    events=_reconcile(previous,events,source_diagnostics,tombstones)
    symbols={e['symbol'] for e in events}
    closes,price_diagnostics=prices.load_closes(project,symbols,now)
    end=(now.date()-timedelta(days=1)).isoformat() if events else None
    calendar_diag=dict(calendar_sessions=[],calendar_confirmed_days={},calendar_verified=not events)
    if events and end:
        start=min(min(e['anchor_at'][:10] for e in events),(now.date()-timedelta(days=150)).isoformat())
        calendar_diag=prices.acquire_calendar(root,start,end,now,deadline=deadline,seed=price_diagnostics)
    calendar=sorted({d for d in calendar_diag.get('calendar_sessions',[]) if d<now.date().isoformat()})
    verified_days=calendar_diag.get('calendar_confirmed_days',{})
    prepared={symbol:analytics.usable(rows,now) for symbol,rows in closes.items()}
    cases=[analytics.evaluate_case(e,[],calendar,now,previous=previous.get(e['id']),
            prepared_rows=prepared.get(e['symbol'],{}),verified_days=verified_days) for e in events]
    targets=analytics.shortlist(cases,closes,now)
    end=calendar[-1] if calendar else None
    current={};current_diag=dict(pending_symbols=0,errors={})
    if targets and end:
        current,current_diag=prices.load_current_prices(project,targets,end,now,root,provider=provider,
                                                        deadline=deadline,max_fetch=12)
    decision_at=clock() if live else now
    picks=analytics.rank_candidates(cases,current,decision_at,calendar) if calendar_diag.get('calendar_verified') else []
    pending=current_diag.get('pending_symbols',0)
    if isinstance(pending,list): pending=len(pending)
    incomplete=(source_diagnostics.get('status') not in {'ready','complete','ok'}
                or price_diagnostics.get('status') not in {'ready','complete','ok'}
                or not calendar_diag.get('calendar_verified')
                or bool(end and closes and max(r['date'] for rows in closes.values() for r in rows)<end)
                or bool(pending) or bool(current_diag.get('errors')))
    # A fully read upstream partial snapshot is a coverage caveat, not a failed
    # local stage. Re-reading millions of unchanged rows every five minutes
    # cannot repair that producer; inspect its new snapshot at the next slot.
    upstream_only=bool(incomplete and source_diagnostics.get('sources')
        and all(row.get('status')=='ready' or row.get('status')=='partial' and row.get('error')=='upstream_partial'
                for row in source_diagnostics['sources'].values())
        and price_diagnostics.get('status') in {'ready','complete','ok'}
        and calendar_diag.get('calendar_verified') and not pending and not current_diag.get('errors')
        and (not end or not closes or max(r['date'] for rows in closes.values() for r in rows)>=end))
    operation=dict(state='complete_with_gaps' if upstream_only else 'partial' if incomplete else 'complete',
                   last_attempt_at=now.isoformat(),pending_symbols=pending,
                   error='source_coverage_partial' if upstream_only else None)
    matured=[c for c in cases if c['horizons']['10']['status']=='completed' and not c.get('exclusion')]
    positives=[c for c in matured if c['horizons']['10']['net_return']>0]
    matured_ids={c['id'] for c in matured};positive_ids={c['id'] for c in positives}
    limitations=list(LIMITATIONS)
    if upstream_only:
        names={'verification':'공시 검증','businesspost':'기사 수집','omni':'종합 뉴스','surge_trace':'급등 역추적'}
        affected=[names.get(key,key) for key,row in source_diagnostics['sources'].items() if row.get('status')=='partial']
        limitations.append('·'.join(affected)+' 원본의 일부 단계는 미완료입니다. 현재 보존된 기록까지 분석했습니다.')
    snapshot=dict(schema_version=1,status='partial' if incomplete else 'ready',generated_at=decision_at.isoformat(),
                  as_of_session=end,schedule=schedule(now),operation=operation,candidates=picks,limitations=limitations,
                  coverage=dict(events_total=len(cases),symbols_total=len(symbols),priced_symbols=len(closes),
                                matured_events=len(matured),positive_events=len(positives),
                                unpriced_events=sum(not closes.get(c['symbol']) for c in cases),
                                excluded_events=sum(bool(c.get('exclusion')) or c['horizons']['10']['status'] in {'blocked','missing','revised'} for c in cases),
                                source_counts=source_diagnostics.get('source_counts',{})))
    with db:
        db.executemany('INSERT INTO cases VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'symbol=excluded.symbol,anchor=excluded.anchor,positive=excluded.positive,'
                       'matured=excluded.matured,payload=excluded.payload',
                       [(c['id'],c['symbol'],c['anchor_at'],int(c['id'] in positive_ids),int(c['id'] in matured_ids),_json(c)) for c in cases])
        _set(db,'snapshot',snapshot);_set(db,'attempt',operation)
        _set(db,'withdrawn_keys',tombstones)
        _set(db,'diagnostics',dict(sources=source_diagnostics,prices=price_diagnostics,calendar=calendar_diag,current_prices=current_diag))
        publication=dict(slot=snapshot['schedule']['slot'],generated_at=snapshot['generated_at'],candidates=picks)
        db.execute('INSERT OR IGNORE INTO publications VALUES (?,?,?)',
                   (analytics.digest(publication),publication['slot'],_json(publication)))
        if not incomplete or upstream_only:
            db.execute('INSERT OR IGNORE INTO runs VALUES (?,?)',(snapshot['schedule']['slot'],_json(snapshot)))
    return snapshot


def run_once(*,root=ROOT,project_root=None,now=None,provider=None,deadline=None):
    live=now is None
    root=Path(root);project=Path(project_root or Path(__file__).resolve().parents[3]);now=clock(now)
    root.mkdir(parents=True,exist_ok=True)
    lock=FileLock(str(root/'worker.lock'))
    try:
        with lock.acquire(timeout=0):
            db=_connect(root,write=True)
            try:
                policy=dict(version=analytics.POLICY,horizons=analytics.HORIZONS,
                            entry_cost=analytics.ENTRY_COST,exit_cost=analytics.EXIT_COST,
                            entry_basis='next_complete_session_close',candidate_policy='trend-confirmed-v1',
                            alias_policy='financial_punctuation_preserved_v1')
                policy_hash=analytics.digest(policy)
                if _meta(db,'policy_hash',policy_hash)!=policy_hash:
                    raise ValueError('policy_change_requires_new_ledger')
                if _meta(db,'policy_hash') is None:
                    with db:
                        _set(db,'policy_hash',policy_hash);_set(db,'policy',policy)
                slot=schedule(now)['slot']
                if db.execute('SELECT 1 FROM runs WHERE slot=?',(slot,)).fetchone():
                    return read_view(root=root,now=now)
                with db:
                    _set(db,'attempt',dict(state='running',last_attempt_at=now.isoformat(),pending_symbols=0,error=None))
                _calculate(db,project,root,now,provider,deadline or time.monotonic()+180,live=live)
            except Exception:
                with db:
                    _set(db,'attempt',dict(state='failed',last_attempt_at=now.isoformat(),pending_symbols=0,
                                           error='catalyst_outcome_refresh_failed'))
            finally:
                db.close()
    except Timeout:
        pass
    return read_view(root=root,now=now)
