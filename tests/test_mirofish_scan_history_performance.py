import json

from app.services.mirofish import outcome_tracker, workflow
from app.services.mirofish.graphrag import scan_history


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def test_scan_performance_reads_outcomes_artifact_without_lazy_recompute(tmp_path, monkeypatch):
    workflows_root = tmp_path / 'workflows'
    scanner_root = tmp_path / 'scanner_runs'
    workflow_id = 'mcp_20260515093000_demo'
    workflow_dir = workflows_root / workflow_id
    _write_json(
        workflow_dir / 'workflow.json',
        {
            'id': workflow_id,
            'created_at': '2026-05-15T09:30:00+09:00',
            'top3': [
                {
                    'symbol': '005930',
                    'target': 'Samsung Electronics',
                    'market': 'KOSPI',
                    'final_score': 82.5,
                    'verdict': {'action': 'BUY', 'confidence_pct': 75},
                    'candidate': {
                        'symbol': '005930',
                        'display_name': 'Samsung Electronics',
                        'market': 'KOSPI',
                        'rank': 1,
                    },
                }
            ],
        },
    )
    _write_json(
        workflow_dir / 'outcomes.json',
        {
            'items': [
                {
                    'symbol': '005930',
                    'status': 'evaluated',
                    'hit': True,
                    'forward_return_pct': 4.2,
                    'entry_date': '2026-05-15',
                }
            ]
        },
    )

    def fail_lazy_recompute(*_args, **_kwargs):
        raise AssertionError('scan performance must not trigger outcome recompute')

    scan_history.invalidate_cache()
    monkeypatch.setattr(scan_history, 'WORKFLOWS_ROOT', str(workflows_root))
    monkeypatch.setattr(scan_history, 'SCANNER_RUNS_ROOT', str(scanner_root))
    monkeypatch.setattr(scan_history, '_today_kst', lambda: '2026-05-15')
    monkeypatch.setattr(outcome_tracker, 'read_workflow_outcomes', fail_lazy_recompute)

    summary = scan_history.get_performance_summary(days=7)

    assert summary['evaluated'] == 1
    assert summary['hit_count'] == 1
    assert summary['avg_return_pct'] == 4.2
    assert summary['workflow_count_scanned'] == 1


def test_read_latest_workflow_does_not_load_every_workflow(tmp_path, monkeypatch):
    root = tmp_path / 'workflows'
    old_id = 'mcp_20260514090000_old'
    new_id = 'mcp_20260515090000_new'
    _write_json(root / old_id / 'workflow.json', {'id': old_id, 'created_at': '2026-05-14T09:00:00+09:00'})
    _write_json(root / new_id / 'workflow.json', {'id': new_id, 'created_at': '2026-05-15T09:00:00+09:00'})

    def fail_list_workflows(*_args, **_kwargs):
        raise AssertionError('read_latest_workflow should inspect directories directly')

    monkeypatch.setattr(workflow, 'WORKFLOWS_ROOT', str(root))
    monkeypatch.setattr(workflow, 'list_workflows', fail_list_workflows)

    latest = workflow.read_latest_workflow()

    assert latest['id'] == new_id
