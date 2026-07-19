import os


def _rec(event_key, verified_at, verdict='BUY'):
    return {'event_key': event_key, 'symbol': '005930', 'verified_at': verified_at,
            'verdict': verdict, 'confidence': 60, 'strong_buy': False, 'regime': 'neutral_balanced'}


def test_append_and_read(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z'))
    sdv.append_record(_rec('k2', '2026-07-19T02:00:00Z'))
    data = sdv.read_history()
    assert [r['event_key'] for r in data['records']] == ['k1', 'k2']


def test_history_cap(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    monkeypatch.setattr(sdv, 'HISTORY_MAX', 3)
    for i in range(5):
        sdv.append_record(_rec(f'k{i}', f'2026-07-19T0{i}:00:00Z'))
    keys = [r['event_key'] for r in sdv.read_history()['records']]
    assert keys == ['k2', 'k3', 'k4']       # oldest dropped, newest kept


def test_latest_by_event_key(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z', verdict='HOLD'))
    sdv.append_record(_rec('k1', '2026-07-19T03:00:00Z', verdict='BUY'))  # newer wins
    latest = sdv.latest_by_event_key()
    assert latest['k1']['verdict'] == 'BUY'


def test_history_recent_first(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'h.json'))
    sdv.append_record(_rec('k1', '2026-07-19T01:00:00Z'))
    sdv.append_record(_rec('k2', '2026-07-19T05:00:00Z'))
    recent = sdv.history(limit=10)
    assert recent[0]['event_key'] == 'k2'   # newest first


def test_read_history_missing_file(monkeypatch, tmp_path):
    from app.services.mirofish import scanner_deepverify as sdv
    monkeypatch.setattr(sdv, 'HISTORY_PATH', os.path.join(str(tmp_path), 'nope.json'))
    assert sdv.read_history() == {'version': 1, 'records': []}
    assert sdv.latest_by_event_key() == {}
