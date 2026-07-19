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
