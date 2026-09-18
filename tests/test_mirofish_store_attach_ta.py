def test_attach_tradingagents_writes_summary(monkeypatch, tmp_path):
    from app.services.mirofish import store
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))
    run_id = 'mf_test_005930'
    import os
    os.makedirs(store._run_dir(run_id), exist_ok=True)
    from app.utils.atomic_json import write_json_atomic
    write_json_atomic(os.path.join(store._run_dir(run_id), 'run.json'),
                      {'id': run_id, 'target': '삼성전자'}, sort_keys=False)

    ta = {'id': 'ta_1', 'method': 'rule',
          'verdict': {'verdict': 'BUY', 'confidence': 66, 'strong_buy': False,
                      'regime': 'constructive_bullish',
                      'regime_adjustment': {'direction': 'bull', 'applied': 5.0},
                      'bull_case': 'b', 'bear_case': 'r', 'risk_summary': 'x'}}
    summary = store.attach_tradingagents(run_id, ta)
    assert summary['verdict'] == 'BUY' and summary['run_id'] == 'ta_1'

    saved = store.read_run(run_id)
    assert saved['tradingagents']['verdict'] == 'BUY'
    assert saved['tradingagents']['regime'] == 'constructive_bullish'


def test_attach_tradingagents_missing_run_returns_none(monkeypatch, tmp_path):
    from app.services.mirofish import store
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))
    assert store.attach_tradingagents('mf_nope_000000', {'id': 'ta', 'verdict': {}}) is None


def test_create_compact_run_writes_legacy_compatible_artifacts(monkeypatch, tmp_path):
    from app.services.mirofish import store
    monkeypatch.setattr(store, 'RUNS_ROOT', str(tmp_path))
    candidate = {
        'symbol': '005930', 'name': '삼성전자', 'display_name': '삼성전자', 'market': 'KOSPI',
        'price': {'date': '2026-07-17', 'current_price': 70000, 'change_pct': 2.5},
    }
    ta = {
        'id': 'ta_20260717_063000_000000_abcdef', 'analysis_status': 'SUCCESS_PRIMARY',
        'profile': 'compact', 'evidence_fingerprint': 'a' * 64,
        'analyst_reports': [{'role': 'technical', 'title': '기술', 'stance': 'bullish', 'score': 80, 'summary': '상승'}],
        'research_debate': {'method': 'llm'}, 'provider_usage': {'calls': 3},
        'verdict': {'verdict': 'BUY', 'confidence': 82, 'reasoning': '근거', 'bull_case': 'b', 'bear_case': 'r'},
    }
    ta['evidence_packet'] = {'sources': [{
        'source': 'KIS', 'source_type': 'market_quote', 'title': '삼성전자',
        'freshness': 'fresh', 'confidence': 1.0,
    }]}
    run = store.create_compact_run(candidate, ta, agent_count=10)
    assert store.read_run(run['id'])['source_run_id'] == ta['id']
    assert store.get_graph(run['id'])['run_id'] == run['id']
    assert store.get_report(run['id'])['markdown'].startswith('# MiroFish Live Report')
    assert run['provider_usage'] == {'calls': 3}
    assert run['pipeline']['agent_count'] == 10
    assert run['pipeline']['compact_role_count'] == 1
    report = store.get_report(run['id'])['markdown']
    assert 'Price: `70000` KRW' in report
    assert 'market_quote/KIS: 삼성전자' in report
