"""Bounded optional price context cannot alter sealed trade guidance."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest


def evidence():
    identity = dict(input_fingerprint='a'*64, source_audit_hash='b'*64, latest_session='2026-10-02')
    def row(symbol, rank):
        return dict(symbol=symbol, name='관측종목'+symbol, rank=rank, status='ready',
            reference_price=100., ret_21=.15, ret_63=.3, from_high_252=-.1, trend_quality=.5,
            checks=dict(top3=rank <= 3, fresh=True, trend=True, near_high=True),
            points=4 if rank <= 3 else 3, available_checks=4, reasons=[])
    return dict(policy_version='quality-leadership-context-v1', **identity, status='ready',
        cohort=dict(inspected=10, valid=10, above_ma200=8, strict_trend=5),
        market=dict(basis='quality_cohort_price_breadth', state='broad', ratio=.8),
        selected=[row('000001',2),row('000002',4)], watchlist=[row('000003',1),row('000004',3),row('000005',5)])


def binding():
    return dict(input_fingerprint='a'*64, source_audit_hash='b'*64, latest_session='2026-10-02',
                candidates=[dict(symbol='000001'),dict(symbol='000002')])


def project(value):
    from app.services.mirofish.alpha_lab.leadership_evidence import public_leadership_context
    return public_leadership_context(value, binding())


def test_context_is_bound_and_deep_copied():
    value=evidence(); original=deepcopy(value)
    result=project(value)
    assert result==original
    result['selected'][0]['checks']['fresh']=False
    assert value==original
    json.dumps(result,allow_nan=False)


def test_safe_selected_display_labels_align_after_helper_name_fallback():
    from app.services.mirofish.alpha_lab.leadership_evidence import public_leadership_context
    value=evidence(); board=binding()
    board['candidates'][0]['name']='가'*90
    board['candidates'][1]['name']='  기존 종목명  '
    value['selected'][0]['name']='000001'
    value['selected'][1]['name']='기존 종목명'
    result=public_leadership_context(value,board)
    assert [row['name'] for row in result['selected']]==[row['name'] for row in board['candidates']]
    assert value['selected'][0]['name']=='000001'


@pytest.mark.parametrize('change',[
    lambda v:v.update(input_fingerprint='c'*64),
    lambda v:v.update(latest_session='2026-10-01'),
    lambda v:v['market'].update(ratio=.7),
    lambda v:v['market'].update(state='weak'),
    lambda v:v['selected'][0].update(points=3),
    lambda v:v['selected'][0].update(available_checks=3),
    lambda v:v['selected'][0].update(reference_price=float('nan')),
    lambda v:v['selected'][0].update(ret_21=float('inf')),
    lambda v:v['selected'][0].update(rank=1.5),
    lambda v:v['selected'][0]['checks'].update(fresh=False),
    lambda v:v['selected'].reverse(),
    lambda v:v['watchlist'][0].update(symbol='000001'),
    lambda v:v['watchlist'][0]['checks'].update(trend=False),
    lambda v:v['cohort'].update(strict_trend=11),
    lambda v:v['selected'][0].update(name='C:/private/.env'),
    lambda v:v['selected'][0].update(reasons=['Bearer secret']),
])
def test_invalid_context_is_dropped_without_promoting_it(change):
    value=evidence(); change(value)
    assert project(value) is None


def test_private_extensions_are_dropped_at_every_nested_boundary():
    value=evidence()
    for row in [value,value['cohort'],value['market'],*value['selected'],*value['watchlist'],
                *[r['checks'] for r in [*value['selected'],*value['watchlist']]]]:
        row['private_path']='C:/private/.env'
    result=project(value)
    assert result is not None
    assert 'private' not in json.dumps(result)


def test_thin_cohort_remains_unknown_not_clear_market():
    value=evidence(); value.update(status='unavailable',watchlist=[])
    value['cohort']=dict(inspected=7,valid=7,above_ma200=6,strict_trend=5)
    value['market'].update(state='unknown',ratio=None)
    for row in value['selected']:
        row.update(rank=None,points=3,available_checks=3)
        row['checks']['top3']=None
    assert project(value)==value


def test_zero_volatility_keeps_undefined_quality_unknown():
    value=evidence(); row=value['selected'][0]
    row.update(trend_quality=None,rank=None,points=2,reasons=['undefined_trend_quality'])
    row['checks'].update(top3=False,trend=False)
    assert project(value)==value
    row['reasons']=[]
    assert project(value) is None


def _saved_fixture():
    spec=importlib.util.spec_from_file_location('leadership_saved_fixture',
        Path(__file__).with_name('test_alpha_lab_decision_engine.py'))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.saved()


def test_projection_preserves_trade_identity_and_price_guidance():
    from app.services.mirofish.alpha_lab.decision_engine import project_opportunity_board
    status,snapshot=_saved_fixture()
    baseline=project_opportunity_board(status,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    value=evidence(); value['selected']=value['selected'][:1]
    value['selected'][0]['symbol']=status['report']['opportunity_board']['candidates'][0]['symbol']
    # Align annotation identities and order to every existing selected candidate.
    template=deepcopy(value['selected'][0]); value['selected']=[]
    for candidate in status['report']['opportunity_board']['candidates']:
        row=deepcopy(template); row.update(symbol=candidate['symbol'],name=candidate['name'],rank=None,points=3)
        row['checks']['top3']=False
        row['checks']['trend']=False; row['points']=2
        value['selected'].append(row)
    value['watchlist']=[]
    status['report']['opportunity_board']['leadership_context']=value
    actual=project_opportunity_board(status,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    board=actual['opportunity_engine']
    assert board['leadership_context']==value
    assert board['candidates']==baseline['opportunity_engine']['candidates']
    assert board['decision_id']==baseline['opportunity_engine']['decision_id']
    twice=project_opportunity_board(actual,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert twice['opportunity_engine']['leadership_context']==value
    assert twice['opportunity_engine']['candidates']==board['candidates']


def test_bad_optional_context_does_not_erase_the_original_candidates():
    from app.services.mirofish.alpha_lab.decision_engine import project_opportunity_board
    status,snapshot=_saved_fixture()
    status['report']['opportunity_board']['leadership_context']=dict(private_path='C:/private/.env')
    actual=project_opportunity_board(status,now='2026-10-05T01:05:00Z',quote_snapshot=snapshot)
    assert len(actual['opportunity_engine']['candidates'])==3
    assert 'leadership_context' not in actual['opportunity_engine']
    assert 'private' not in json.dumps(actual)
