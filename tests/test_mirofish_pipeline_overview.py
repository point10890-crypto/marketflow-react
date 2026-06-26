import json
import os
import time
from datetime import datetime, timezone

from app.services.mirofish import alpha_scanner, pipeline_overview


def test_outcomes_board_cache_hit_skips_workflow_scan(monkeypatch):
    cached = {'window_days': 30, 'items': [], 'summary': {'evaluated_count': 0}}
    pipeline_overview._PIPELINE_TODAY_CACHE.clear()
    with pipeline_overview._PIPELINE_TODAY_LOCK:
        pipeline_overview._PIPELINE_TODAY_CACHE['board:30:20'] = (time.time(), cached)

    def fail_scan(_cutoff):
        raise AssertionError('cache hit should not scan workflow directories')

    monkeypatch.setattr(pipeline_overview, '_recent_workflow_ids', fail_scan)

    assert pipeline_overview.get_outcomes_board(days=30, limit=20) is cached


def test_outcomes_board_reads_existing_artifact_only(tmp_path, monkeypatch):
    workflow_root = tmp_path / 'workflows'
    workflow_dir = workflow_root / 'mcp_20260515090000_test'
    workflow_dir.mkdir(parents=True)
    (workflow_dir / 'outcomes.json').write_text(
        json.dumps(
            {
                'items': [
                    {
                        'symbol': '005930',
                        'name': '삼성전자',
                        'rank': 1,
                        'entry_date': '2026-05-14',
                        'entry_price': 201000,
                        'status': 'evaluated',
                        'hit': True,
                        'forward_return_pct': 3.2,
                        'primary_horizon_days': 5,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    pipeline_overview._PIPELINE_TODAY_CACHE.clear()
    monkeypatch.setattr(pipeline_overview, 'WORKFLOWS_ROOT', str(workflow_root))

    board = pipeline_overview.get_outcomes_board(days=30, limit=20)

    assert board['sample_size'] == 1
    assert board['workflow_count'] == 1
    assert board['summary']['evaluated_count'] == 1
    assert board['summary']['hit_rate_pct'] == 100.0
    assert board['items'][0]['symbol'] == '005930'
    assert board['items'][0]['entry_price'] == 201000


def test_pipeline_today_snapshot_fails_open_when_refresh_is_slow(monkeypatch):
    pipeline_overview._PIPELINE_TODAY_CACHE.clear()

    def slow_build():
        time.sleep(0.08)
        return {'generated_at': 'done'}

    def fail_kpi_window(days):
        raise AssertionError('fallback response must not build outcome KPI synchronously')

    monkeypatch.setattr(pipeline_overview, '_PIPELINE_TODAY_BACKGROUND_REFRESH', True)
    monkeypatch.setattr(pipeline_overview, '_build_pipeline_today_snapshot', slow_build)
    monkeypatch.setattr(pipeline_overview, '_kpi_window', fail_kpi_window)

    snapshot = pipeline_overview.get_pipeline_today_snapshot(max_wait_seconds=0.01)

    assert snapshot['degraded'] is True
    assert snapshot['degraded_reason'] == 'refreshing'
    assert snapshot['kpi_7d']['source'] == 'pending_refresh'
    time.sleep(0.1)
    pipeline_overview._PIPELINE_TODAY_CACHE.clear()


def test_pipeline_today_snapshot_fast_path_does_not_start_refresh(monkeypatch):
    pipeline_overview._PIPELINE_TODAY_CACHE.clear()

    def fail_build():
        raise AssertionError('fast path should not start background refresh')

    monkeypatch.setattr(pipeline_overview, '_PIPELINE_TODAY_BACKGROUND_REFRESH', False)
    monkeypatch.setattr(pipeline_overview, '_build_pipeline_today_snapshot', fail_build)

    snapshot = pipeline_overview.get_pipeline_today_snapshot()

    assert snapshot['degraded'] is True
    assert snapshot['degraded_reason'] == 'fast_path'
    assert 'funnel' in snapshot


def test_scanner_schedule_status_uses_light_source_metadata(tmp_path, monkeypatch):
    for filename in alpha_scanner.WATCHED_SOURCE_FILES:
        path = tmp_path / filename
        if filename.endswith('.json'):
            path.write_text(json.dumps({'timestamp': '2026-05-15T00:00:00+00:00'}), encoding='utf-8')
        else:
            path.write_text('sample\n', encoding='utf-8')

    def fail_full_artifact_load():
        raise AssertionError('schedule status must not load full scanner artifacts')

    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, '_load_artifacts', fail_full_artifact_load)
    monkeypatch.setattr(
        alpha_scanner,
        'read_latest_scanner_run',
        lambda: {
            'id': 'mfas_test',
            'generated_at': '2026-05-15T00:00:00+00:00',
            'candidate_count': 3,
            'freshness': {'status': 'fresh'},
        },
    )
    monkeypatch.setattr(
        alpha_scanner.tradingview_provider,
        'get_status',
        lambda include_live=False: {'available': False, 'include_live': include_live},
    )

    status = alpha_scanner.get_scanner_schedule_status()

    assert status['last_run_id'] == 'mfas_test'
    assert status['candidate_count'] == 3
    assert status['providers']['tradingview']['available'] is False
    assert {item['file'] for item in status['source_files']} == {
        f'data/{filename}' for filename in alpha_scanner.WATCHED_SOURCE_FILES
    }


def test_pipeline_counts_scanner_runs_by_kst_trading_day(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    root.mkdir()
    (root / 'mfas_20260517143000_prev_kst').mkdir()
    (root / 'mfas_20260517234334_today_kst').mkdir()
    (root / 'mfas_20260518150000_next_kst').mkdir()
    monkeypatch.setattr(pipeline_overview, 'SCANNER_RUNS_ROOT', str(root))

    now_kst = datetime(2026, 5, 18, 8, 50, tzinfo=pipeline_overview.KST)

    assert pipeline_overview._count_scanner_runs_today(now_kst) == 1


def test_alerts_today_counts_utc_events_by_kst_day(tmp_path, monkeypatch):
    admin_root = tmp_path / 'admin_mirofish'
    admin_root.mkdir()
    (admin_root / 'alpha_scanner_alert_state.json').write_text(
        json.dumps(
            {
                'last_sent_at': '2026-05-17T23:50:00+00:00',
                'history': [
                    {'sent_at': '2026-05-17T14:59:00+00:00'},
                    {'sent_at': '2026-05-17T23:50:00+00:00'},
                    {'sent_at': '2026-05-18T14:59:59+00:00'},
                    {'sent_at': '2026-05-18T15:00:00+00:00'},
                ],
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(pipeline_overview, 'ADMIN_DATA_ROOT', str(admin_root))

    now_kst = datetime(2026, 5, 18, 12, 0, tzinfo=pipeline_overview.KST)

    summary = pipeline_overview._alerts_today(now_kst)
    assert summary['scanner_alerts_today'] == 2
    assert summary['recent_scanner_alerts'][0]['sent_at'] == '2026-05-18T14:59:59+00:00'


def test_alerts_today_counts_legacy_sent_events_without_history(tmp_path, monkeypatch):
    admin_root = tmp_path / 'admin_mirofish'
    admin_root.mkdir()
    (admin_root / 'alpha_scanner_alert_state.json').write_text(
        json.dumps(
            {
                'last_checked_at': '2026-06-26T01:49:51+00:00',
                'sent_events': {
                    '079650:WATCH:2026-06-26': {
                        'sent_at': '2026-06-26T01:49:51+00:00',
                        'run_id': 'mfas_test',
                        'symbol': '079650',
                        'display_name': '서산',
                        'market': 'KOSDAQ',
                        'action': 'WATCH',
                        'alpha_score': 40,
                        'risk_score': 20,
                        'price': {'current_price': 5760, 'change_rate': 3.2},
                    },
                    '000001:WATCH:2026-06-25': {
                        'sent_at': '2026-06-25T01:49:51+00:00',
                        'symbol': '000001',
                        'display_name': 'Old',
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )
    monkeypatch.setattr(pipeline_overview, 'ADMIN_DATA_ROOT', str(admin_root))

    now_kst = datetime(2026, 6, 26, 10, 55, tzinfo=pipeline_overview.KST)
    summary = pipeline_overview._alerts_today(now_kst)

    assert summary['scanner_alerts_today'] == 1
    assert summary['scanner_last_alert_at'] == '2026-06-26T01:49:51+00:00'
    assert summary['recent_scanner_alerts'][0]['symbol'] == '079650'
    assert summary['recent_scanner_alerts'][0]['price']['current_price'] == 5760


def test_read_latest_scanner_run_reads_only_newest_file(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    old_dir = root / 'mfas_20260514090000_old'
    new_dir = root / 'mfas_20260515090000_new'
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    old_path = old_dir / 'run.json'
    new_path = new_dir / 'run.json'
    old_path.write_text(json.dumps({'id': old_dir.name, 'candidate_count': 1}), encoding='utf-8')
    new_path.write_text(json.dumps({'id': new_dir.name, 'candidate_count': 7}), encoding='utf-8')
    os.utime(old_path, (time.time() - 3600, time.time() - 3600))
    os.utime(new_path, None)

    def fail_full_records_scan():
        raise AssertionError('latest scanner run should not load every run json')

    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(root))
    monkeypatch.setattr(alpha_scanner, '_scanner_run_records', fail_full_records_scan)

    latest = alpha_scanner.read_latest_scanner_run()

    assert latest['id'] == new_dir.name
    assert latest['candidate_count'] == 7
