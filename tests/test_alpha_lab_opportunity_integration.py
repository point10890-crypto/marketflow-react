"""Additive engine integration preserves old discovery and monitor identities."""
from copy import deepcopy

import pytest

from app.services.mirofish.alpha_lab import service, store, monitor
from tests.test_alpha_lab_service import _context_scan
from tests.test_alpha_lab_monitor import report, Provider, REGISTER, OPEN
from tests.test_alpha_lab_opportunity_store import board, module
from tests.test_alpha_lab_routes import client


def test_scan_passes_all_survivors_to_new_engine_before_restoring_legacy_three(tmp_path, monkeypatch):
    data, scan = _context_scan(tmp_path, monkeypatch)
    scan['candidates'] = [dict(deepcopy(scan['candidates'][0]),symbol=f'{index:06d}') for index in range(5)]
    seen={}
    def discover(*args,**kwargs):
        seen['candidate_limit']=kwargs.get('candidate_limit')
        return deepcopy(scan)
    def build(discovery,prices,report,**kwargs):
        seen['symbols']=[row['symbol'] for row in discovery['candidates']]
        return board()
    monkeypatch.setattr(service,'discover_opportunities',discover)
    monkeypatch.setattr(service,'build_opportunity_board',build,raising=False)
    result=service.scan_once(tmp_path)
    assert result['state']=='held'
    assert seen['candidate_limit']==100 and len(seen['symbols'])==5
    legacy=deepcopy(scan);legacy['candidates']=legacy['candidates'][:3]
    assert result['report']['opportunity_scan']['audit_hash']==store._hash(legacy)
    assert [row['symbol'] for row in result['report']['buy_candidates']]==['000000','000001','000002']
    original=deepcopy(store.read_journal(tmp_path/'opportunities'))
    service.scan_once(tmp_path)
    assert store.read_journal(tmp_path/'opportunities')==original
    assert len(module().read_journal(tmp_path)['issued'])==1


def test_new_engine_failure_holds_guidance_without_losing_legacy_scan(tmp_path,monkeypatch):
    _context_scan(tmp_path,monkeypatch)
    def failure(*args,**kwargs):raise ValueError('C:/private/API_KEY')
    monkeypatch.setattr(service,'build_opportunity_board',failure,raising=False)
    result=service.scan_once(tmp_path)
    assert result['state']=='held' and result['report']['buy_candidates']
    assert result['report']['opportunity_board']['status']=='held'
    assert 'private' not in str(result['report']['opportunity_board'])
    monkeypatch.setattr(service,'ROOT',tmp_path)
    view=service.read_status(now='2026-10-04T06:00:00Z')['opportunity_engine']
    assert view['status']=='held' and view['candidates']==[]
    allowed={'data','setup','critic','diversification','risk','entry'}
    assert view['stages'] and all(stage['id'] in allowed for stage in view['stages'])


def seed(root):
    value=report();value['opportunity_board']=board()
    monitor.register_report(root,value,now=REGISTER)
    store.publish(root,value,now=REGISTER,held=True)
    module().register_board(root,value['opportunity_board'])
    return value


class RecordingProvider(Provider):
    def __init__(self,**kwargs):super().__init__(**kwargs);self.symbols=[]
    def fetch_quote(self,symbol,now):
        self.symbols.append(symbol)
        return super().fetch_quote(symbol,now)


def test_monitor_fetches_new_selected_symbol_once_and_preserves_legacy_result(tmp_path):
    value=seed(tmp_path);provider=RecordingProvider()
    result=monitor.run_monitor(tmp_path,provider,now=OPEN)
    assert provider.symbols==['196170','005930']
    assert [row['symbol'] for row in result['monitoring']['quotes']]==['196170']
    assert result['paper']['matured']==0 and result['paper']['win_rate'] is None
    snapshot=module().read_quote_snapshot(tmp_path,value['opportunity_board'])
    assert snapshot['decision_id']==value['opportunity_board']['decision_id']
    assert set(snapshot['quotes'])=={'196170','005930'}
    assert snapshot['quotes']['005930']['price']==101.
    assert 'fill_price' not in str(snapshot) and 'adjusted_plan' not in snapshot['quotes']['005930']
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    monitor.attach_operations(store.read_status(tmp_path,now=OPEN),tmp_path,now=OPEN)
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_new_monitor_closed_window_makes_no_extra_quotes(tmp_path):
    value=seed(tmp_path);provider=RecordingProvider()
    monitor.run_monitor(tmp_path,provider,now=REGISTER)
    assert provider.symbols==[]
    snapshot=module().read_quote_snapshot(tmp_path,value['opportunity_board'])
    assert snapshot['calendar']['entry_session']=='2026-10-06'
    view=module().attach_saved(dict(state='held',report=value),tmp_path,now=REGISTER)
    assert view['report']['opportunity_board']['evaluation']['pending']==2


def test_report_change_during_new_quote_does_not_attach_old_quote_to_new_source(tmp_path):
    value=seed(tmp_path)
    class Racing(RecordingProvider):
        def fetch_quote(self,symbol,now):
            if symbol=='005930':
                changed=deepcopy(value);changed['input_fingerprint']='e'*64
                changed['opportunity_board']['input_fingerprint']='e'*64
                store.publish(tmp_path,changed,now=OPEN,held=True)
            return super().fetch_quote(symbol,now)
    provider=Racing();monitor.run_monitor(tmp_path,provider,now=OPEN)
    assert provider.symbols==['196170','005930']
    snapshot=module().read_quote_snapshot(tmp_path,value['opportunity_board'])
    assert snapshot is None or not snapshot['quotes']


def test_get_only_reads_saved_new_board_without_build_or_provider_calls(tmp_path,monkeypatch):
    value=seed(tmp_path)
    monitor.run_monitor(tmp_path,RecordingProvider(),now=OPEN)
    monkeypatch.setattr(service,'ROOT',tmp_path)
    def forbidden(*args,**kwargs):pytest.fail('GET attempted acquisition or mutation')
    monkeypatch.setattr(service,'run_research',forbidden)
    monkeypatch.setattr(service,'discover_opportunities',forbidden)
    monkeypatch.setattr(service,'build_opportunity_board',forbidden,raising=False)
    monkeypatch.setattr(store,'_write',forbidden)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=service.read_status(now=OPEN)
    assert result['opportunity_engine']['decision_id']==value['opportunity_board']['decision_id']
    assert result['opportunity_engine']['evaluation']['issued']==2
    assert result['opportunity_engine']['status']=='ready'
    assert len(result['opportunity_engine']['candidates'])==2
    assert all(row['action']=='entry_candidate' for row in result['opportunity_engine']['candidates'])
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_monitor_wrapper_returns_byte_identical_legacy_operations(tmp_path):
    legacy=tmp_path/'legacy';new=tmp_path/'new';seed(legacy);seed(new)
    expected=monitor._run_legacy_monitor(legacy,RecordingProvider(),now=OPEN)
    actual=monitor.run_monitor(new,RecordingProvider(),now=OPEN)
    assert actual==expected
    assert (legacy/'monitor'/'registry.json').read_bytes()==(new/'monitor'/'registry.json').read_bytes()
    assert (legacy/'monitor'/'entries.json').read_bytes()==(new/'monitor'/'entries.json').read_bytes()


def test_corrupt_new_ledger_holds_get_guidance_with_saved_quote_and_no_repair(tmp_path,monkeypatch):
    seed(tmp_path);monitor.run_monitor(tmp_path,RecordingProvider(),now=OPEN)
    monkeypatch.setattr(service,'ROOT',tmp_path)
    assert service.read_status(now=OPEN)['opportunity_engine']['status']=='ready'
    path=tmp_path/'decision_engine'/'issued.json';path.write_text('{broken',encoding='utf-8')
    monkeypatch.setattr(service,'ROOT',tmp_path)
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=service.read_status(now=OPEN)
    assert result['opportunity_engine']['status']=='held'
    assert len(result['opportunity_engine']['candidates'])==2
    assert all(row['action']=='data_check' for row in result['opportunity_engine']['candidates'])
    assert 'opportunity_store_recovered' in result['opportunity_engine']['reasons']
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_extra_quote_failure_keeps_original_result_and_holds_new_candidates(tmp_path,monkeypatch):
    value=seed(tmp_path)
    class Failing(RecordingProvider):
        def fetch_quote(self,symbol,now):
            if symbol=='005930':raise RuntimeError('credential details never public')
            return super().fetch_quote(symbol,now)
    result=monitor.run_monitor(tmp_path,Failing(),now=OPEN)
    assert result['monitoring']['status']=='ready'
    snapshot=module().read_quote_snapshot(tmp_path,value['opportunity_board'])
    assert snapshot['quotes']=={} and snapshot['reasons']==['quote_unavailable']
    monkeypatch.setattr(service,'ROOT',tmp_path)
    view=service.read_status(now=OPEN)['opportunity_engine']
    assert view['status']=='held' and all(row['action']=='data_check' for row in view['candidates'])


def _private_saved_report(root):
    value=seed(root)
    value['opportunity_board']['private_artifact']='C:/private/.env'
    value['opportunity_board']['candidates'][0]['ranking']['private_artifact']='C:/private/.env'
    store.publish(root,value,now=REGISTER,held=True)
    return value


def _fake_scan_thread(monkeypatch):
    class Immediate:
        def __init__(self,*,target,**kwargs):self.target=target
        def start(self):self.target()
    monkeypatch.setattr(service.threading,'Thread',Immediate)
    monkeypatch.setattr(service,'_execute',lambda root:None)


def test_start_scan_public_projection_removes_private_raw_board_and_blocks_running_guidance(tmp_path,monkeypatch):
    value=_private_saved_report(tmp_path);monkeypatch.setattr(service,'ROOT',tmp_path)
    _fake_scan_thread(monkeypatch)
    result=service.start_scan()
    assert result['state']=='running'
    assert 'C:/private' not in str(result)
    assert result['opportunity_engine']['status']=='held'
    assert all(row['action']=='data_check' and row['current_price'] is None for row in result['opportunity_engine']['candidates'])
    legacy={key:deepcopy(item) for key,item in value.items() if key!='opportunity_board'}
    assert {key:item for key,item in result['report'].items() if key!='opportunity_board'}==legacy
    assert store.read_status(tmp_path)['report']['opportunity_board']['private_artifact']=='C:/private/.env'


def test_busy_start_scan_redacts_saved_board_without_writing_or_fetching(tmp_path,monkeypatch):
    _private_saved_report(tmp_path);monkeypatch.setattr(service,'ROOT',tmp_path)
    class Busy:
        def acquire(self,*,timeout):raise service.Timeout('busy')
    monkeypatch.setattr(service,'_lock',lambda root:Busy())
    before={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result=service.start_scan()
    assert 'C:/private' not in str(result)
    assert result['opportunity_engine']['status']=='held'
    assert before=={str(p):p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_post_endpoint_serializes_only_public_new_board_and_retains_legacy_rows(client,tmp_path,monkeypatch):
    import app.routes.admin_mirofish as routes
    from app.services.mirofish.alpha_lab.proposals import present_status
    value=_private_saved_report(tmp_path);monkeypatch.setattr(service,'ROOT',tmp_path)
    monkeypatch.setattr(routes,'_alpha_lab_service',lambda:service)
    _fake_scan_thread(monkeypatch)
    response=client.post('/api/admin/mirofish/alpha-lab',json={})
    assert response.status_code==202
    assert 'C:/private' not in response.get_data(as_text=True)
    assert response.json['opportunity_engine']['status']=='held'
    legacy={key:deepcopy(item) for key,item in value.items() if key!='opportunity_board'}
    clock=response.json['report']['buy_candidates'][0]['proposal']['derived_at']
    expected=present_status(dict(state='running',report=legacy),now=clock)
    assert response.json['report']['buy_candidates']==expected['report']['buy_candidates']
