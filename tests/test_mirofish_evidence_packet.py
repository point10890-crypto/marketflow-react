import pytest

from app.services.mirofish import evidence_packet
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
    assert {key: first['sources'][0][key] for key in (
        'evidence_id', 'source', 'fetched_at', 'freshness', 'confidence', 'content_fingerprint'
    )} == {
        'evidence_id': 'kis-1', 'source': 'KIS',
        'fetched_at': '2026-07-17T06:30:00+00:00',
        'freshness': 'fresh', 'confidence': 0.99,
        'content_fingerprint': first['sources'][0]['content_fingerprint'],
    }
    assert first['sources'][0]['content']['text'] == 'quote 70000'
    changed = _candidate()
    changed['source_packets'][0]['text'] = 'quote 71000'
    assert build_evidence_packet(changed)['fingerprint'] != first['fingerprint']


def test_latest_source_cutoff_compares_timezone_aware_instants():
    assert evidence_packet.latest_source_cutoff([
        '2026-09-03T10:00:00+09:00',  # 01:00 UTC
        '2026-09-03T03:00:00+00:00',  # later instant despite lexical order
    ]) == '2026-09-03T03:00:00+00:00'


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
    changed_execution = {**packet, 'execution_inputs': {'use_llm': False, 'brain': None}}
    changed_execution['fingerprint'] = 'changed-execution'
    assert cache_key(changed_execution) != base


def test_packet_rejects_missing_or_after_cutoff_provenance():
    missing = _candidate()
    missing.pop('source_packets')
    with pytest.raises(ValueError, match='provenance'):
        build_evidence_packet(missing)

    missing_timestamp = _candidate()
    missing_timestamp['source_packets'][0].pop('observed_at')
    with pytest.raises(ValueError, match='provenance'):
        build_evidence_packet(missing_timestamp)

    future = _candidate()
    future['source_packets'][0]['observed_at'] = '2026-07-17T06:31:00+00:00'
    with pytest.raises(ValueError, match='after as_of'):
        build_evidence_packet(future)


def test_packet_reads_nested_scanner_price_and_binds_all_provider_models():
    candidate = _candidate()
    candidate['price'] = {
        'date': '2026-07-17T06:30:00+00:00', 'current_price': 71000,
        'change_rate': 3.25, 'volume': 987654,
    }
    packet = build_evidence_packet(candidate, models={
        'bulk_text.deepseek': 'deepseek-fast', 'bulk_text.openai': 'gpt-fast',
        'decisive_text.deepseek': 'deepseek-pro', 'decisive_text.openai': 'gpt-pro',
    })
    assert packet['numeric_inputs']['current_price'] == 71000
    assert packet['numeric_inputs']['change_pct'] == 3.25
    assert packet['numeric_inputs']['volume'] == 987654
    assert packet['models']['decisive_text.openai'] == 'gpt-pro'


def test_packet_preserves_authoritative_zero_numeric_values():
    candidate = _candidate()
    candidate['price'] = {'current_price': 0, 'change_rate': 0, 'volume': 0}
    packet = build_evidence_packet(candidate)
    assert packet['numeric_inputs']['current_price'] == 0
    assert packet['numeric_inputs']['change_pct'] == 0
    assert packet['numeric_inputs']['volume'] == 0
