import os


def _ev(symbol, action='BUY_CANDIDATE', alpha=50.0, key=None):
    return {'event_key': key or f'{symbol}:{action}:2026-07-19',
            'candidate': {'symbol': symbol, 'display_name': symbol, 'market': 'KOSPI',
                          'action': action, 'alpha_score': alpha, 'risk_score': 10.0}}


def _patch_deps(monkeypatch, sdv, tmp_path):
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    import app.services.mirofish.store as store
    import app.services.mirofish.tradingagents.engine as engine
    monkeypatch.setattr(store, '_brain_summary',
                        lambda t: {'regime': 'constructive_bullish', 'alignment_score': 0.8,
                                   'snapshot_at': '2026-07-19T00:00:00Z'})
    calls = {'n': 0}
    def fake_deep(target, *, symbol=None, brain=None, **kw):
        calls['n'] += 1
        return {'id': f'ta_{symbol}', 'method': 'rule',
                'verdict': {'verdict': 'BUY', 'confidence': 70, 'strong_buy': False,
                            'regime': (brain or {}).get('regime'),
                            'regime_adjustment': {'direction': 'bull', 'alignment': 0.8, 'applied': 5.0}}}
    monkeypatch.setattr(engine, 'run_deep_analysis', fake_deep)
    return calls


def test_select_top_k_buy_only(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setenv('MIROFISH_TA_SCAN_MAX', '2')
    events = [_ev('A', alpha=10), _ev('B', alpha=90), _ev('C', alpha=50),
              _ev('W', action='WATCH', alpha=99)]
    selected = sdv._select_events(events)
    assert [e['candidate']['symbol'] for e in selected] == ['B', 'C']  # top-2 alpha, WATCH excluded


def test_dedupe_skips_existing(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record({'event_key': 'B:BUY_CANDIDATE:2026-07-19', 'verified_at': '2026-07-19T01:00:00Z'})
    selected = sdv._select_events([_ev('B', alpha=90), _ev('C', alpha=50)])
    assert [e['candidate']['symbol'] for e in selected] == ['C']  # B already verified


def test_verify_new_events_writes_history(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    calls = _patch_deps(monkeypatch, sdv, tmp_path)
    sdv._verify_new_events([_ev('B', alpha=90)], {'generated_at': '2026-07-19T00:00:00Z'})
    recs = sdv.read_history()['records']
    assert calls['n'] == 1 and len(recs) == 1
    r = recs[0]
    assert r['symbol'] == 'B' and r['verdict'] == 'BUY' and r['regime'] == 'constructive_bullish'
    assert r['ta_run_id'] == 'ta_B' and r['brain_snapshot_at'] == '2026-07-19T00:00:00Z'


def test_verify_one_isolates_failure(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    _patch_deps(monkeypatch, sdv, tmp_path)
    import app.services.mirofish.tradingagents.engine as engine
    def boom(*a, **k): raise RuntimeError('llm down')
    monkeypatch.setattr(engine, 'run_deep_analysis', boom)
    sdv._verify_new_events([_ev('B')], {'generated_at': 'x'})  # must not raise
    assert sdv.read_history()['records'] == []


def test_enqueue_killswitch(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setenv('MIROFISH_TA_SCAN_DISABLED', 'true')
    fired = {'n': 0}
    monkeypatch.setattr(sdv, '_verify_new_events', lambda ev, run: fired.__setitem__('n', fired['n'] + 1))
    sdv.enqueue_new_events([_ev('B')], {})
    assert fired['n'] == 0  # disabled → no-op
