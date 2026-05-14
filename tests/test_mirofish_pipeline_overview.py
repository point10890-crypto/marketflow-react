import json
import time

from app.services.mirofish import pipeline_overview


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
