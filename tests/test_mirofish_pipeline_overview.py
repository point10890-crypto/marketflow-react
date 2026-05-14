import json
import time

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
