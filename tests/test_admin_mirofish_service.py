from app.services.mirofish import store


def test_mirofish_run_writes_readable_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    run = store.create_run({
        'target': 'Samsung Electronics',
        'agent_count': 7,
        'mode': 'full',
    })

    assert run['id'].startswith('mf_samsung-electronics_')
    assert run['target'] == 'Samsung Electronics'
    assert run['status'] == 'completed'
    assert run['verdict']['action'] == 'BUY'
    assert len(run['analysts']) == 7

    saved_run = store.read_run(run['id'])
    graph = store.get_graph(run['id'])
    report = store.get_report(run['id'])

    assert saved_run is not None
    assert saved_run['id'] == run['id']
    assert graph is not None
    assert graph['run_id'] == run['id']
    assert graph['nodes']
    assert report is not None
    assert report['format'] == 'markdown'
    assert 'Samsung Electronics' in report['markdown']


def test_mirofish_rejects_path_traversal_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    try:
        store.read_run('../escape')
    except ValueError as exc:
        assert 'invalid run_id' in str(exc)
    else:
        raise AssertionError('read_run should reject unsafe run ids')
