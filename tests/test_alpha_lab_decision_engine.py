"""Research challenger ranking and pure, sealed quote entry projection."""
from copy import deepcopy
from datetime import date, timedelta
import importlib
import json
import math

import pytest


def engine():
    try:
        return importlib.import_module('app.services.mirofish.alpha_lab.decision_engine')
    except ModuleNotFoundError:
        pytest.fail('the pure opportunity ranking and projector are not implemented')


def phase(values, start, end):
    start_day = date.fromisoformat(start)
    trades = []
    for i, value in enumerate(values):
        signal = start_day + timedelta(days=3*i)
        trades.append(dict(status='closed', signal_date=signal.isoformat(),
            entry_date=(signal+timedelta(days=1)).isoformat(),
            exit_date=(signal+timedelta(days=2)).isoformat(),
            net_return=value+.004, stress_net_return=value))
    net = [value+.004 for value in values]
    summary = dict(samples=len(values), wins=sum(v > 0 for v in net), losses=sum(v < 0 for v in net),
        zeros=0, mean_net_return=sum(net)/len(net), stress_mean_net_return=sum(values)/len(values),
        compounded_trade_return=math.prod(1+v for v in net)-1,
        stress_compounded_trade_return=math.prod(1+v for v in values)-1,
        start=start, end=end, last_exit_session=trades[-1]['exit_date'])
    return dict(summary=summary, trades=trades, open_trades=[], diagnostics={})


def fixture():
    values = {'000001': [.04, -.006]*20, '000002': [.038, -.006]*20,
              '000003': [.037, -.006]*20, '000004': [.22, -.11]*20}
    prices, candidates, audit = {}, [], []
    first = date(2026, 7, 24)
    for symbol, outcomes in values.items():
        cal = phase(outcomes, '2022-01-03', '2025-01-02')
        conf = phase([.025, -.006]*6, '2025-01-03', '2026-10-02')
        candidate = dict(symbol=symbol, name='종목'+symbol, strategy_id='momentum',
            setup_active=True, last_close=100., quote_session='2026-10-02',
            plan=dict(status='ready', entry_price=100., stop_price=92., target_price=116.,
                      atr=4., loss_fraction=.08, gain_fraction=.16),
            risk=dict(weight=0., status='held'), reasons=[],
            evidence=dict(selection_basis='calibration_stress_mean_then_confirmation',
                retrospective=True, independent_validation=False, stronger_evidence=False,
                calibration=deepcopy(cal['summary']), confirmation=deepcopy(conf['summary'])))
        candidates.append(candidate)
        audit.append(dict(symbol=symbol, strategy_id='momentum', setup_active=True,
                          selected=True, eligible=True, calibration=cal, confirmation=conf, reasons=[]))
        closes = [100.]
        for i in range(70):
            movement = .005*math.sin(i*.7)+.001
            closes.append(closes[-1]*(1+(movement if symbol in {'000001','000002'} else -movement)))
        closes = [v*100/closes[-1] for v in closes]
        prices[symbol] = [dict(symbol=symbol, date=(first+timedelta(days=i)).isoformat(),
            open=c, high=c+1., low=c-1., close=c, volume=1000.) for i,c in enumerate(closes)]
    discovery = dict(policy_version='quality-setup-opportunity-v1',
        selection_basis='calibration_stress_mean_then_confirmation', latest_session='2026-10-02',
        inspected_count=4, eligible_count=4, candidates=candidates, audit=audit,
        horizon_sessions=10, lookback_sessions=1260, calibration_sessions=1008,
        confirmation_sessions=252, cost_stress_multiplier=2., reasons=[])
    report = dict(schema_version=1, mode='research', latest_session='2026-10-02',
        decision_at='2026-10-02T09:45:00Z', input_fingerprint='a'*64,
        provenance=dict(captured_at='2026-10-02T09:35:00Z', price_source='KIS', source_hash='c'*64),
        universe=dict(scope_date='2026-10-02'), diagnostics={},
        opportunity_scan=dict(status='ready', audit_hash='b'*64, reasons=[]))
    return discovery, prices, report


def board():
    discovery, prices, report = fixture()
    return engine().build_opportunity_board(discovery, prices, report, now='2026-10-02T10:00:00Z'), report


def saved():
    raw, report = board()
    report['opportunity_board'] = raw
    report['proposal_window'] = dict(policy_version='next-session-proposal-v1',
        input_fingerprint='a'*64, opportunity_audit_hash='b'*64,
        origin_at='2026-10-02T09:45:00Z', entry_session='2026-10-05',
        valid_until='2026-10-05T06:30:00Z', calendar_source='KIS:CTCA0903R')
    snapshot = dict(decision_id=raw['decision_id'], input_fingerprint='a'*64,
        source_audit_hash='b'*64, observed_at='2026-10-05T01:05:00Z',
        calendar=dict(status='ready', source='KIS:CTCA0903R', market_state='open',
            checked_at='2026-10-05T00:00:00Z', entry_session='2026-10-05',
            valid_until='2026-10-05T06:30:00Z'), quotes={})
    for candidate in raw['candidates']:
        snapshot['quotes'][candidate['symbol']] = dict(symbol=candidate['symbol'], price=101.,
            opening_price=99., quote_at='2026-10-05T01:04:30Z',
            fetched_at='2026-10-05T01:05:00Z', source='KIS:J:FHKST03010200+FHKST01010100', status='ready')
    return dict(state='held', report=report), snapshot


def test_uncertainty_and_causal_correlation_reorder_all_survivors():
    actual, _ = board()
    assert actual['coverage'] == dict(inspected=4, eligible=4, selected=3)
    assert [r['symbol'] for r in actual['candidates']] == ['000001','000003','000002']
    assert actual['candidates'][2]['ranking']['correlation_penalty'] == pytest.approx(.01)
    assert actual['alternatives'][0]['symbol'] == '000004'
    assert actual['candidates'][0]['ranking']['standard_error'] == pytest.approx(.023/math.sqrt(39))
    assert actual['candidates'][0]['ranking']['conservative_score'] == pytest.approx(.017-1.96*.023/math.sqrt(39))


def test_future_prices_and_confirmation_profit_size_cannot_change_ranking():
    discovery, prices, report = fixture()
    expected = engine().build_opportunity_board(discovery, prices, report, now='2026-10-02T10:00:00Z')
    for symbol, rows in prices.items():
        rows.append(dict(symbol=symbol,date='2026-10-03',close=float('nan')))
    for row in discovery['audit']:
        row['confirmation'] = phase([.8,-.006]*6,'2025-01-03','2026-10-02')
    actual = engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:00:00Z')
    assert [r['ranking'] for r in actual['candidates']] == [r['ranking'] for r in expected['candidates']]
    assert [r['symbol'] for r in actual['candidates']] == [r['symbol'] for r in expected['candidates']]


def test_unknown_correlation_is_explicit_and_is_not_treated_as_independent():
    discovery, prices, report = fixture()
    prices['000003'] = prices['000003'][-5:]
    actual = engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:00:00Z')
    row = next(r for r in actual['candidates'] if r['symbol']=='000003')
    assert 'correlation_unavailable' in row['reasons']
    assert row['ranking']['correlation_penalty'] >= .005


def test_nonpositive_conservative_score_is_explicitly_exploratory():
    discovery,prices,report=fixture()
    for row in discovery['audit']:
        # A smaller sample makes the same positive mean uncertainty dominated.
        row['calibration']=phase([.19,-.11]*15,'2022-01-03','2025-01-02')
    actual=engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:00:00Z')
    assert actual['candidates']
    assert all(row['ranking']['conservative_score']<0 for row in actual['candidates'])
    assert all('탐색적 참고' in row['why_stock'] for row in actual['candidates'])
    assert all('uncertainty_adjusted_score_nonpositive' in row['audit']['reasons'] for row in actual['candidates'])


def test_reference_kelly_is_recomputed_capped_and_never_published_as_probability():
    actual, _ = board()
    assert sum(r['reference_weight'] for r in actual['candidates']) <= .15+1e-12
    for row in actual['candidates']:
        assert 0 < row['reference_weight'] <= .05
        assert row['reference_weight'] == min(.25*row['kelly']['raw_fraction'],.05,.01/.08)
        assert row['audit']['independent_validation'] is False
        assert 'p' not in row['kelly'] and 'win_rate' not in row['ranking']
    assert actual['research_only'] is True and actual['live_orders'] is False
    json.dumps(actual,allow_nan=False)


def test_rescan_clock_does_not_change_stable_decision_identity():
    discovery,prices,report=fixture()
    first=engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:00:00Z')
    report['decision_at']='2026-10-02T10:30:00Z'
    later=engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:30:00Z')
    assert first['decision_id']==later['decision_id']
    assert [r['opportunity_id'] for r in first['candidates']]==[r['opportunity_id'] for r in later['candidates']]


@pytest.mark.parametrize('malformation',['future_trade','nan_trade','failed_confirmation','stale_source','missing_fingerprint'])
def test_bad_evidence_and_bad_source_hold_guidance(malformation):
    discovery,prices,report=fixture()
    if malformation=='future_trade':
        for row in discovery['audit']: row['calibration']['trades'][0]['exit_date']='2026-10-03'
    elif malformation=='nan_trade':
        for row in discovery['audit']: row['calibration']['trades'][0]['stress_net_return']=float('nan')
    elif malformation=='failed_confirmation':
        for row in discovery['audit']: row['confirmation']=phase([-.02,.005]*6,'2025-01-03','2026-10-02')
    elif malformation=='stale_source': report['provenance']['captured_at']='2026-09-01T00:00:00Z'
    else: report.pop('input_fingerprint')
    actual=engine().build_opportunity_board(discovery,prices,report,now='2026-10-02T10:00:00Z')
    assert actual['status']=='held'
    assert not any(r['action']=='entry_candidate' for r in actual['candidates'])


def test_sparse_legacy_fixture_has_no_board_and_projector_is_pure():
    status=dict(state='held',report=dict(buy_candidates=[]))
    assert engine().project_opportunity_board(status,now='2026-10-05T01:05:00Z')==status
    source,snapshot=saved();before=deepcopy(source);quotes_before=deepcopy(snapshot)
    result=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert source==before and snapshot==quotes_before and result is not source
    assert result['report']['opportunity_board']['candidates'][0]['plan']==source['report']['opportunity_board']['candidates'][0]['plan']
    assert result['opportunity_engine']['evaluation']['basis']=='issued_opportunities_not_fills'
    assert 'win_rate' not in result['opportunity_engine']['evaluation']


def test_entry_requires_current_saved_quote_and_uses_current_price_not_open_fill():
    source,snapshot=saved()
    result=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert result['status']=='ready' and result['entry_session']=='2026-10-05'
    assert all(r['action']=='entry_candidate' for r in result['candidates'])
    for row in result['candidates']:
        assert row['current_price']==101. and row['plan']['entry_low']==101.
        assert row['plan']['basis']=='observed_quote_reference'
        assert row['source_at']=='2026-10-02T09:35:00Z'
        assert row['quote_at']=='2026-10-05T01:04:30Z'


@pytest.mark.parametrize('mutation',['identity','fingerprint','audit','calendar','calendar_stale','source','future','stale','lag','symbol','failed','nan'])
def test_malformed_or_unbound_quote_never_becomes_entry(mutation):
    source,snapshot=saved();symbol=source['report']['opportunity_board']['candidates'][0]['symbol']
    row=snapshot['quotes'][symbol]
    if mutation=='identity':snapshot['decision_id']='f'*64
    elif mutation=='fingerprint':snapshot['input_fingerprint']='f'*64
    elif mutation=='audit':snapshot['source_audit_hash']='f'*64
    elif mutation=='calendar':snapshot['calendar']['source']='local_weekdays'
    elif mutation=='calendar_stale':snapshot['calendar']['checked_at']='2026-10-02T00:00:00Z'
    elif mutation=='source':row['source']='cache'
    elif mutation=='future':row['quote_at']='2026-10-05T01:06:00Z'
    elif mutation=='stale':row['fetched_at']='2026-10-05T00:55:00Z';row['quote_at']='2026-10-05T00:54:30Z'
    elif mutation=='lag':row['quote_at']='2026-10-05T01:02:00Z'
    elif mutation=='symbol':row['symbol']='999999'
    elif mutation=='failed':row['status']='held'
    else:row['price']=float('nan')
    result=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert result['candidates'][0]['action']=='data_check'


@pytest.mark.parametrize('price',[103.,92.,116.])
def test_outside_chase_cap_or_stop_or_target_is_skipped(price):
    source,snapshot=saved();symbol=source['report']['opportunity_board']['candidates'][0]['symbol']
    snapshot['quotes'][symbol]['price']=price
    result=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert result['candidates'][0]['action']=='skip'


def test_expiry_and_window_mutation_cannot_renew_original_entry():
    source,snapshot=saved()
    first=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert first['opportunity_engine']['valid_until']=='2026-10-05T06:30:00Z'
    expired=engine().project_opportunity_board(first,now='2026-10-05T06:30:00Z',quote_snapshot=snapshot)
    assert all(r['action']!='entry_candidate' for r in expired['opportunity_engine']['candidates'])
    first['report']['proposal_window']['entry_session']='2026-10-06'
    first['report']['proposal_window']['valid_until']='2026-10-06T06:30:00Z'
    changed=engine().project_opportunity_board(first,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert changed['opportunity_engine']['valid_until']=='2026-10-05T06:30:00Z'
    assert all(row['action']=='data_check' for row in changed['opportunity_engine']['candidates'])


@pytest.mark.parametrize('reason',['opportunity_engine_unavailable','opportunity_store_recovered','opportunity_store_unavailable'])
def test_saved_engine_or_store_failure_blocks_all_new_guidance(reason):
    source,snapshot=saved()
    source['report']['opportunity_board']['reasons'].append(reason)
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert actual['status']=='held' and all(row['action']=='data_check' for row in actual['candidates'])


@pytest.mark.parametrize('mutation',['missing_weight','missing_plan','nan_ranking','foreign_binding','plan_edit'])
def test_malformed_saved_rows_hold_without_crashing_or_exposing_entry(mutation):
    source,snapshot=saved()
    row=source['report']['opportunity_board']['candidates'][0]
    if mutation=='missing_weight':row.pop('reference_weight')
    elif mutation=='missing_plan':row.pop('plan')
    elif mutation=='nan_ranking':row['ranking']['score']=float('nan')
    elif mutation=='foreign_binding':row['decision_id']='f'*64
    else:row['plan']['entry_high']=110.
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert actual['status']=='held'
    assert not any(row['action']=='entry_candidate' for row in actual['candidates'])
    json.dumps(actual,allow_nan=False)


def test_private_internal_extensions_do_not_leak_in_nested_public_fields():
    source,snapshot=saved()
    raw=source['report']['opportunity_board']
    raw['private_path']='C:/private/research.json'
    for field in ('plan','ranking','kelly','audit'):
        raw['candidates'][0][field]['private_path']='C:/private/research.json'
    raw['coverage']['private_path']='C:/private/research.json'
    raw['evaluation']=dict(basis='issued_opportunities_not_fills',issued=3,pending=3,expired=0,observed=0,unobserved=0,private_path='C:/private/research.json')
    raw['stages'][0]['private_path']='C:/private/research.json'
    raw['alternatives'][0]['private_path']='C:/private/research.json'
    original=deepcopy(source)
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert source==original
    assert actual['report']['opportunity_board']['candidates'][0]['plan']['entry_low']==100.
    assert 'C:/private' not in json.dumps(actual)
    assert actual['opportunity_engine']['status']=='ready'


@pytest.mark.parametrize('shape',['invalid','empty','wrong_type'])
def test_private_raw_board_is_removed_on_every_early_return(shape):
    source,snapshot=saved()
    if shape=='invalid':source['report']['opportunity_board']=dict(schema_version=99,private_path='C:/private/invalid.json')
    elif shape=='empty':source['report']['opportunity_board']={}
    else:source['report']['opportunity_board']=['C:/private/wrong_type.json']
    original=deepcopy(source)
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert source==original and 'opportunity_board' not in actual['report']
    assert 'C:/private' not in json.dumps(actual)


@pytest.mark.parametrize('field',['candidate_action','stage_status','alternative_strategy'])
def test_nested_objects_cannot_replace_public_scalar_fields(field):
    source,snapshot=saved()
    raw=source['report']['opportunity_board']
    secret=dict(private_path='C:/private/wrong_scalar.json')
    if field=='candidate_action':raw['candidates'][0]['action']=secret
    elif field=='stage_status':raw['stages'][0]['status']=secret
    else:raw['alternatives'][0]['strategy_id']=secret
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert 'C:/private' not in json.dumps(actual)


@pytest.mark.parametrize('state',['running','failed','error'])
def test_failed_or_running_scan_blocks_current_board(state):
    source,snapshot=saved();source['state']=state
    actual=engine().project_opportunity_board(source,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)['opportunity_engine']
    assert actual['status']=='held' and all(r['action']=='data_check' for r in actual['candidates'])


def test_certified_future_session_waits_without_reading_current_quotes():
    source,snapshot=saved()
    actual=engine().project_opportunity_board(source,now='2026-10-04T01:05:00Z')['opportunity_engine']
    assert all(r['action']=='wait_next_session' for r in actual['candidates'])
    assert actual['valid_until']=='2026-10-05T06:30:00Z'


def test_discovery_limit_is_additive_and_default_bytes_remain_identical(monkeypatch):
    from tests.test_alpha_lab_discovery import controlled,bars
    discovery=controlled(monkeypatch)
    prices={f'{i:06d}':bars(symbol=f'{i:06d}') for i in range(1,5)}
    default=discovery.discover_opportunities(prices)
    full=discovery.discover_opportunities(prices,candidate_limit=100)
    assert len(default['candidates'])==3 and len(full['candidates'])==4
    full['candidates']=full['candidates'][:3]
    assert json.dumps(default,sort_keys=True,allow_nan=False)==json.dumps(full,sort_keys=True,allow_nan=False)
    for invalid in (True,0,101,1.5):
        with pytest.raises(ValueError):discovery.discover_opportunities({},candidate_limit=invalid)
