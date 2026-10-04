"""Administrator symbol analysis shares calculations without global publication."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from app.models import db
import app.auth.decorators as auth
import app.routes.admin_mirofish as routes

NOW = '2026-10-04T06:00:00Z'
BASE = '/api/admin/mirofish/stock-analysis'


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='symbol-test', SQLALCHEMY_DATABASE_URI='sqlite:///:memory:')
    db.init_app(app)
    app.register_blueprint(routes.admin_mirofish_bp, url_prefix='/api/admin/mirofish')
    monkeypatch.setattr(auth, '_get_current_user', lambda: SimpleNamespace(
        id=1, email='fixture@example.test', status='approved', is_admin=True, is_aibain_active=False))
    return app.test_client()


@pytest.fixture
def provider(monkeypatch):
    value = dict(schema_version=1, policy_version='admin-symbol-alpha-v1', state='running',
                 target=dict(symbol='196170', name='알테오젠', market='KR'), generated_at=NOW, error=None, result=None)
    service = SimpleNamespace(search=Mock(return_value={'candidates': [value['target']]}),
                              start_analysis=Mock(return_value=value), read_status=Mock(return_value=value))
    monkeypatch.setattr(routes, '_stock_analysis_service', lambda: service, raising=False)
    return service


@pytest.mark.parametrize('path,method', [(BASE+'/search?q=알테오젠', 'GET'), (BASE, 'POST'), (BASE+'/196170', 'GET')])
@pytest.mark.parametrize('user,code', [(None,401),
    (SimpleNamespace(status='approved',is_admin=False,is_aibain_active=True),403),
    (SimpleNamespace(status='approved',is_admin=False,is_aibain_active=False),403),
    (SimpleNamespace(status='suspended',is_admin=True,is_aibain_active=False),403)])
def test_all_symbol_routes_are_admin_only_and_private(client, provider, monkeypatch, path, method, user, code):
    monkeypatch.setattr(auth, '_get_current_user', lambda: user)
    response = client.open(path, method=method, json={'symbol':'196170'} if method == 'POST' else None)
    assert response.status_code == code
    assert 'private' in response.headers['Cache-Control'] and 'no-store' in response.headers['Cache-Control']
    provider.search.assert_not_called(); provider.start_analysis.assert_not_called(); provider.read_status.assert_not_called()


def test_route_contract_and_saved_get(client, provider):
    assert client.get(BASE+'/search?q=알테&limit=8').json['candidates'][0]['symbol'] == '196170'
    response = client.post(BASE, json={'symbol':'196170'})
    assert response.status_code == 202
    provider.start_analysis.assert_called_once_with('196170')
    assert client.get(BASE+'/196170').json['target']['symbol'] == '196170'
    provider.read_status.assert_called_once_with('196170')


@pytest.mark.parametrize('body', [None, [], {'symbol':196170}, {'symbol':'../secret'}, {'symbol':'196170','horizon':20}, {'symbol':'19617'}, {'symbol':'196170 '}, {'symbol':'000000'}])
def test_exact_post_contract_rejects_bad_identity_before_job(client, provider, body):
    response = client.post(BASE, json=body)
    assert response.status_code == 400
    provider.start_analysis.assert_not_called()


def test_unknown_symbol_is_generic_400_and_provider_error_is_sanitized(client, provider):
    provider.start_analysis.side_effect = ValueError('unknown_symbol')
    assert client.post(BASE,json={'symbol':'999990'}).status_code == 400
    provider.read_status.side_effect = RuntimeError('private token secret')
    response = client.get(BASE+'/196170')
    assert response.status_code == 503 and 'secret' not in response.get_data(as_text=True)


def symbol_service():
    from app.services.mirofish.alpha_lab import symbol_analysis
    return symbol_analysis


def snapshot():
    from tests.test_alpha_lab_discovery import bars
    rows = bars(); shift = datetime.fromisoformat('2026-10-02').date()-datetime.fromisoformat(rows[-1]['date']).date()
    for row in rows:
        row['date'] = (datetime.fromisoformat(row['date']).date()+shift).isoformat()
        row['symbol'] = '196170'
    return dict(prices_by_symbol={'196170':rows}, names={'196170':'알테오젠'}, latest_session='2026-10-02',
        input_fingerprint='a'*64, provenance=dict(captured_at='2026-10-04T04:00:00Z',price_basis='provider_reported_unverified',
            price_adjustment_verified=False,historical_vintage_verified=False,point_in_time_universe_verified=False),
        status='ready', reasons=[], warnings=[], quality=dict(status='passed',reasons=[]),
        universe=dict(scope_date='2026-10-02'), reference_calendar=[row['date'] for row in rows],
        decision_at='2026-10-04T05:00:00Z',calendar_confirmed_at='2026-10-04T05:00:00Z', proposal_window=dict(policy_version='next-session-proposal-v1',
            input_fingerprint='a'*64,opportunity_audit_hash='b'*64,origin_at='2026-10-04T05:00:00Z',
            entry_session='2026-10-05',valid_until='2026-10-05T06:30:00Z',calendar_source='KIS:CTCA0903R'))


def test_single_symbol_parity_outside_global_three_and_no_journal_writes(monkeypatch, tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    from app.services.mirofish.alpha_lab import discovery, store
    mod = symbol_service(); controlled(monkeypatch)
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    data = snapshot(); original = deepcopy(data)
    expected = discovery.discover_opportunities(data['prices_by_symbol'],names=data['names'],as_of=data['latest_session'])['candidates'][0]
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    monkeypatch.setattr(store,'observe_and_freeze',lambda *args,**kwargs:pytest.fail('manual pipeline must not publish journal'))
    result = mod.analyze_once('196170',root=tmp_path,now=NOW)
    candidate = result['result']['candidate']
    assert candidate['symbol'] == '196170' and candidate['plan'] == expected['plan']
    assert candidate['risk'] == expected['risk']
    assert candidate['proposal']['proposed_weight'] == expected['risk']['research_weight']
    assert candidate['proposal']['action'] == 'buy' and candidate['proposal']['order_allowed'] is False
    assert data == original and not list(tmp_path.rglob('forward.json'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:pytest.fail('GET must not collect'))
    assert mod.read_status('196170',root=tmp_path,now=NOW)['result']['candidate']['plan'] == expected['plan']


def test_wait_still_has_deterministic_atr_plan_and_no_invented_probability(monkeypatch,tmp_path):
    mod = symbol_service(); data = snapshot()
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:data)
    result = mod.analyze_once('196170',root=tmp_path,now=NOW)
    candidate = result['result']['candidate']
    assert candidate['plan']['entry_price'] == 100.
    assert candidate['proposal']['action'] == 'wait' and candidate['proposal']['proposed_weight'] == 0.
    assert candidate['risk'].get('p') is None and candidate['risk'].get('kelly_raw') is None


def test_same_input_does_not_renew_expiry_and_failed_run_retains_plan_as_wait(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod = symbol_service(); controlled(monkeypatch)
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:snapshot())
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    second=mod.analyze_once('196170',root=tmp_path,now='2026-10-05T08:00:00Z')
    assert second['result']['candidate']['proposal']['valid_until'] == first['result']['candidate']['proposal']['valid_until']
    assert second['result']['candidate']['proposal']['action'] == 'wait'
    def fail(*args,**kwargs):raise RuntimeError('secret-key-private-path')
    monkeypatch.setattr(mod,'acquire_inputs',fail)
    failed=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert failed['state']=='failed' and failed['result']['candidate']['proposal']['action']=='wait'
    assert failed['result']['candidate']['plan']==first['result']['candidate']['plan']
    assert 'secret-key' not in str(failed)


def test_missing_official_window_blocks_buy_without_removing_price_plan(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service(); controlled(monkeypatch); data=snapshot(); data.pop('proposal_window')
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:data)
    result=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert result['result']['candidate']['proposal']['action']=='wait'
    assert result['result']['candidate']['plan']['entry_price']==100.


def test_later_calendar_confirmation_completes_first_origin_without_renewal(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service();controlled(monkeypatch);data=snapshot();window=data.pop('proposal_window')
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert first['result']['candidate']['proposal']['action']=='wait'
    data['decision_at']='2026-10-04T07:00:00Z';window['origin_at']=data['decision_at'];data['proposal_window']=window
    second=mod.analyze_once('196170',root=tmp_path,now='2026-10-04T07:00:00Z')
    assert second['result']['candidate']['proposal']['action']=='buy'
    assert second['result']['candidate']['proposal']['valid_until']=='2026-10-05T06:30:00Z'
    saved=mod.store._read(tmp_path/'196170'/'status.json')['status']['_report']
    assert saved['decision_at']=='2026-10-04T05:00:00Z'
    assert saved['proposal_window']['origin_at']=='2026-10-04T05:00:00Z'


def test_calendar_revision_holds_same_prices_without_replacing_original_deadline(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service();controlled(monkeypatch);data=snapshot()
    data['proposal_window'].update(entry_session='2026-10-06',valid_until='2026-10-06T06:30:00Z')
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert first['result']['candidate']['proposal']['action']=='buy'
    data['proposal_window'].update(entry_session='2026-10-05',valid_until='2026-10-05T06:30:00Z')
    second=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert second['result']['candidate']['proposal']['action']=='wait'
    assert second['result']['candidate']['proposal']['proposed_weight']==0.
    assert second['result']['candidate']['proposal']['valid_until']=='2026-10-06T06:30:00Z'
    assert second['result']['candidate']['plan']==first['result']['candidate']['plan']


def test_saved_get_requires_current_day_calendar_without_external_calls(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service();controlled(monkeypatch);data=snapshot()
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:pytest.fail('GET must not acquire'))
    next_day=mod.read_status('196170',root=tmp_path,now='2026-10-05T00:00:00Z')
    assert next_day['result']['candidate']['proposal']['action']=='wait'
    assert next_day['result']['candidate']['proposal']['valid_until']==first['result']['candidate']['proposal']['valid_until']


@pytest.mark.parametrize('corruption',[{}, {'schema_version':1,'origins':{},'sha256':'0'*64}])
def test_unsealed_or_corrupt_origins_never_reissue_saved_buy(monkeypatch,tmp_path,corruption):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service();controlled(monkeypatch);data=snapshot()
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    mod.store._write(tmp_path/'196170'/'origins.json',corruption)
    second=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert second['state']=='failed' and second['result']['candidate']['proposal']['proposed_weight']==0.
    assert second['result']['candidate']['plan']==first['result']['candidate']['plan']


def test_inherited_sealed_origin_may_precede_the_canonical_rescan_decision(monkeypatch,tmp_path):
    from tests.test_alpha_lab_discovery import controlled
    mod=symbol_service();controlled(monkeypatch);data=snapshot();data['decision_at']='2026-10-04T05:30:00Z'
    monkeypatch.setattr(mod,'resolve_target',lambda symbol:dict(symbol=symbol,name='알테오젠',market='KR'))
    monkeypatch.setattr(mod,'acquire_inputs',lambda *args,**kwargs:deepcopy(data))
    first=mod.analyze_once('196170',root=tmp_path,now=NOW)
    second=mod.analyze_once('196170',root=tmp_path,now=NOW)
    assert first['result']['candidate']['proposal']['action']=='buy'
    assert second['result']['candidate']['proposal']['action']=='buy'
    assert second['result']['candidate']['proposal']['valid_until']==first['result']['candidate']['proposal']['valid_until']


def test_explicit_reference_calendar_keeps_sparse_symbol_safety(monkeypatch):
    from tests.test_alpha_lab_discovery import bars,controlled
    discovery=controlled(monkeypatch); dense=bars(); sparse=[row for index,row in enumerate(dense) if index!=61]
    result=discovery.discover_opportunities({'005930':sparse},as_of=dense[-1]['date'],reference_calendar=[row['date'] for row in dense])
    assert result['diagnostics']['missing_next_union_quote']>=1
    assert result['diagnostics']['sparse_factor_window']>=1


@pytest.mark.parametrize('calendar', [['2026-10-02','2026-10-01'], ['2026-10-02','2026-10-02'], ['bad-date'], ['2026-10-03']])
def test_reference_calendar_is_canonical_ordered_and_covers_observed_rows(calendar):
    from tests.test_alpha_lab_discovery import bars
    from app.services.mirofish.alpha_lab import discovery
    with pytest.raises(ValueError):
        discovery.discover_opportunities({'005930':bars()},reference_calendar=calendar)
