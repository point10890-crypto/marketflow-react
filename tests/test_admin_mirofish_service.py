import pytest

from app.services.mirofish import live_data, store


@pytest.fixture(autouse=True)
def disable_live_kis_api(monkeypatch):
    monkeypatch.setenv('MIROFISH_USE_KIS', '0')
    with live_data._kis_cache_lock:
        live_data._kis_snapshot_cache.clear()


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
    assert run['verdict']['action'] in ('BUY', 'HOLD', 'SELL', 'HOLD_REVIEW')
    if run['verdict']['action'] == 'HOLD_REVIEW':
        assert run['verdict']['analysis_status'] == 'HOLD_REVIEW'
        assert run['cio']['final_answer']['allocation_pct'] == 0.0
        assert run['cio']['rule_candidate_verdict'] is not None
    assert run['verdict']['target'] == run['display_name']
    assert run['display_name'] in run['verdict']['summary']
    assert len(run['analysts']) == 7
    assert run['data_context']['source_files']
    assert run['data_context']['source_packets']
    assert run['data_context']['hybrid_context']['packet_count'] == len(run['data_context']['source_packets'])

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
    assert snapshot['source_packet_count'] >= 1
    assert snapshot['hybrid_context']['mode'] == 'hybrid_rag_source_packets'
    assert 'price' in snapshot
    assert 'signal_count' in snapshot


def test_mirofish_target_snapshot_resolves_chosung_and_normalized_names():
    samsung = store.resolve_target_snapshot('ㅅㅅㅈㅈ')
    soil = store.resolve_target_snapshot('soil')
    soil_chosung = store.resolve_target_snapshot('ㅇㅅㅇㅇ')

    assert samsung['resolved']['symbol'] == '005930'
    assert soil['resolved']['symbol'] == '010950'
    assert soil_chosung['resolved']['symbol'] == '010950'


def test_mirofish_target_snapshot_returns_ambiguous_candidates():
    doosan = '\ub450\uc0b0'
    doosan_robotics = '\ub450\uc0b0\ub85c\ubcf4\ud2f1\uc2a4'

    snapshot = store.resolve_target_snapshot(doosan)
    candidate_names = [item['display_name'] for item in snapshot['candidates']]

    assert snapshot['resolved']['symbol'] == '000150'
    assert candidate_names[0] == doosan
    assert doosan_robotics in candidate_names
    assert len(snapshot['candidates']) >= 4


def test_mirofish_target_snapshot_returns_initial_candidates():
    doosan_initials = '\u3137\u3145'
    doosan = '\ub450\uc0b0'
    doosan_energy = '\ub450\uc0b0\uc5d0\ub108\ube4c\ub9ac\ud2f0'
    doosan_robotics = '\ub450\uc0b0\ub85c\ubcf4\ud2f1\uc2a4'

    snapshot = store.resolve_target_snapshot(doosan_initials)
    candidate_names = [item['display_name'] for item in snapshot['candidates']]

    assert doosan in candidate_names
    assert doosan_energy in candidate_names
    assert doosan_robotics in candidate_names


def test_mirofish_target_search_ranks_exact_initials_first():
    response = store.search_target_candidates('\u3137\u3145', limit=12)
    candidate_names = [item['display_name'] for item in response['candidates']]

    assert candidate_names[0] == '\ub450\uc0b0'
    assert '\ub450\uc0b0\uc5d0\ub108\ube4c\ub9ac\ud2f0' in candidate_names
    assert '\ub450\uc0b0\ub85c\ubcf4\ud2f1\uc2a4' in candidate_names


def test_mirofish_target_search_is_lightweight_candidates_only():
    response = store.search_target_candidates('\ub450\uc0b0', limit=4)

    assert response['source'] == 'ticker_map'
    assert [item['display_name'] for item in response['candidates'][:2]] == [
        '\ub450\uc0b0',
        '\ub450\uc0b0\uc5d0\ub108\ube4c\ub9ac\ud2f0',
    ]
    assert 'price' not in response
    assert 'kis' not in response


def test_mirofish_context_can_enrich_graphrag_with_kis_api(monkeypatch):
    monkeypatch.setenv('MIROFISH_USE_KIS', '1')

    def fake_kis_snapshot(resolved):
        return {
            'source': 'KIS API',
            'enabled': True,
            'found': True,
            'symbol': resolved['symbol'],
            'quote': {
                'symbol': resolved['symbol'],
                'price': 202000,
                'change': 1000,
                'change_pct': 0.5,
                'open': 201000,
                'high': 203000,
                'low': 200500,
                'volume': 1234567,
                'trading_value': 250000000000,
                'market_cap_eok': 4800000,
                'high_52w': 210000,
                'low_52w': 120000,
            },
            'investor': {
                'foreign_net_qty': 12000,
                'institution_net_qty': -3000,
                'individual_net_qty': -9000,
            },
            'sources': ['KIS API: inquire-price', 'KIS API: inquire-investor'],
            'fetched_at': '2026-05-04T00:00:00+00:00',
        }

    monkeypatch.setattr(live_data, 'load_kis_snapshot', fake_kis_snapshot)

    context = live_data.build_context('ㅅㅅㅈㅈ')

    assert context['kis']['found'] is True
    assert context['price']['source'] == 'kis_api'
    assert context['price']['price'] == 202000
    assert 'KIS API live quote' in context['corpus']
    assert 'KIS API investor flow' in context['corpus']
    assert 'KIS API: inquire-price' in context['source_files']
    assert any(packet['source_type'] == 'api' for packet in context['source_packets'])


def test_mirofish_run_start_resolves_chosung_target(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))

    run = store.create_run({
        'target': 'ㅅㅅㅈㅈ',
        'agent_count': 3,
        'mode': 'fast',
    })

    assert run['symbol'] == '005930'
    assert run['display_name'] == '삼성전자'
    assert run['status'] == 'completed'


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
