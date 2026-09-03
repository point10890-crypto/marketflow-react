"""BUY-only TOP3 selection tests — deterministic, no graphrag/network."""
from app.services.mirofish import workflow as wf


def _run(action, score):
    return {
        'status': 'completed', 'analysis_status': 'SUCCESS_PRIMARY',
        'verdict': {'action': action}, 'final_score': score, 'symbol': f'{action}{score}',
    }


def _run_with_label(label, score):
    return {
        'status': 'completed', 'analysis_status': 'SUCCESS_PRIMARY',
        'verdict': {'label': label}, 'final_score': score, 'symbol': f'{label}{score}',
    }


def test_select_top3_buy_only():
    ranked = [_run('BUY', 90), _run('SELL', 85), _run('HOLD', 80), _run('BUY', 70)]
    top3 = wf._select_top3(ranked, top_n=3, require_buy=True)
    assert [r['verdict']['action'] for r in top3] == ['BUY', 'BUY']
    assert [r['final_score'] for r in top3] == [90, 70]


def test_select_top3_no_buy_is_empty():
    ranked = [_run('SELL', 90), _run('HOLD', 80)]
    assert wf._select_top3(ranked, top_n=3, require_buy=True) == []


def test_select_top3_require_buy_false_keeps_all():
    ranked = [_run('SELL', 90), _run('BUY', 80), _run('HOLD', 70)]
    top3 = wf._select_top3(ranked, top_n=3, require_buy=False)
    assert len(top3) == 3 and top3[0]['final_score'] == 90


def test_verdict_is_buy_case_insensitive():
    assert wf._verdict_is_buy(_run('buy', 1)) is True
    assert wf._verdict_is_buy(_run(' BUY ', 1)) is True
    assert wf._verdict_is_buy(_run('SELL', 1)) is False
    assert wf._verdict_is_buy({}) is False


def test_verdict_is_buy_uses_cio_label_but_not_scanner_action():
    assert wf._verdict_is_buy(_run_with_label('BUY', 1)) is True
    assert wf._verdict_is_buy({'action': 'BUY_CANDIDATE', 'verdict': {}}) is False


def test_select_top3_buy_only_accepts_verdict_label_fallback():
    ranked = [_run('HOLD', 90), _run_with_label('BUY', 80), _run('SELL', 70)]
    top3 = wf._select_top3(ranked, top_n=3, require_buy=True)
    assert top3 == [ranked[1]]


def test_require_buy_env_override(monkeypatch):
    monkeypatch.setenv('MIROFISH_TOP3_REQUIRE_BUY', 'false')
    assert wf._require_buy(None) is False
    monkeypatch.setenv('MIROFISH_TOP3_REQUIRE_BUY', 'true')
    assert wf._require_buy(None) is True


def test_require_buy_filters_take_precedence(monkeypatch):
    monkeypatch.setenv('MIROFISH_TOP3_REQUIRE_BUY', 'true')
    assert wf._require_buy({'filters': {'require_buy': False}}) is False


def test_default_require_buy_true(monkeypatch):
    monkeypatch.delenv('MIROFISH_TOP3_REQUIRE_BUY', raising=False)
    assert wf._require_buy(None) is True


def test_telegram_no_buy_message():
    workflow = {
        'id': 'mcp_x', 'scanner_run_id': 'mfas_x', 'event_count': 2,
        'analysis_runs': [_run('SELL', 80), _run('HOLD', 70)], 'top3': [],
        'filters': {'require_buy': True, 'batch_size': 2, 'top_n': 3},
        'summary': {'buy_count': 0, 'analyzed_count': 2},
    }
    msg = wf.build_workflow_top3_telegram_message(workflow)
    assert '오늘 매수 판정 종목 없음' in msg


def test_hold_review_is_never_selected_or_notified():
    incomplete = {
        'analysis_status': 'HOLD_REVIEW',
        'verdict': {'action': 'HOLD_REVIEW'},
        'final_score': 999,
    }
    ordinary_hold = _run('HOLD', 70)
    assert wf._select_top3([incomplete, ordinary_hold], top_n=3, require_buy=False) == [ordinary_hold]
    ok, reason = wf.should_send_workflow_top3({
        'top3': [incomplete],
        'summary': {'quality': {'recommendation': 'send'}},
    })
    assert ok is False and reason == 'hold_review'


def test_failed_or_unallowlisted_status_is_never_complete():
    assert wf._analysis_is_complete({'status': 'failed', 'verdict': {'action': 'BUY'}}) is False
    assert wf._analysis_is_complete({'analysis_status': 'DEGRADED', 'verdict': {'action': 'BUY'}}) is False
    assert wf._analysis_is_complete({
        'status': 'completed', 'analysis_status': 'SUCCESS_PRIMARY',
        'verdict': {'action': 'HOLD'},
    }) is True
