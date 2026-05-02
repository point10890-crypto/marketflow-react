from app.services.mirofish import store


def test_mirofish_run_writes_readable_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    run = store.create_run({
        'target': 'Samsung Electronics',
        'agent_count': 7,
        'mode': 'full',
    })

    assert run['id'].startswith('mf_samsung-electronics_')
    assert run['display_name']
    assert run['symbol'] == '005930'
    assert run['status'] == 'completed'
    assert run['source'] == 'live_file_artifacts'
    assert run['verdict']['action'] in ('BUY', 'HOLD', 'SELL')
    assert len(run['analysts']) == 7
    assert run['data_context']['source_files']

    saved_run = store.read_run(run['id'])
    graph = store.get_graph(run['id'])
    report = store.get_report(run['id'])

    assert saved_run is not None
    assert saved_run['id'] == run['id']
    assert graph is not None
    assert graph['run_id'] == run['id']
    assert graph['source'] == 'live_file_artifacts'
    assert graph['nodes']
    assert report is not None
    assert report['format'] == 'markdown'
    assert run['display_name'] in report['markdown']


def test_mirofish_async_run_streams_progress_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    run = store.create_run({
        'target': 'Samsung Electronics',
        'agent_count': 3,
        'mode': 'fast',
        'async': True,
    })

    assert run['status'] == 'running'
    assert run['progress']['percent'] >= 2

    import time
    from app.services.mirofish import events as mf_events

    saved = None
    for _ in range(200):
        saved = store.read_run(run['id'])
        if saved and saved.get('status') == 'completed':
            break
        time.sleep(0.1)

    assert saved is not None
    assert saved['status'] == 'completed'
    assert saved['progress']['percent'] == 100
    assert saved['performance']['elapsed_ms'] >= 0
    assert saved['graph_nodes']
    assert store.get_graph(run['id'])['nodes']
    assert store.get_report(run['id'])['markdown']

    event_tail = mf_events.read_events(run['id'])
    assert event_tail['total'] >= 5
    assert any((event.get('payload') or {}).get('progress') == 100 for event in event_tail['events'])


def test_mirofish_target_snapshot_uses_live_artifacts():
    snapshot = store.resolve_target_snapshot('Samsung Electronics')

    assert snapshot['source'] == 'live_file_artifacts'
    assert snapshot['resolved']['symbol'] == '005930'
    assert snapshot['source_files']
    assert 'price' in snapshot
    assert 'signal_count' in snapshot


def test_mirofish_data_sources_reports_files():
    sources = store.get_data_sources()

    assert sources['mode'] == 'live_file_artifacts'
    assert any(item['file'] == 'data/daily_prices.csv' for item in sources['files'])


def test_mirofish_rejects_path_traversal_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    try:
        store.read_run('../escape')
    except ValueError as exc:
        assert 'invalid run_id' in str(exc)
    else:
        raise AssertionError('read_run should reject unsafe run ids')
