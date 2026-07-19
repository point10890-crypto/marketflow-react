def test_commit_enqueues(monkeypatch, tmp_path):
    import os
    from app.services.mirofish import alpha_scanner as sc
    from app.services.mirofish import scanner_deepverify as sdv
    captured = {}
    monkeypatch.setattr(sdv, 'enqueue_new_events', lambda events, run: captured.update(events=events, run=run))
    state_file = os.path.join(str(tmp_path), 'alert.json')
    result = {'state_path': state_file, 'run': {'id': 'r1', 'generated_at': 'x'},
              'events': [{'event_key': 'k1', 'candidate': {'symbol': '005930', 'action': 'BUY_CANDIDATE'}}]}
    sc.commit_scanner_alert_events(result)
    assert captured.get('events') and captured['events'][0]['event_key'] == 'k1'
    assert captured['run']['id'] == 'r1'


def test_summary_merges_tradingagents(monkeypatch):
    import datetime as _dt
    from app.services.mirofish import alpha_scanner as sc
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'latest_by_event_key',
                        lambda: {'005930:BUY_CANDIDATE:2026-07-19': {'verdict': 'BUY', 'confidence': 70,
                                                                     'strong_buy': True, 'regime': 'constructive_bullish'}})
    state = {'version': 2, 'sent_events': {
        '005930:BUY_CANDIDATE:2026-07-19': {
            'event_key': '005930:BUY_CANDIDATE:2026-07-19', 'symbol': '005930',
            'display_name': '삼성전자', 'market': 'KOSPI', 'action': 'BUY_CANDIDATE',
            'sent_at': _dt.datetime.now(_dt.timezone.utc).isoformat(),
        }}}
    summary = sc._alert_state_summary(state, 'x')
    feed = summary.get('feed_events') or []
    hit = [e for e in feed if e.get('event_key') == '005930:BUY_CANDIDATE:2026-07-19']
    assert hit, f'event not in feed: {[e.get("event_key") for e in feed]}'
    assert hit[0]['tradingagents']['verdict'] == 'BUY'
