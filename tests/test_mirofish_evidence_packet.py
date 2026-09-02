from app.services.mirofish.evidence_packet import build_evidence_packet, cache_key


def _candidate():
    return {
        'symbol': '005930', 'name': '삼성전자', 'market': 'KOSPI',
        'observed_at': '2026-07-17T06:30:00+00:00',
        'price': 70000, 'change_pct': 2.5, 'volume': 123456,
        'source': 'KIS',
        'source_packets': [{
            'id': 'kis-1', 'source': 'KIS', 'observed_at': '2026-07-17T06:30:00+00:00',
            'freshness': 'fresh', 'confidence': 0.99, 'text': 'quote 70000',
        }],
        'alpha_score': 82, 'risk_score': 21,
    }


def test_packet_is_replay_stable_and_binds_provenance():
    first = build_evidence_packet(_candidate(), profile='compact')
    second = build_evidence_packet(_candidate(), profile='compact')
    assert first == second
    assert first['as_of'] == '2026-07-17T06:30:00+00:00'
    assert first['sources'][0] == {
        'evidence_id': 'kis-1', 'source': 'KIS',
        'fetched_at': '2026-07-17T06:30:00+00:00',
        'freshness': 'fresh', 'confidence': 0.99,
        'content_fingerprint': first['sources'][0]['content_fingerprint'],
    }
    changed = _candidate()
    changed['source_packets'][0]['text'] = 'quote 71000'
    assert build_evidence_packet(changed)['fingerprint'] != first['fingerprint']


def test_cache_key_changes_for_replay_contract_dimensions():
    packet = build_evidence_packet(_candidate(), profile='compact')
    base = cache_key(packet)
    for field, value in (
        ('as_of', '2026-07-18T06:30:00+00:00'),
        ('profile', 'full'), ('models', {'fast': 'deepseek-v4'}),
        ('schema_version', 'v2'), ('prompt_version', 'p2'),
    ):
        changed = {**packet, field: value}
        assert cache_key(changed) != base
