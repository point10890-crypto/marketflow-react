"""marketflow_claw.delivery — 경로 선택, dry-run 기본, 킬스위치, 직접 DM 검증."""
import marketflow_claw.delivery as dl
import marketflow_claw.memory as mem


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(mem, 'DB_PATH', str(tmp_path / 'claw.db'))
    monkeypatch.setattr(dl, 'REPORTS_DIR', str(tmp_path / 'reports'))
    monkeypatch.setattr(dl, 'ensure_dirs', lambda: None)
    (tmp_path / 'reports').mkdir()


def test_route_prefers_direct_dm_when_chat_set(monkeypatch):
    monkeypatch.setenv('CLAW_TELEGRAM_CHAT_ID', '123')
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', 'x')
    assert dl.route()['mode'] == 'direct-dm'
    monkeypatch.delenv('CLAW_TELEGRAM_CHAT_ID')
    assert dl.route()['mode'] == 'legacy-personal-bot'


def test_dry_run_never_sends(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setattr(dl, '_send_direct', lambda text: (_ for _ in ()).throw(AssertionError('must not send')))
    res = dl.deliver('close', '테스트', send=False)
    assert res['sent'] is False and res['mode'] == 'dry-run' and res['error'] is None


def test_kill_switch_blocks_send(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.delenv('CLAW_DELIVERY_ENABLED', raising=False)
    res = dl.deliver('close', '테스트', send=True)
    assert res['sent'] is False and 'CLAW_DELIVERY_ENABLED' in res['error']


def test_direct_dm_requires_ok_and_message_id(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('CLAW_DELIVERY_ENABLED', '1')
    monkeypatch.setenv('CLAW_TELEGRAM_CHAT_ID', '123')
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', 'tok')
    calls = []

    class R:
        def __init__(self, status, body): self.status_code, self._b = status, body
        def json(self): return self._b

    import requests
    monkeypatch.setattr(requests, 'post', lambda url, json, timeout: (calls.append(json), R(200, {'ok': True, 'result': {'message_id': 7}}))[1])
    res = dl.deliver('close', '본문', send=True)
    assert res['sent'] is True and res['mode'] == 'direct-dm' and calls[0]['chat_id'] == '123'
    assert 'tok' not in str(res)  # 토큰 비노출

    monkeypatch.setattr(requests, 'post', lambda url, json, timeout: R(403, {'ok': False, 'description': 'Forbidden: bot was blocked by the user'}))
    res2 = dl.deliver('close', '본문2', send=True)
    assert res2['sent'] is False and res2['error'].startswith('http_403')

    # 같은 본문은 성공 기록이 있으면 재발송 차단
    res3 = dl.deliver('close', '본문', send=True)
    assert res3['sent'] is False and res3['error'] == 'duplicate_digest'


def test_dry_run_then_send_then_dedupe(monkeypatch, tmp_path):
    """실제 발생했던 결함: dry-run 이 digest 를 delivered=0 으로 선점하면 실발송 후에도 중복 차단이 안 됐다."""
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv('CLAW_DELIVERY_ENABLED', '1')
    monkeypatch.setenv('CLAW_TELEGRAM_CHAT_ID', '123')
    monkeypatch.setenv('TELEGRAM_CHANNEL_BOT_TOKEN', 'tok')
    sent = []

    class R:
        status_code = 200
        def json(self): return {'ok': True, 'result': {'message_id': 1}}
    import requests
    monkeypatch.setattr(requests, 'post', lambda url, json, timeout: (sent.append(1), R())[1])

    assert dl.deliver('close', '같은 본문', send=False)['sent'] is False      # dry-run 선점
    assert dl.deliver('close', '같은 본문', send=True)['sent'] is True         # 실발송
    res = dl.deliver('close', '같은 본문', send=True)                          # 재발송 시도
    assert res['sent'] is False and res['error'] == 'duplicate_digest'
    assert len(sent) == 1
    with mem.connect() as con:
        assert con.execute('SELECT COUNT(*), SUM(delivered) FROM briefs').fetchone() == (1, 1)


def test_tests_do_not_touch_production_db(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    with mem.connect() as con:
        assert con.execute('PRAGMA database_list').fetchone()[2].startswith(str(tmp_path))
