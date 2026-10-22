"""New desk first decisions remain separate from the sealed legacy experiment."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import json

import pytest


def module():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.candidate_store')
    except ModuleNotFoundError:
        pytest.fail('candidate desk persistence and projection are not implemented')


def data():
    bars=[]
    for i in range(20):
        day=(date(2026,10,2)+timedelta(days=i)).isoformat()
        bars.append(dict(symbol='005930',date=day,open=100.,high=102.,low=99.,close=101.,volume=10000.))
    return dict(prices_by_symbol={'005930':bars},names={'005930':'Samsung'},latest_session='2026-10-21',
        input_fingerprint='a'*64,provenance=dict(source_contract_hash='b'*64,price_basis='KIS:J:D:adjusted_requested',
        captured_at='2026-10-22T00:01:00Z'))


def desk():
    phase=dict(samples=40,wins=25,win_rate=.625,mean_net_return=.01,stress_mean_net_return=.005,
               block_count=6,unique_symbols=8)
    version=module().POLICY
    weight=.01 if version=='contextual-candidates-v4' else .05
    context=dict(phase,expected_net_return=.008,expected_stress_net_return=.004,
        training_end='2026-05-30',neighbors_exclude_target=True)
    return dict(schema_version=1,policy_version=version,state='ready',
        input_fingerprint='a'*64,generated_at='2026-10-22T00:02:00Z',latest_session='2026-10-21',
        entry_session='2026-10-23',valid_until='2026-10-23T06:30:00Z',
        source=dict(provider='KIS',venue='KRX',adjusted_requested=True,captured_at='2026-10-22T00:01:00Z',
                    historical_vintage_verified=False,corporate_action_adjustment_verified=False),
        candidates=[dict(symbol='005930',name='Samsung',rank=1,strength_score=80.,quote_session='2026-10-21',
            reason_facts=['Trend and relative strength'],plan=dict(entry_price=101.,entry_upper=103.02,
            stop_price=95.,target_price=113.,horizon_sessions=10,loss_fraction=1-95/101),
            risk=dict(reference_weight=weight,kelly_fraction=.25,raw_kelly=.4,adjusted_kelly=.1,
                planned_account_loss=weight*(1-95/101),approved_exposure=0.,live_orders=False),
            model_evidence=context)],
        funnel=[dict(id='inspected',label='Inspected',count=1)],evidence=dict(formation=phase,confirmation=phase),
        model=dict(name='causal-context-neighbors-v1',status='experimental',training_end='2026-05-30',
            comparison_interpretation='v3_unconditional_retrospective_control_not_v4_holdout',validation='forward_collecting'),
        reasons=[],approved_exposure=0.,live_orders=False)


def test_first_price_session_decision_is_immutable_and_uses_actual_creation_day(tmp_path):
    mod=module(); original=desk(); inputs=data()
    first=mod.publish(tmp_path,original,inputs,now=original['generated_at'])
    assert len(first['decision_id'])==64
    assert first['entry_session']=='2026-10-23'
    journal=mod.read_decisions(tmp_path)
    assert journal['records'][0]['desk']==first
    assert journal['records'][0]['created_at'].startswith('2026-10-22')
    replacement=deepcopy(original);replacement['candidates'][0]['plan']['entry_price']=200.
    # A later run cannot replace the original signal-session plan.
    assert mod.publish(tmp_path,replacement,inputs,now='2026-10-22T01:00:00Z')['decision_id']==first['decision_id']
    assert mod.read_decisions(tmp_path)['records'][0]['desk']==first
    assert not (tmp_path.parent/'detection-v2').exists()


def test_saved_projection_is_pure_and_suppresses_stale_failed_or_tampered_result(tmp_path):
    mod=module(); value=desk(); mod.publish(tmp_path,value,data(),now=value['generated_at'])
    before={p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*.json')}
    assert mod.read_public(tmp_path,now='2026-10-22T00:03:00Z')['state']=='ready'
    assert mod.read_public(tmp_path,now='2026-10-23T06:30:01Z')['state']=='held'
    assert {p.relative_to(tmp_path):p.read_bytes() for p in tmp_path.rglob('*.json')}==before
    mod.set_attempt(tmp_path,'failed',now='2026-10-22T00:04:00Z',error='source_unavailable')
    assert mod.read_public(tmp_path,now='2026-10-22T00:05:00Z')['state']=='failed'
    path=tmp_path/'decisions.json';raw=json.loads(path.read_text(encoding='utf-8'))
    raw['data']['records'][0]['desk']['candidates'][0]['plan']['target_price']=9999
    path.write_text(json.dumps(raw),encoding='utf-8')
    assert mod.read_public(tmp_path,now='2026-10-22T00:05:00Z') is None


def test_backdated_entry_or_source_contract_change_is_not_silently_accepted(tmp_path):
    mod=module(); value=desk();value['entry_session']='2026-10-22'
    with pytest.raises(ValueError):mod.publish(tmp_path,value,data(),now=value['generated_at'])
    value=desk();mod.publish(tmp_path,value,data(),now=value['generated_at'])
    other=data();other['provenance']['source_contract_hash']='c'*64
    with pytest.raises(ValueError):mod.publish(tmp_path,value,other,now='2026-10-22T01:00:00Z')


def test_consumed_volume_revision_preserves_original_forward_result(tmp_path):
    mod=module(); value=desk();inputs=data();mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    previous=mod.read_decisions(tmp_path)
    revised=deepcopy(inputs);revised['prices_by_symbol']['005930'][-1]['volume']+=1
    mod.observe(tmp_path,revised,now='2026-10-23T11:31:00Z')
    after=mod.read_decisions(tmp_path)
    assert previous==after
    report=mod.read_public(tmp_path,now='2026-10-22T01:00:00Z')
    assert report['state']=='held'
    assert 'source_revision' in report['reasons']


def test_later_observation_does_not_create_repeated_trades_for_the_old_decision(tmp_path):
    mod=module();value=desk();inputs=data();first=mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    later=deepcopy(inputs)
    later['prices_by_symbol']['005930'].append(dict(symbol='005930',date='2026-10-23',
        open=101.,high=103.,low=100.,close=102.,volume=10000.))
    mod.observe(tmp_path,later,now='2026-10-23T11:31:00Z')
    from app.services.mirofish.alpha_lab import store
    journal=store.read_journal(tmp_path/'forward'/first['decision_id'])
    assert len(journal['decisions'])==1
    assert journal['decisions'][0]['decision_date']=='2026-10-22'


def test_missing_frozen_official_entry_cannot_fill_on_later_union_session(tmp_path):
    mod=module();value=desk();inputs=data();first=mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    later=deepcopy(inputs)
    later['latest_session']='2026-10-26'
    later['prices_by_symbol']['005930'].append(dict(symbol='005930',date='2026-10-26',
        open=101.,high=120.,low=100.,close=115.,volume=10000.))
    mod.observe(tmp_path,later,now='2026-10-26T11:31:00Z')
    from app.services.mirofish.alpha_lab import store
    journal=store.read_journal(tmp_path/'forward'/first['decision_id'])
    assert journal['decisions'][0]['outcomes'][0].get('entry_date') is None
    assert mod.read_public(tmp_path,now='2026-10-26T11:32:00Z')['state']=='held'


def test_partial_current_pointer_publication_recovers_existing_original(tmp_path,monkeypatch):
    mod=module();value=desk();inputs=data();save=mod._save;failed=[]
    def once(path,body):
        if path.name=='current.json' and not failed:
            failed.append(True);raise OSError('transient rename failure')
        return save(path,body)
    monkeypatch.setattr(mod,'_save',once)
    with pytest.raises(OSError):mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    frozen=mod.read_decisions(tmp_path)['records'][0]['desk']
    mod.publish(tmp_path,value,inputs,now='2026-10-22T01:00:00Z')
    assert mod.read_public(tmp_path,now='2026-10-22T01:00:01Z')['decision_id']==frozen['decision_id']
    assert len(mod.read_decisions(tmp_path)['records'])==1


@pytest.mark.parametrize('change',['delete_bar','traded_value'])
def test_selected_evidence_deletion_or_liquidity_revision_quarantines(tmp_path,change):
    mod=module();value=desk();inputs=data();mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    later=deepcopy(inputs)
    if change=='delete_bar':later['prices_by_symbol']['005930'].pop(-2)
    else:later['prices_by_symbol']['005930'][-1]['traded_value']=123456789.
    mod.observe(tmp_path,later,now='2026-10-22T01:00:00Z')
    assert mod.read_public(tmp_path,now='2026-10-22T01:01:00Z')['state']=='held'


def test_nontradable_holding_outcome_is_preserved_but_excluded_like_historical_pool(tmp_path):
    mod=module();value=desk();inputs=data();first=mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    later=deepcopy(inputs);later['latest_session']='2026-10-27'
    for day,vol,high in [('2026-10-23',10000.,102.),('2026-10-26',0.,102.),('2026-10-27',10000.,120.)]:
        later['prices_by_symbol']['005930'].append(dict(symbol='005930',date=day,open=101.,
            high=high,low=100.,close=101.,volume=vol,tradable=vol>0))
    mod.observe(tmp_path,later,now='2026-10-27T11:31:00Z')
    from app.services.mirofish.alpha_lab import store
    outcome=store.read_journal(tmp_path/'forward'/first['decision_id'])['decisions'][0]['outcomes'][0]
    assert outcome['status']=='closed'
    assert outcome.get('evidence_excluded_nontradable') is True
    assert mod.read_public(tmp_path,now='2026-10-27T11:32:00Z')['forward']['matured']==0


def dated(created_day, *, price_day=None, cash=False):
    value, inputs=desk(),data()
    created=date.fromisoformat(created_day)
    price=date.fromisoformat(price_day) if price_day else created-timedelta(days=1)
    value.update(generated_at=created_day+'T00:02:00Z',latest_session=price.isoformat(),
        entry_session=(created+timedelta(days=1)).isoformat(),
        valid_until=(created+timedelta(days=1)).isoformat()+'T06:30:00Z')
    value['source']['captured_at']=created_day+'T00:01:00Z'
    value['candidates'][0]['quote_session']=price.isoformat()
    value['model']['training_end']=(price-timedelta(days=140)).isoformat()
    value['candidates'][0]['model_evidence']['training_end']=value['model']['training_end']
    inputs['latest_session']=price.isoformat()
    inputs['prices_by_symbol']['005930']=[dict(row,date=(price-timedelta(days=19-index)).isoformat())
        for index,row in enumerate(inputs['prices_by_symbol']['005930'])]
    if cash:value.update(state='held',candidates=[])
    return value,inputs


def test_fixed_window_counts_first_actual_created_kst_day_and_retains_cash(tmp_path,monkeypatch):
    mod=module();monkeypatch.setattr(mod,'observe',lambda *a,**k:None)
    declaration,inputs=dated('2026-10-22',cash=True)
    mod.publish(tmp_path,declaration,inputs,now=declaration['generated_at'])
    first,inputs=dated('2026-10-23',cash=True)
    mod.publish(tmp_path,first,inputs,now=first['generated_at'])
    same_day,inputs=dated('2026-10-23',price_day='2026-10-20',cash=True)
    mod.publish(tmp_path,same_day,inputs,now=same_day['generated_at'])
    records=mod.read_decisions(tmp_path)['records']
    assert [r['in_fixed_window'] for r in records]==[False,True,False]
    assert records[1]['desk']['candidates']==[]


def test_fixed_window_stops_after_sixty_distinct_actual_decision_days(tmp_path,monkeypatch):
    mod=module();monkeypatch.setattr(mod,'observe',lambda *a,**k:None)
    for offset in range(63):
        value,inputs=dated((date(2026,10,22)+timedelta(days=offset)).isoformat(),cash=True)
        mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    records=mod.read_decisions(tmp_path)['records']
    assert sum(r['in_fixed_window'] for r in records)==60
    assert records[1]['in_fixed_window'] is True
    assert records[60]['in_fixed_window'] is True
    assert records[61]['in_fixed_window'] is False and records[62]['in_fixed_window'] is False


@pytest.mark.parametrize('remove_pointer',[False,True])
def test_old_price_session_replay_preserves_or_repairs_newest_pointer(tmp_path,monkeypatch,remove_pointer):
    mod=module();calls=[]
    monkeypatch.setattr(mod,'observe',lambda *a,**k:calls.append(a[1]['latest_session']))
    first,inputs=dated('2026-10-22');original=mod.publish(tmp_path,first,inputs,now=first['generated_at'])
    later,new_inputs=dated('2026-10-23');newest=mod.publish(tmp_path,later,new_inputs,now=later['generated_at'])
    if remove_pointer:(tmp_path/'current.json').unlink()
    calls.clear()
    assert mod.publish(tmp_path,first,inputs,now='2026-10-23T01:00:00Z')['decision_id']==original['decision_id']
    assert mod._load(tmp_path/'current.json')['decision_id']==newest['decision_id']
    assert calls==[]


@pytest.mark.parametrize('terminal',[False,True])
def test_deleting_consumed_session_from_all_symbols_quarantines_without_resealing_result(tmp_path,terminal):
    mod=module();value=desk();inputs=data();first=mod.publish(tmp_path,value,inputs,now=value['generated_at'])
    later=deepcopy(inputs);later['latest_session']='2026-10-27'
    for day,high in [('2026-10-23',102.),('2026-10-26',102.),('2026-10-27',120. if terminal else 102.)]:
        later['prices_by_symbol']['005930'].append(dict(symbol='005930',date=day,open=101.,high=high,low=100.,close=101.,volume=10000.))
    mod.observe(tmp_path,later,now='2026-10-27T11:31:00Z')
    from app.services.mirofish.alpha_lab import store
    directory=tmp_path/'forward'/first['decision_id']
    original=deepcopy(store.read_journal(directory)['decisions'][0]['outcomes'][0])
    assert original['status']==('closed' if terminal else 'open')
    corrupted=deepcopy(later)
    corrupted['prices_by_symbol']['005930']=[r for r in corrupted['prices_by_symbol']['005930'] if r['date']!='2026-10-26']
    mod.observe(tmp_path,corrupted,now='2026-10-28T11:31:00Z')
    assert store.read_journal(directory)['decisions'][0]['outcomes'][0]==original
    observations=mod._load(tmp_path/'observations.json')['records'][first['decision_id']]
    assert 'consumed_price_data_missing' in observations['revisions'][-1]['reasons']
    assert observations['forward']['excluded_source_revised_decision'] is True


@pytest.mark.parametrize('change',[
    lambda d:d.update(state='running'),lambda d:d.update(candidates=[]),
    lambda d:d.update(state='held'),lambda d:d['candidates'].append(deepcopy(d['candidates'][0])),
    lambda d:d['candidates'][0].update(symbol='000001'),
    lambda d:d['candidates'][0].update(quote_session='2026-10-20'),
    lambda d:d['candidates'][0]['plan'].update(entry_price=float('nan')),
    lambda d:d['candidates'][0]['plan'].update(stop_price=0.),
    lambda d:d['candidates'][0]['plan'].update(stop_price=101.),
    lambda d:d['candidates'][0]['plan'].update(entry_upper=100.),
    lambda d:d['candidates'][0]['plan'].update(target_price=103.02),
    lambda d:d['candidates'][0]['plan'].update(loss_fraction=.01),
    lambda d:d['candidates'][0]['plan'].update(horizon_sessions=5),
    lambda d:d['candidates'][0]['risk'].update(reference_weight=.06),
    lambda d:d['candidates'][0]['risk'].update(raw_kelly=2.),
    lambda d:d['candidates'][0]['risk'].update(kelly_fraction=.5),
    lambda d:d['candidates'][0]['risk'].update(adjusted_kelly=.2),
    lambda d:d['candidates'][0]['risk'].update(planned_account_loss=.9),
    lambda d:d['candidates'][0]['risk'].update(approved_exposure=.01),
    lambda d:d['candidates'][0]['risk'].update(live_orders=True),
])
def test_publication_rejects_invalid_candidate_semantics_before_first_decision(tmp_path,change):
    mod=module();value=desk();change(value)
    with pytest.raises(ValueError):mod.publish(tmp_path,value,data(),now=value['generated_at'])
    assert not (tmp_path/'decisions.json').exists()
    assert not (tmp_path/'current.json').exists()


def test_v3_global_economics_cannot_be_replaced_by_positive_context_fields(tmp_path):
    value=desk();value['policy_version']='cross-sectional-candidates-v3'
    value['evidence']['formation']['stress_mean_net_return']=-.01
    with pytest.raises(ValueError):module().publish(tmp_path,value,data(),now=value['generated_at'])


def test_v4_positive_context_is_explicitly_distinct_from_negative_v3_control(tmp_path):
    value=desk();value['policy_version']='contextual-candidates-v4'
    value['candidates'][0]['risk']['reference_weight']=.01
    value['candidates'][0]['risk']['planned_account_loss']=.01*value['candidates'][0]['plan']['loss_fraction']
    for phase in value['evidence'].values():
        phase.update(mean_net_return=-.02,stress_mean_net_return=-.03)
    result=module().publish(tmp_path,value,data(),now=value['generated_at'])
    assert result['policy_version']=='contextual-candidates-v4' and result['state']=='ready'


@pytest.mark.parametrize('change',[
    lambda d:d['model'].update(validation='retrospective'),
    lambda d:d['model'].update(training_end='2026-10-22'),
    lambda d:d['candidates'][0]['model_evidence'].update(samples=29),
    lambda d:d['candidates'][0]['model_evidence'].update(block_count=4),
    lambda d:d['candidates'][0]['model_evidence'].update(unique_symbols=4),
    lambda d:d['candidates'][0]['model_evidence'].update(expected_stress_net_return=0.),
    lambda d:d['candidates'][0]['model_evidence'].update(mean_net_return=-.01),
    lambda d:d['candidates'][0]['model_evidence'].update(neighbors_exclude_target=False),
    lambda d:d['candidates'][0]['model_evidence'].update(training_end='2026-05-31'),
    lambda d:d['candidates'][0]['model_evidence'].update(wins=99),
    lambda d:d['candidates'][0]['model_evidence'].update(win_rate=.99),
    lambda d:d['candidates'][0]['risk'].update(reference_weight=.02),
])
def test_v4_requires_finite_positive_supported_other_symbol_context(tmp_path,change):
    mod=module();value=desk();value['policy_version']='contextual-candidates-v4'
    value['candidates'][0]['risk']['reference_weight']=.01
    value['candidates'][0]['risk']['planned_account_loss']=.01*value['candidates'][0]['plan']['loss_fraction']
    change(value)
    with pytest.raises(ValueError):mod.publish(tmp_path,value,data(),now=value['generated_at'])


@pytest.mark.parametrize('score',[77.,80.])
def test_actual_detector_score_scale_and_source_close_survive_publication(tmp_path,score):
    value=desk();value['candidates'][0]['strength_score']=score
    first=module().publish(tmp_path,value,data(),now=value['generated_at'])
    assert first['candidates'][0]['strength_score']==score
    assert first['candidates'][0]['plan']['entry_price']==101.


@pytest.mark.parametrize('zero_raw',[False,True])
def test_zero_reference_weight_or_zero_kelly_cannot_publish_ready(tmp_path,zero_raw):
    value=desk();risk=value['candidates'][0]['risk']
    risk.update(reference_weight=0.,planned_account_loss=0.)
    if zero_raw:risk.update(raw_kelly=0.,adjusted_kelly=0.)
    with pytest.raises(ValueError):module().publish(tmp_path,value,data(),now=value['generated_at'])
