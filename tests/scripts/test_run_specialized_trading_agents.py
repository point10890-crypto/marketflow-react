import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def cli():
    path = ROOT / 'scripts/run_specialized_trading_agents.py'
    assert path.exists(), 'Specialized trading agent CLI is not implemented'
    spec = importlib.util.spec_from_file_location('specialized_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_executes_real_actors_and_same_run_replays_exact_fills(tmp_path):
    module = cli()
    request = module.demo_request()
    assert request == module.demo_request(), 'Demo replay must use identical input'
    from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator
    database = tmp_path / 'agents.sqlite'
    first = asyncio.run(TradingOrchestrator(database).run(request, run_id='demo-1'))
    assert first['status'] == 'completed'
    assert first['synthetic'] is True and first['live_orders'] is False
    assert first['data']['status'] == 'ready'
    assert len(first['quant']['candidates']) in range(1, 4)
    assert first['approval']['decision'] == 'approved'
    assert first['execution']['status'] == 'executed'
    assert first['execution']['fills']
    assert max(first['risk']['targets'].values()) <= .2
    assert sum(first['risk']['targets'].values()) <= .6
    restarted = asyncio.run(TradingOrchestrator(database).run(request, run_id='demo-1'))
    assert restarted == first
    other = asyncio.run(TradingOrchestrator(database).run(request, run_id='demo-2'))
    assert other['execution']['status'] == 'duplicate_day'
    assert other['execution']['fills'] == []
    assert other['execution']['portfolio'] == first['execution']['portfolio']


def test_sqlite_interruption_recovers_completed_data_and_finishes_once(tmp_path):
    from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator, PipelineError
    request = cli().demo_request()
    database = tmp_path / 'recover.sqlite'
    interrupted = TradingOrchestrator(database)

    class FailedQuant:
        async def handle(self, message):
            raise RuntimeError('PRIVATE-ERROR-MUST-NOT-BE-JOURNALED')

    interrupted.actors['quant'] = FailedQuant()
    with pytest.raises(PipelineError):
        asyncio.run(interrupted.run(request, run_id='recover-1'))
    data = interrupted.store.load_stage('recover-1', 'data')
    assert data and interrupted.store.load_stage('recover-1', 'quant') is None
    recovered = TradingOrchestrator(database)
    report = asyncio.run(recovered.run(request, run_id='recover-1'))
    assert report['status'] == 'completed' and len(report['execution']['fills']) == 1
    assert recovered.store.load_stage('recover-1', 'data') == data
    assert b'PRIVATE-ERROR-MUST-NOT-BE-JOURNALED' not in database.read_bytes()
    assert asyncio.run(TradingOrchestrator(database).run(request, run_id='recover-1')) == report


def test_verified_loss_of_qualification_exits_existing_paper_position(tmp_path):
    from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator
    request = cli().demo_request()
    request['portfolio'] = {'cash': 800000., 'positions': {'000001': 10.}}
    for row in request['fundamentals']:
        row['tradable'] = False
    request['evidence']['source_hashes']['fundamentals'] = cli().digest(request['fundamentals'])
    report = asyncio.run(TradingOrchestrator(tmp_path / 'exit.sqlite').run(request, run_id='exit-1'))
    assert report['data']['status'] == 'ready' and report['quant']['qualification_complete'] is True
    assert report['risk']['targets'] == {'000001': 0.}
    assert report['approval']['decision'] == 'approved'
    assert report['execution']['status'] == 'executed'
    assert len(report['execution']['fills']) == 1 and report['execution']['fills'][0]['side'] == 'SELL'
    assert report['execution']['portfolio']['positions'] == {}


def acquired_fixture(tmp_path):
    history, cohort = tmp_path / 'history', tmp_path / 'cohort.json'
    (history / 'prices').mkdir(parents=True)
    (history / 'financials').mkdir()
    financials = [{'symbol': '005930', 'available_date': '2026-08-15', 'period_end': '2026-06-30',
                   'equity': 100, 'liabilities': 50, 'net_income': 10, 'operating_profit': 20,
                   'fs_div': 'CFS', 'source': 'fixture_DART'}]
    cohort.write_text(json.dumps({'as_of': '2026-10-01', 'ranking': {'ranked': [
        {'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI', 'market_cap': 1e12,
         'volume': 1e6, 'date': '2026-10-01', 'share_type': 'common', 'source': 'fixture'}]}}), encoding='utf-8')
    (tmp_path / 'sources').mkdir()
    (tmp_path / 'sources/financials.json').write_text(json.dumps(financials), encoding='utf-8')
    prices = history / 'prices/prices.csv'
    prices.write_text('symbol,date,close,volume\n005930,2026-10-01,100,1000\n', encoding='utf-8')
    funds = history / 'financials/financials.json'
    funds.write_text('[]', encoding='utf-8')
    price_report = {'selected_symbols': ['005930'], 'total_rows': 1, 'completed_at': '2026-10-02T01:00:00Z',
                    'prices_sha256': hashlib.sha256(prices.read_bytes()).hexdigest(), 'symbols': [],
                    'corporate_action_adjustment_verified': False}
    (history / 'prices/report.json').write_text(json.dumps(price_report), encoding='utf-8')
    (history / 'financials/collection_report.json').write_text(json.dumps({
        'financials_sha256': hashlib.sha256(funds.read_bytes()).hexdigest(), 'records': 0,
        'generated_at': '2026-10-02T01:00:00Z', 'historical_vintage_verified': False}), encoding='utf-8')
    return history, cohort


def test_acquired_unverified_sources_are_held_without_quant_or_fills(tmp_path):
    module = cli()
    history, cohort = acquired_fixture(tmp_path)
    request = module.acquired_request(history, cohort)
    from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator
    report = asyncio.run(TradingOrchestrator(tmp_path / 'agents.sqlite').run(request, run_id='actual-held'))
    assert report['status'] == 'held' and report['synthetic'] is False
    assert len(report['data']['ranked']) == 1
    assert report['data']['prices'] == []
    assert report['quant']['qualification_complete'] is False
    assert report['execution']['fills'] == []
    assert {'price_adjustment_verified_missing_or_unverified',
            'financial_vintage_verified_missing_or_unverified'}.issubset(report['data']['reasons'])
    assert request['acquisition']['price_rows_available'] == 1


def test_acquired_corrupt_file_is_rejected_and_verification_cannot_be_promoted(tmp_path):
    module = cli()
    history, cohort = acquired_fixture(tmp_path)
    report_path = history / 'prices/report.json'
    report = json.loads(report_path.read_text())
    report['corporate_action_adjustment_verified'] = True
    report_path.write_text(json.dumps(report))
    assert module.acquired_request(history, cohort)['evidence']['price_adjustment_verified'] is False
    (history / 'prices/prices.csv').write_text('changed')
    with pytest.raises(ValueError):
        module.acquired_request(history, cohort)


def test_cache_audit_preserves_actual_capture_when_report_generation_time_changes(tmp_path):
    module = cli()
    history, cohort = acquired_fixture(tmp_path)
    financial_path = history / 'financials/collection_report.json'
    financial = json.loads(financial_path.read_text())
    financial['captures'] = [{'fetched_at': '2026-10-02T01:00:00Z'},
                             {'fetched_at': '2026-10-02T08:00:00+09:00'}]
    financial_path.write_text(json.dumps(financial))
    first = module.acquired_request(history, cohort)
    financial['generated_at'] = '2026-10-03T02:00:00Z'
    financial_path.write_text(json.dumps(financial))
    assert module.acquired_request(history, cohort) == first
    assert first['evidence']['source_timestamps']['fundamentals'] == '2026-10-02T01:00:00Z'
    del financial['captures']
    financial_path.write_text(json.dumps(financial))
    assert module.acquired_request(history, cohort)['evidence']['source_timestamps']['fundamentals'] is None


def test_cli_exports_summary_and_reuses_database(tmp_path, capsys):
    module = cli()
    args = ['--demo', '--database', str(tmp_path / 'agents.sqlite'), '--out', str(tmp_path / 'out'),
            '--run-id', 'cli-demo']
    assert module.main(args) == 0
    first = json.loads((tmp_path / 'out/report.json').read_text(encoding='utf-8'))
    assert first['execution']['fills']
    assert module.main(args) == 0
    assert json.loads((tmp_path / 'out/report.json').read_text(encoding='utf-8')) == first
    assert (tmp_path / 'out/report.html').exists()
    summary = capsys.readouterr().out
    assert 'paper' in summary and 'synthetic' in summary


def test_cli_rejects_credentials_without_echoing_or_exporting_them(tmp_path, capsys):
    module = cli()
    request = module.demo_request()
    request['api_key'] = 'SECRET-MUST-NEVER-APPEAR'
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request), encoding='utf-8')
    assert module.main(['--request', str(path), '--database', str(tmp_path / 'db.sqlite'),
                        '--out', str(tmp_path / 'out'), '--run-id', 'secret-test']) == 2
    assert 'SECRET-MUST-NEVER-APPEAR' not in capsys.readouterr().out
    assert not (tmp_path / 'out/report.json').exists()


def test_verified_request_requires_explicit_execution_input(tmp_path, capsys):
    module = cli()
    request = module.demo_request()
    del request['execution']
    path = tmp_path / 'request.json'
    path.write_text(json.dumps(request), encoding='utf-8')
    assert module.main(['--request', str(path), '--database', str(tmp_path / 'db.sqlite'),
                        '--out', str(tmp_path / 'out'), '--run-id', 'no-quotes']) == 0
    report = json.loads((tmp_path / 'out/report.json').read_text(encoding='utf-8'))
    assert report['status'] == 'held' and report['execution']['fills'] == []


def test_render_existing_report_without_reopening_ledger_or_running_actors(tmp_path, monkeypatch):
    module = cli()
    from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator
    report = asyncio.run(TradingOrchestrator(tmp_path / 'original.sqlite').run(
        module.demo_request(), run_id='render-original'))
    source = tmp_path / 'original.json'
    source.write_text(json.dumps(report), encoding='utf-8')
    original_bytes = source.read_bytes()
    ledger_bytes = (tmp_path / 'original.sqlite').read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('Rendering must not rerun actors or open a ledger')

    monkeypatch.setattr(TradingOrchestrator, '__init__', forbidden)
    unused_db = tmp_path / 'unused.sqlite'
    assert module.main(['--render-report', str(source), '--out', str(tmp_path / 'view'),
                        '--database', str(unused_db)]) == 0
    assert source.read_bytes() == original_bytes
    assert (tmp_path / 'original.sqlite').read_bytes() == ledger_bytes
    assert not unused_db.exists()
    assert json.loads((tmp_path / 'view/report.json').read_text('utf-8')) == report
    attribution = json.loads((tmp_path / 'view/kelly_attribution.json').read_text('utf-8'))
    assert attribution['rows'][0]['final_weight'] == .2
    assert attribution['rows'][0]['post_cost_target_value'] == pytest.approx(
        report['execution']['nav_after'] * .2)
    markup = (tmp_path / 'view/report.html').read_text('utf-8')
    assert '검출 결과 → 켈리 공식 → 투자 비중' in markup
    assert '20.00%' in markup and '200,000.00원' in markup
    in_place = tmp_path / 'same-output'
    in_place.mkdir()
    stored = in_place / 'report.json'
    stored.write_text(json.dumps(report, indent=4), encoding='utf-8')
    original_format = stored.read_bytes()
    assert module.main(['--render-report', str(stored), '--out', str(in_place)]) == 0
    assert stored.read_bytes() == original_format


def test_render_blocks_credentials_without_exporting(tmp_path, capsys):
    module = cli()
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({'api_key': 'SECRET-RENDER-NEVER-ECHO'}), encoding='utf-8')
    assert module.main(['--render-report', str(path), '--out', str(tmp_path / 'view')]) == 2
    assert 'SECRET-RENDER-NEVER-ECHO' not in capsys.readouterr().out
    assert not (tmp_path / 'view').exists()


@pytest.mark.parametrize('filename', ['kelly_attribution.json', 'report.html', 'report.html.tmp'])
def test_render_rejects_source_colliding_with_other_output_files(tmp_path, filename):
    module = cli()
    report = dict(run_id='collision', status='held', synthetic=False, paper_only=True, live_orders=False,
        data=dict(status='blocked', reasons=[], ranked=[], eligible_symbols=[]),
        quant=dict(qualification_complete=False, qualified=[], reasons=[], candidates=[]),
        risk=dict(status='held', targets={}, reasons=[]), approval=dict(decision='held'),
        execution=dict(status='held', fills=[]), stages=[])
    source = tmp_path / filename
    source.write_text(json.dumps(report, indent=4), encoding='utf-8')
    before = source.read_bytes()
    assert module.main(['--render-report', str(source), '--out', str(tmp_path)]) == 2
    assert source.read_bytes() == before
    assert not (tmp_path / 'report.json').exists()
