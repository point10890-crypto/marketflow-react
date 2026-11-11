"""Private, paginated reads of the saved historical catalyst ledger."""
import re
import sqlite3
from flask import request
from app.routes.kongming_catalyst import _allowed, _project, _response
from app.services.catalyst_outcomes import service

NUMBER=(int,float)
HORIZON={'status':str,'entry_date':str,'exit_date':str,'entry_price':NUMBER,'exit_price':NUMBER,
         'net_return':NUMBER,'gross_return':NUMBER,'mfe':NUMBER,'mae':NUMBER,'source_revision':bool}
FIELDS={
    'schema_version':int,'status':str,'generated_at':str,'as_of_session':str,
    'schedule':{'timezone':str,'times':[str],'next_run_at':str,'slot':str},
    'coverage':{key:int for key in ('events_total','symbols_total','priced_symbols','matured_events',
                                  'positive_events','unpriced_events','excluded_events')},
    'operation':{'state':str,'last_attempt_at':str,'pending_symbols':int,'error':str},
    'candidates':[{'symbol':str,'name':str,'rank':int,'score':NUMBER,'reasons':[str],'invalidation':[str],
                   'price':NUMBER,'price_session':str,'price_fetched_at':str,
                   'plan':{'entry_price':NUMBER,'stop_price':NUMBER,'target_price':NUMBER},
                   'historical':{'matured':int,'positive':int,'mean_net_return':NUMBER},
                   'latest_event':{'title':str,'url':str,'first_seen_at':str,'verification':str}}],
    'cases':[{'id':str,'symbol':str,'name':str,'title':str,'url':str,'source':str,'event_type':str,
              'published_at':str,'first_seen_at':str,'anchor_at':str,'analysis_basis':str,'verification':str,'exclusion':str,
              'horizons':{str(n):HORIZON for n in (5,10,20)},'price_source':str,'price_fetched_at':str}],
    'pagination':{'page':int,'page_size':int,'total':int,'pages':int},'limitations':[str],
}


def catalyst_outcomes_response():
    if not _allowed():
        return _response({'error':'kongming_catalyst_forbidden'},403)
    if (set(request.args)-{'page','page_size','symbol','filter'}
            or any(len(v)!=1 for _,v in request.args.lists()) or request.get_data(cache=True).strip()):
        return _response({'error':'invalid_catalyst_outcome_query'},400)
    try:
        page=request.args.get('page','1');size=request.args.get('page_size','10')
        if not re.fullmatch(r'[0-9]{1,7}',page) or not re.fullmatch(r'[0-9]{1,2}',size):
            raise ValueError()
        args=dict(page=int(page),page_size=int(size),symbol=request.args.get('symbol'),filter=request.args.get('filter','rising'))
        if (not 1<=args['page']<=1000000 or not 1<=args['page_size']<=50 or args['filter'] not in {'all','rising'}
                or args['symbol'] is not None and not re.fullmatch(r'[0-9]{6}',args['symbol'])):
            raise ValueError()
    except ValueError:
        return _response({'error':'invalid_catalyst_outcome_query'},400)
    try:
        raw=service.read_view(**args)
        if raw.get('schema_version')!=1: raise ValueError('schema')
        payload=_project(raw,FIELDS)
        counts=raw.get('coverage',{}).get('source_counts',{})
        payload['coverage']['source_counts']={k:v for k,v in counts.items()
            if re.fullmatch(r'[a-z_]{1,40}',k) and type(v) is int and v>=0}
    except (OSError,sqlite3.Error,ValueError,KeyError,TypeError,AttributeError,RecursionError):
        return _response({'error':'catalyst_outcomes_unavailable'},503)
    return _response(payload,200)
