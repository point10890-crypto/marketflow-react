from datetime import datetime, timedelta, timezone

import pytest

from app.services.mirofish import goodrich_client as client


def test_today_history_reads_all_pages_and_normalizes_utc(monkeypatch):
    now = datetime(2026, 9, 18, 7, tzinfo=timezone.utc)
    rows = [dict(cycle_id=str(i), detected_at=(now - timedelta(minutes=i)).replace(tzinfo=None).isoformat(), picks=[])
            for i in range(125)]
    rows += [dict(cycle_id='midnight', detected_at='2026-09-17T15:00:00Z', picks=[]),
             dict(cycle_id='yesterday', detected_at='2026-09-17T14:59:59Z', picks=[])]
    calls = []

    def history(*, limit, offset):
        calls.append(offset)
        return {'items': rows[offset:offset + limit]}

    monkeypatch.setattr(client, 'get_detection_history', history)
    result = client.get_today_detection_history(now=now)
    assert calls == [0, 100]
    assert result['date'] == '2026-09-18'
    assert result['timezone'] == 'Asia/Seoul'
    assert len(result['items']) == 126
    assert result['items'][0]['detected_at'] == '2026-09-18T16:00:00+09:00'
    assert result['items'][-1]['cycle_id'] == 'midnight'


def test_today_history_empty_does_not_show_yesterday(monkeypatch):
    monkeypatch.setattr(client, 'get_detection_history', lambda **_: {'items': [
        {'cycle_id': 'old', 'detected_at': '2026-09-17T06:00:00', 'picks': []}]})
    assert client.get_today_detection_history(now=datetime(2026, 9, 18, tzinfo=timezone.utc))['items'] == []


def test_today_history_does_not_claim_complete_when_page_fails(monkeypatch):
    def history(**kwargs):
        if kwargs['offset']:
            raise client.GoodrichServiceError('upstream failed')
        return {'items': [{'cycle_id': str(i), 'detected_at': '2026-09-18T01:00:00', 'picks': []} for i in range(100)]}
    monkeypatch.setattr(client, 'get_detection_history', history)
    with pytest.raises(client.GoodrichServiceError):
        client.get_today_detection_history(now=datetime(2026, 9, 18, tzinfo=timezone.utc))
