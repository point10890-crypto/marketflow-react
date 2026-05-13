import json
from datetime import datetime, timedelta, timezone

from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import alpha_scanner


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _seed_artifacts(data_dir):
    (data_dir / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000001,KOSPI,000001.KS,Alpha One',
            '000002,KOSDAQ,000002.KQ,Beta Two',
        ]),
        encoding='utf-8',
    )
    (data_dir / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000001,2026-05-02,Alpha One,100,0,1.0,101,98,99,100000,2026-05-02 16:00:00',
            '000001,2026-05-03,Alpha One,108,0,8.0,110,100,101,600000000,2026-05-03 16:00:00',
            '000002,2026-05-03,Beta Two,50,0,22.0,59,47,48,1000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    _write_json(data_dir / 'screener_leading_latest.json', {
        'timestamp': '2026-05-10T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })
    _write_json(data_dir / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': '2026-05-10T00:00:00+00:00'},
        'signals': [
            {
                'symbol': '000001',
                'name': 'Alpha One',
                'market': 'KR',
                'composite': {'composite_score': 90, 'entry_ready': 'True'},
            },
        ],
    })
    _write_json(data_dir / 'jongga_v2_latest.json', {
        'date': '2026-05-10',
        'signals': [
            {
                'stock_code': '000001',
                'stock_name': 'Alpha One',
                'market': 'KOSPI',
                'score': {'total': 12},
                'checklist': {'negative_news': False, 'upper_wick_long': False},
            },
            {
                'stock_code': '000002',
                'stock_name': 'Beta Two',
                'market': 'KOSDAQ',
                'score': {'total': 6},
                'checklist': {'negative_news': True, 'upper_wick_long': True},
            },
        ],
    })


def _seed_advanced_artifacts(data_dir):
    (data_dir / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000010,KOSPI,000010.KS,Steady Accumulator',
            '000020,KOSPI,000020.KS,Single Day Spike',
        ]),
        encoding='utf-8',
    )
    price_rows = ['ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time']
    steady_prices = [100, 102, 103, 105, 107, 109, 111, 114, 116, 120]
    steady_volumes = [900000, 950000, 1000000, 1100000, 1250000, 1400000, 1600000, 1900000, 2300000, 4200000]
    spike_prices = [95, 96, 96, 97, 98, 99, 100, 101, 102, 132]
    spike_volumes = [800000, 820000, 780000, 850000, 870000, 880000, 910000, 920000, 950000, 8000000]
    for index, close in enumerate(steady_prices):
        previous = steady_prices[index - 1] if index else close
        change_rate = ((close / previous) - 1) * 100 if index else 0
        price_rows.append(
            f"000010,2026-05-{index + 1:02d},Steady Accumulator,{close},0,{change_rate:.2f},"
            f"{close * 1.02:.2f},{close * 0.98:.2f},{previous},{steady_volumes[index]},2026-05-{index + 1:02d} 16:00:00"
        )
    for index, close in enumerate(spike_prices):
        previous = spike_prices[index - 1] if index else close
        change_rate = ((close / previous) - 1) * 100 if index else 0
        high = 160 if index == len(spike_prices) - 1 else close * 1.02
        low = 94 if index == len(spike_prices) - 1 else close * 0.98
        price_rows.append(
            f"000020,2026-05-{index + 1:02d},Single Day Spike,{close},0,{change_rate:.2f},"
            f"{high:.2f},{low:.2f},{previous},{spike_volumes[index]},2026-05-{index + 1:02d} 16:00:00"
        )
    (data_dir / 'daily_prices.csv').write_text('\n'.join(price_rows), encoding='utf-8')
    _write_json(data_dir / 'screener_leading_latest.json', {
        'timestamp': '2026-05-10T00:00:00+00:00',
        'results': [
            {'code': '000010', 'name': 'Steady Accumulator', 'score': {'total_enriched': 88}},
            {'code': '000020', 'name': 'Single Day Spike', 'score': {'total_enriched': 90}},
        ],
    })
    _write_json(data_dir / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': '2026-05-10T00:00:00+00:00'},
        'signals': [
            {'symbol': '000010', 'name': 'Steady Accumulator', 'market': 'KR', 'composite': {'composite_score': 91, 'entry_ready': 'True'}},
            {'symbol': '000020', 'name': 'Single Day Spike', 'market': 'KR', 'composite': {'composite_score': 92, 'entry_ready': 'True'}},
        ],
    })
    _write_json(data_dir / 'jongga_v2_latest.json', {
        'date': '2026-05-10',
        'signals': [
            {'stock_code': '000010', 'stock_name': 'Steady Accumulator', 'market': 'KOSPI', 'score': {'total': 13}, 'checklist': {'negative_news': False, 'upper_wick_long': False}},
            {'stock_code': '000020', 'stock_name': 'Single Day Spike', 'market': 'KOSPI', 'score': {'total': 13}, 'checklist': {'negative_news': False, 'upper_wick_long': True}},
        ],
    })


def test_alpha_scanner_creates_ranked_deterministic_run(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})

    assert run['status'] == 'completed'
    assert run['source'] == 'local_marketflow_artifacts'
    assert run['candidate_count'] == 2
    assert run['scoring_schema']['ranking'] == 'rank by alpha_score - 0.55 * risk_score + conviction_adjustment, descending.'
    assert run['candidates'][0]['symbol'] == '000001'
    assert run['candidates'][0]['rank'] == 1
    assert run['candidates'][0]['action'] == 'BUY_CANDIDATE'
    assert run['candidates'][0]['signal_quality'] in {'actionable', 'high_conviction'}
    assert run['candidates'][0]['analysis_profile']['source_count'] == 4
    assert run['candidates'][0]['entry_plan']['risk_reward'] >= 2
    assert run['candidates'][0]['replay_context']['lookahead_safe'] is True
    assert run['candidates'][0]['name'] == run['candidates'][0]['display_name']
    assert run['candidates'][0]['alpha_score'] > run['candidates'][1]['alpha_score']
    assert run['candidates'][1]['risk_score'] > run['candidates'][0]['risk_score']
    assert {'rank', 'symbol', 'name', 'display_name', 'market', 'alpha_score', 'risk_score'} <= set(run['candidates'][0])
    assert run['candidates'][0]['evidence']

    saved = alpha_scanner.read_scanner_run(run['id'])
    candidate_payload = alpha_scanner.read_scanner_candidates(run['id'])

    assert saved['id'] == run['id']
    assert candidate_payload['candidate_count'] == 2
    assert candidate_payload['candidates'][0]['symbol'] == '000001'


def test_alpha_scanner_advanced_analysis_penalizes_single_day_spikes(tmp_path, monkeypatch):
    _seed_advanced_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    by_symbol = {candidate['symbol']: candidate for candidate in run['candidates']}

    steady = by_symbol['000010']
    spike = by_symbol['000020']
    assert run['candidates'][0]['symbol'] == '000010'
    assert steady['ranking_score'] > spike['ranking_score']
    assert steady['analysis_profile']['trend_quality'] > 0
    assert steady['analysis_profile']['volume_accumulation'] > 0
    assert steady['analysis_profile']['volume_ratio'] > 1
    assert steady['signal_quality'] in {'actionable', 'high_conviction'}
    assert spike['risk_score'] > steady['risk_score']
    assert spike['analysis_profile']['over_ma20_pct'] > steady['analysis_profile']['over_ma20_pct']
    assert spike['action'] != 'BUY_CANDIDATE'


def test_alpha_scanner_handles_missing_optional_artifacts(tmp_path, monkeypatch):
    (tmp_path / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000003,2026-05-03,Fallback Three,20,0,5.0,21,19,20,3000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 3})

    assert run['candidate_count'] == 1
    assert run['freshness']['status'] == 'partial'
    assert run['freshness']['missing_files'] >= 3
    assert run['candidates'][0]['symbol'] == '000003'
    assert run['candidates'][0]['source'] == 'local_marketflow_artifacts'


def test_alpha_scanner_prefers_canonical_stock_name_alias(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    (tmp_path / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000001,KOSPI,000001.KS,???',
            '000002,KOSDAQ,000002.KQ,???',
        ]),
        encoding='utf-8',
    )
    (tmp_path / 'korean_stocks_list.csv').write_text(
        '\n'.join([
            'ticker,name,market',
            '000001,정식알파,KOSPI',
            '000002,정식베타,KOSDAQ',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})

    by_symbol = {candidate['symbol']: candidate for candidate in run['candidates']}
    assert by_symbol['000001']['display_name'] == '정식알파'
    assert by_symbol['000001']['name'] == '정식알파'
    assert by_symbol['000001']['market'] == 'KOSPI'


def test_alpha_scanner_can_filter_requested_symbols(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000002'], 'limit': 5})

    assert run['candidate_count'] == 1
    assert run['requested_symbols'] == ['000002']
    assert run['candidates'][0]['symbol'] == '000002'


def test_alpha_scanner_latest_run_returns_newest_and_skips_bad_files(tmp_path, monkeypatch):
    runs_root = tmp_path / 'runs'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(runs_root))
    older_dir = runs_root / 'mfas_20260504000000_aaaaaaaaaaaa'
    newer_dir = runs_root / 'mfas_20260505000000_bbbbbbbbbbbb'
    bad_dir = runs_root / 'mfas_20260506000000_badbadbadbad'
    unsafe_dir = runs_root / '..escape'
    for path in (older_dir, newer_dir, bad_dir, unsafe_dir):
        path.mkdir(parents=True, exist_ok=True)
    _write_json(older_dir / 'run.json', {
        'id': older_dir.name,
        'status': 'completed',
        'generated_at': '2026-05-04T00:00:00+00:00',
        'candidate_count': 1,
        'candidates': [{'symbol': '000001'}],
    })
    _write_json(newer_dir / 'run.json', {
        'id': newer_dir.name,
        'status': 'completed',
        'generated_at': '2026-05-05T00:00:00+00:00',
        'candidate_count': 2,
        'candidates': [{'symbol': '000002'}],
    })
    (bad_dir / 'run.json').write_text('{bad json', encoding='utf-8')

    latest = alpha_scanner.read_latest_scanner_run()
    summaries = alpha_scanner.list_scanner_runs(limit=10)

    assert latest['id'] == newer_dir.name
    assert latest['candidates'][0]['symbol'] == '000002'
    assert [item['id'] for item in summaries] == [newer_dir.name, older_dir.name]
    assert 'candidates' not in summaries[0]


def test_alpha_scanner_status_without_runs_reports_schedule_and_freshness(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('ALPHA_SCANNER_TIMES', '09:20,bad,16:10')

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['enabled'] is True
    assert status['last_run_at'] is None
    assert status['scheduled_times'] == ['09:20', '16:10']
    assert status['next_scheduled_at'].startswith('2026-05-06T09:20:00')
    assert status['freshness']['available_files'] == 5
    assert status['source_files']


def test_alpha_scanner_status_uses_latest_run_metadata(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 17, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['last_run_id'] == run['id']
    assert status['last_run_at'] == run['generated_at']
    assert status['candidate_count'] == run['candidate_count']
    assert status['freshness'] == run['freshness']
    assert status['next_scheduled_at'].startswith('2026-05-07T09:20:00')


def test_alpha_scanner_status_treats_scheduler_last_run_as_kst(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'scheduler_last_run.json', {
        'alpha_scanner_0920': '2026-05-11T09:20:30',
        'alpha_scanner_monitor': '2026-05-11T09:24:30',
        'crypto': '2026-05-11T12:00:00',
    })

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 11, 9, 25, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['scheduler_last_run_at'] == '2026-05-11T09:24:30+09:00'


def test_alpha_scanner_status_reports_current_source_freshness(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
        ],
    })

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 17, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['last_run_id'] == run['id']
    assert status['latest_run_freshness'] == run['freshness']
    assert status['freshness']['status'] == 'stale'
    assert any(
        item['file'] == 'data/screener_leading_latest.json'
        and item['freshness'] == 'stale'
        and item['max_age_days'] == 7
        for item in status['source_files']
    )


def test_alpha_scanner_alert_check_only_returns_new_events(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = str(tmp_path / 'alert_state.json')

    first = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
    )
    second = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
    )

    assert first['new_event_count'] == 1
    assert first['events'][0]['candidate']['symbol'] == '000001'
    assert 'MiroFish 알파 스캐너 신규 후보' in first['message']
    assert 'Alpha One' in first['message']
    assert '매수 후보' in first['message']
    assert second['new_event_count'] == 0
    assert second['events'] == []


def test_alpha_scanner_alert_check_can_defer_state_until_send_success(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = str(tmp_path / 'alert_state.json')

    pending = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )
    retry = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )
    state = alpha_scanner.commit_scanner_alert_events(pending)
    after_commit = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert pending['new_event_count'] == 1
    assert retry['new_event_count'] == 1
    assert state['sent_event_count'] == 1
    assert after_commit['new_event_count'] == 0


def test_alpha_scanner_alert_check_blocks_stale_core_source_alerts(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is True
    assert result['blocked_reason'] == 'source_freshness:stale'
    assert result['new_event_count'] == 0
    assert '알림 차단' in result['message']


def test_alpha_scanner_alert_check_allows_stale_supporting_sources(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': '2026-01-01T00:00:00+00:00'},
        'signals': [
            {
                'symbol': '000001',
                'name': 'Alpha One',
                'market': 'KR',
                'composite': {'composite_score': 90, 'entry_ready': 'True'},
            },
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is False
    assert result['source_warning'] == 'source_freshness:stale'
    assert result['new_event_count'] == 1


def test_alpha_scanner_alert_check_can_allow_stale_core_for_workflow_batches(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
        block_on_stale=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is False
    assert result['source_warning'] == 'source_freshness:stale'
    assert result['new_event_count'] == 1


def test_alpha_scanner_realtime_monitor_sends_after_source_change(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')
    sent_messages = []

    first = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )
    second = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )

    assert first['status'] == 'sent'
    assert first['new_event_count'] == 1
    assert first['telegram_sent'] is True
    assert first['state_committed'] is True
    assert sent_messages and 'Alpha One' in sent_messages[0]
    assert second['status'] == 'unchanged'
    assert second['source_changed'] is False


def test_alpha_scanner_realtime_monitor_rechecks_legacy_blocked_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = tmp_path / 'monitor_state.json'
    alert_state_path = str(tmp_path / 'alert_state.json')
    source = alpha_scanner.get_scanner_source_signature()
    _write_json(monitor_state_path, {
        'version': 1,
        'last_status': 'blocked',
        'last_source_fingerprint': source['fingerprint'],
        'last_processed_at': '2026-05-10T00:00:00+00:00',
    })
    sent_messages = []

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=str(monitor_state_path),
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )

    assert result['status'] == 'sent'
    assert result['source_changed'] is True
    assert result['monitor_state']['version'] == alpha_scanner.MONITOR_STATE_VERSION
    assert sent_messages and 'Alpha One' in sent_messages[0]


def test_alpha_scanner_realtime_monitor_retries_when_telegram_fails(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    first = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        retry_seconds=300,
        send_fn=lambda message: False,
    )
    second = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        retry_seconds=300,
        send_fn=lambda message: True,
    )

    assert first['status'] == 'send_failed'
    assert first['state_committed'] is False
    assert second['status'] == 'retry_wait'


def test_alpha_scanner_realtime_monitor_dry_run_does_not_commit_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        commit_monitor_state=False,
        send_fn=None,
    )

    assert result['status'] == 'pending_send'
    assert result['monitor_state_committed'] is False
    assert not (tmp_path / 'monitor_state.json').exists()
    assert not (tmp_path / 'alert_state.json').exists()


def test_alpha_scanner_realtime_monitor_dry_run_no_events_does_not_commit_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=999,
        max_risk=45,
        commit_monitor_state=False,
        send_fn=None,
    )

    assert result['status'] == 'no_new_events'
    assert result['state_committed'] is False
    assert result['monitor_state_committed'] is False
    assert not (tmp_path / 'monitor_state.json').exists()
    assert not (tmp_path / 'alert_state.json').exists()


def test_alpha_scanner_diagnostics_reports_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)

    diagnostics = alpha_scanner.get_scanner_diagnostics(
        now=datetime(2026, 5, 6, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert diagnostics['health'] == 'error'
    assert diagnostics['source']['missing_files'] == 6
    assert diagnostics['source_freshness']['status'] == 'missing'
    assert diagnostics['source_freshness']['missing_required_files'] == 5
    assert len(diagnostics['source_files']) == 6
    assert diagnostics['schedule']['freshness']['status'] == 'missing'
    assert {issue['code'] for issue in diagnostics['issues']} >= {
        'missing_source_files',
        'telegram_not_configured',
    }


def test_alpha_scanner_rejects_unsafe_run_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    try:
        alpha_scanner.read_scanner_run('../escape')
    except ValueError as exc:
        assert 'invalid scanner run_id' in str(exc)
    else:
        raise AssertionError('unsafe scanner run id should be rejected')


def test_admin_mirofish_scanner_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/scanner/runs' in rules
    assert '/api/admin/mirofish/scanner/status' in rules
    assert '/api/admin/mirofish/scanner/diagnostics' in rules
    assert '/api/admin/mirofish/scanner/alerts/check' in rules
    assert '/api/admin/mirofish/scanner/alerts/state' in rules
    assert '/api/admin/mirofish/scanner/monitor/check' in rules
    assert '/api/admin/mirofish/scanner/monitor/status' in rules
    assert '/api/admin/mirofish/scanner/runs/latest' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/candidates' in rules
    assert '/api/admin/mirofish/workflow/status' in rules
    assert '/api/admin/mirofish/workflow/scan-analyze' in rules
