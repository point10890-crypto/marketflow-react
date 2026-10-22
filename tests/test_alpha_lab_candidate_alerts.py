"""Only new sealed desk events use the existing authorized private transport."""
import importlib
import pytest
from app.services.mirofish.alpha_lab import candidate_store
from tests.test_alpha_lab_candidate_store import desk,data
from tests.test_alpha_lab_telegram_alerts import Telegram, TOKEN, CHAT


def module():
    try:return importlib.import_module('app.services.mirofish.alpha_lab.candidate_alerts')
    except ModuleNotFoundError:pytest.fail('candidate event delivery is not implemented')


def test_new_event_uses_own_ledger_and_exact_frozen_prices_once(tmp_path,monkeypatch):
    mod=module();value=desk();candidate_store.publish(tmp_path/'candidate-desk',value,data(),now=value['generated_at'])
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN',TOKEN);monkeypatch.setenv('TELEGRAM_CHAT_ID',str(CHAT))
    telegram=Telegram(now='2026-10-22T00:03:00Z')
    options=dict(now=telegram.now,enabled=True,request_get=telegram.get,request_post=telegram.post)
    assert mod.deliver_latest(tmp_path,**options)['status']=='delivered'
    assert mod.deliver_latest(tmp_path,**options)['status']=='already_delivered'
    assert len(telegram.posts)==1
    assert '101' in telegram.posts[0]['text'] and '005930' in telegram.posts[0]['text']
    assert (tmp_path/'candidate-desk'/'notifications'/'telegram.json').exists()
    assert not (tmp_path/'notifications').exists()


def test_expired_or_failed_desk_never_sends(tmp_path,monkeypatch):
    mod=module();value=desk();candidate_store.publish(tmp_path/'candidate-desk',value,data(),now=value['generated_at'])
    telegram=Telegram(now='2026-10-23T06:31:00Z')
    assert not mod.preview_latest(tmp_path,now=telegram.now)['sendable']
    assert mod.deliver_latest(tmp_path,now=telegram.now,enabled=True,
        request_get=telegram.get,request_post=telegram.post)['status']!='delivered'
    assert not telegram.posts and not telegram.gets
