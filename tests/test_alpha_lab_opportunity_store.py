"""Immutable issued opportunities; observations are never fills."""
from copy import deepcopy
import importlib
import importlib.util
import json

import pytest

from app.services.mirofish.alpha_lab import store

ORIGIN = '2026-10-04T05:00:00Z'
OPEN = '2026-10-06T00:05:00Z'


def module():
    name = 'app.services.mirofish.alpha_lab.opportunity_store'
    assert importlib.util.find_spec(name), 'issued-opportunity store is not implemented'
    return importlib.import_module(name)


def board():
    value = dict(schema_version=1, policy_version='profit-opportunity-v1', decision_id='d'*64,
        input_fingerprint='a'*64, source_audit_hash='b'*64, generated_at=ORIGIN,
        latest_session='2026-10-02', valid_until=None, entry_session=None, status='ready',
        research_only=True, live_orders=False, coverage=dict(inspected=6, eligible=4, selected=2),
        candidates=[dict(opportunity_id=(str(i)*64), decision_id='d'*64, input_fingerprint='a'*64,
            source_audit_hash='b'*64, symbol=symbol, name=symbol, market='KR',rank=i,strategy_id='momentum',
            action='data_check',label='데이터 확인',why_stock='완료 순수익 근거',why_now='시세 확인 대기',
            next_action='공식 다음 거래일 시세 확인',quote_session='2026-10-02',source_at='2026-10-04T04:00:00Z',
            current_price=None,quote_at=None,fetched_at=None,quote_source=None,valid_until=None,reference_weight=.05,
            ranking=dict(stress_mean_net_return=.02,standard_error=.001,conservative_score=.01804,
                correlation_penalty=0.,score=.01804,calibration_samples=40,confirmation_samples=20),
            kelly=dict(raw_fraction=2.,fraction=.25,cap=.05,account_risk_cap=.01),
            audit=dict(status='passed',reasons=[],independent_validation=False),reasons=[],
            plan=dict(basis='last_closed_price_reference', entry_low=100.,entry_high=102.,
                      stop_price=96.,target_price=108.,horizon_sessions=10))
            for i,symbol in enumerate(('196170','005930'),1)], alternatives=[], stages=[], reasons=[])
    canonical=[{key:deepcopy(row[key]) for key in ('symbol','strategy_id','rank','reference_weight',
        'plan','ranking','kelly')} for row in value['candidates']]
    value['decision_id']=store._hash(dict(policy_version='profit-opportunity-v1',input_fingerprint='a'*64,
        source_audit_hash='b'*64,latest_session='2026-10-02',candidates=canonical))
    for row in value['candidates']:
        row['decision_id']=value['decision_id']
        row['opportunity_id']=store._hash(dict(decision_id=value['decision_id'],symbol=row['symbol'],strategy_id=row['strategy_id']))
    return value


def snapshot(value=None):
    value = value or board()
    return dict(decision_id=value['decision_id'], input_fingerprint=value['input_fingerprint'],
        source_audit_hash=value['source_audit_hash'], observed_at=OPEN,
        calendar=dict(status='ready',source='KIS:CTCA0903R',checked_at=OPEN,is_open=True,market_state='open',
            entry_session='2026-10-06',valid_until='2026-10-06T06:30:00Z'),
        quotes={'196170':dict(symbol='196170',price=101.,opening_price=100.,
            quote_at='2026-10-06T00:04:30Z',fetched_at=OPEN,
            source='KIS:J:FHKST03010200+FHKST01010100')})


def test_register_is_immutable_and_replay_keeps_original_origin(tmp_path):
    mod=module(); original=board()
    assert mod.register_board(tmp_path,original)==original
    bytes_before={str(p):p.read_bytes() for p in tmp_path.rglob('*.json')}
    newer=deepcopy(original);newer['generated_at']='2026-10-06T01:00:00Z'
    assert mod.register_board(tmp_path,newer)==original
    assert bytes_before=={str(p):p.read_bytes() for p in tmp_path.rglob('*.json')}
    journal=mod.read_journal(tmp_path)
    assert len(journal['issued'])==1
    assert journal['issued'][0]['board']==original
    changed=deepcopy(original);changed['candidates'][0]['plan']['entry_high']=103.
    with pytest.raises(ValueError,match='identity'):
        mod.register_board(tmp_path,changed)
    assert mod.read_journal(tmp_path)==journal


def test_each_unknown_row_remains_unobserved_and_no_fill_or_pnl_is_created(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    status=dict(state='held',report=dict(opportunity_board=value))
    view=mod.attach_saved(status,tmp_path,now=OPEN)
    evaluation=view['report']['opportunity_board']['evaluation']
    assert evaluation==dict(basis='issued_opportunities_not_fills',issued=2,pending=0,
        expired=0,observed=1,unobserved=1)
    after=mod.attach_saved(status,tmp_path,now='2026-10-06T06:31:00Z')['report']['opportunity_board']['evaluation']
    assert after['observed']==1 and after['expired']==1
    assert 'win_rate' not in evaluation and 'net_return' not in evaluation
    assert 'fill_price' not in json.dumps(view) and 'actual_pnl' not in json.dumps(view)
    assert status['report']['opportunity_board']==value


def test_pre_session_is_pending_and_unknown_calendar_is_not_nonfill(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    before=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=ORIGIN)
    assert before['report']['opportunity_board']['evaluation']['unobserved']==2
    data=snapshot();data['observed_at']='2026-10-04T06:00:00Z'
    data['calendar'].update(checked_at=data['observed_at'],is_open=False)
    data['quotes']={}
    mod.save_quote_snapshot(tmp_path,value,data,now=data['observed_at'])
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=data['observed_at'])
    assert view['report']['opportunity_board']['evaluation']['pending']==2


def test_expiry_is_pinned_and_mismatched_source_never_saves_old_quotes(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    first=snapshot();mod.save_quote_snapshot(tmp_path,value,first,now=OPEN)
    mismatch=snapshot();mismatch['input_fingerprint']='e'*64
    with pytest.raises(ValueError,match='identity'):
        mod.save_quote_snapshot(tmp_path,value,mismatch,now=OPEN)
    moved=snapshot();moved['calendar']['entry_session']='2026-10-07'
    moved['calendar']['valid_until']='2026-10-07T06:30:00Z'
    with pytest.raises(ValueError,match='window'):
        mod.save_quote_snapshot(tmp_path,value,moved,now=OPEN)
    assert mod.read_quote_snapshot(tmp_path,value)==first


def test_corrupt_primary_journal_recovers_last_sealed_backup_without_get_writes(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    other=deepcopy(value);other['decision_id']='e'*64
    mod.register_board(tmp_path,other)
    path=tmp_path/'decision_engine'/'issued.json';path.write_text('{broken',encoding='utf-8')
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=mod.attach_saved(dict(state='held',report=dict(opportunity_board=other)),tmp_path,now=OPEN)
    assert result['report']['opportunity_board']['status']=='held'
    assert 'opportunity_store_recovered' in result['report']['opportunity_board']['reasons']
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert len(mod.read_journal(tmp_path)['issued'])==1


def test_failed_atomic_write_preserves_last_issued_journal(tmp_path,monkeypatch):
    mod=module();value=board();mod.register_board(tmp_path,value)
    previous=mod.read_journal(tmp_path)
    write=store._write
    def failing(path,data):
        if str(path).endswith('issued.json'):
            raise OSError('disk full')
        return write(path,data)
    monkeypatch.setattr(store,'_write',failing)
    other=deepcopy(value);other['decision_id']='e'*64
    with pytest.raises(OSError):mod.register_board(tmp_path,other)
    assert mod.read_journal(tmp_path)==previous


def test_quote_failure_replaces_guidance_but_preserves_observation_history(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    failed=snapshot();failed['quotes']={};failed['reasons']=['quote_unavailable']
    mod.save_quote_snapshot(tmp_path,value,failed,now=OPEN)
    assert mod.read_quote_snapshot(tmp_path,value)==failed
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=OPEN)
    assert view['report']['opportunity_board']['evaluation']['observed']==1


def test_sparse_legacy_saved_read_does_not_create_any_files(tmp_path):
    mod=module();value=dict(state='held',report=dict(schema_version=1))
    assert mod.attach_saved(value,tmp_path,now=OPEN)==value
    assert mod.read_quote_snapshot(tmp_path,None) is None
    assert not list(tmp_path.rglob('*'))


def test_deleted_primary_journal_holds_instead_of_treating_saved_quotes_as_issued(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    (tmp_path/'decision_engine'/'issued.json').unlink()
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=OPEN)
    assert result['report']['opportunity_board']['status']=='held'
    assert 'opportunity_store_recovered' in result['report']['opportunity_board']['reasons']
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('change',[dict(checked_at='2026-10-05T00:05:00Z'),
    dict(checked_at='2026-10-06T00:05:01Z'),dict(source='weekday_guess')])
def test_invalid_calendar_evidence_cannot_mark_any_quote_observed(tmp_path,change):
    mod=module();value=board();mod.register_board(tmp_path,value)
    data=snapshot();data['calendar'].update(change)
    with pytest.raises(ValueError,match='window'):
        mod.save_quote_snapshot(tmp_path,value,data,now=OPEN)
    assert mod.read_quote_snapshot(tmp_path,value) is None
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=OPEN)
    assert view['report']['opportunity_board']['evaluation']['observed']==0


def test_nonfinite_snapshot_failure_does_not_write_even_a_new_window(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    data=snapshot();data['quotes']['196170']['price']=float('nan')
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    with pytest.raises(ValueError):mod.save_quote_snapshot(tmp_path,value,data,now=OPEN)
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_swapped_sealed_observation_cannot_count_for_another_source(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    other=deepcopy(value);other.update(decision_id='e'*64,input_fingerprint='c'*64)
    mod.register_board(tmp_path,other)
    original=tmp_path/'decision_engine'/'observations'/f"{value['decision_id']}.json"
    swapped=tmp_path/'decision_engine'/'observations'/f"{other['decision_id']}.json"
    swapped.write_bytes(original.read_bytes())
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=other)),tmp_path,now=OPEN)
    assert view['report']['opportunity_board']['status']=='held'
    assert 'opportunity_store_unavailable' in view['report']['opportunity_board']['reasons']
    assert view['report']['opportunity_board']['evaluation']['observed']<=1
    with pytest.raises(ValueError,match='observation'):
        mod.save_quote_snapshot(tmp_path,other,snapshot(other),now=OPEN)
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mutation',['missing_binding','unknown_symbol','future_quote','wrong_session','future_receipt'])
def test_semantically_invalid_sealed_receipt_holds_without_get_repair(tmp_path,mutation):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    path=tmp_path/'decision_engine'/'observations'/f"{value['decision_id']}.json"
    raw=store._read(path);data=raw['data'];receipt=data['observed']['196170']
    if mutation=='missing_binding':data.pop('decision_id',None)
    if mutation=='unknown_symbol':
        data['observed']['999999']=data['observed'].pop('196170');receipt['quote']['symbol']='999999'
    if mutation=='future_quote':receipt['quote'].update(quote_at='2026-10-06T00:05:01Z',fetched_at='2026-10-06T00:05:01Z')
    if mutation=='wrong_session':receipt['quote'].update(quote_at='2026-10-05T00:04:30Z',fetched_at='2026-10-05T00:05:00Z')
    if mutation=='future_receipt':receipt['observed_at']='2026-10-06T00:05:01Z'
    raw['sha256']=store._hash(data);store._write(path,raw)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=OPEN)
    assert view['report']['opportunity_board']['status']=='held'
    assert view['report']['opportunity_board']['evaluation']['observed']==0
    assert 'opportunity_store_unavailable' in view['report']['opportunity_board']['reasons']
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_missing_established_observation_holds_without_forgetting_issued_window(tmp_path):
    mod=module();value=board();mod.register_board(tmp_path,value)
    mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    observation=tmp_path/'decision_engine'/'observations'/f"{value['decision_id']}.json"
    observation.unlink()
    assert mod.read_quote_snapshot(tmp_path,value)==snapshot()
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    view=mod.attach_saved(dict(state='held',report=dict(opportunity_board=value)),tmp_path,now=OPEN)
    assert view['report']['opportunity_board']['status']=='held'
    assert 'opportunity_store_unavailable' in view['report']['opportunity_board']['reasons']
    with pytest.raises(ValueError,match='observation'):
        mod.save_quote_snapshot(tmp_path,value,snapshot(),now=OPEN)
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
