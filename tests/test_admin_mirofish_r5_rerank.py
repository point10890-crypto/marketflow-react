import copy
import hashlib
import json
import math

import pytest

from app.services.mirofish import alpha_scanner, deepseek_client, workflow
from app.services.mirofish.evidence_packet import cache_key


def _candidate(symbol: str, ranking_score: float) -> dict:
    source_cutoff = '2026-09-03T06:30:00+00:00'
    return {
        'symbol': symbol,
        'name': f'Candidate {symbol}',
        'display_name': f'Candidate {symbol}',
        'market': 'KOSPI',
        'alpha_score': 80.0,
        'risk_score': 20.0,
        'ranking_score': ranking_score,
        'strategy_tags': ['leading_screener'],
        'evidence': [],
        'price': {
            'date': '2026-09-03',
            'current_price': 100.0,
            'change_rate': 2.0,
            'volume': 1_000_000,
        },
        'source_packets': [{
            'evidence_id': f'{symbol}-market',
            'source': 'daily_prices.csv',
            'source_type': 'market_data',
            'title': f'{symbol} daily price',
            'observed_at': source_cutoff,
            'freshness': 'fresh',
            'confidence': 0.95,
            'content': {'symbol': symbol, 'close': 100.0},
        }],
        'source_cutoff': source_cutoff,
        'replay_context': {
            'source_cutoff': source_cutoff,
            'data_sources': ['daily_prices.csv'],
            'lookahead_safe': True,
        },
        'provenance_missing': [],
        'analysis_profile': {
            'profitability_scorecard': {'goal_fit_score': 75.0},
        },
    }


def _overlay(symbol: str, adjustment: float, **overrides) -> dict:
    overlay = {
        'enabled': True,
        'applied': True,
        'status': 'applied',
        'provider': 'deepseek',
        'model': 'deepseek-v4-pro',
        'schema_version': 'mirofish.deepseek_rerank.v1',
        'max_abs_adjustment': 8.0,
        'created_at': '2026-09-03T06:31:00+00:00',
        'input_fingerprint': 'a' * 64,
        'input_symbols': [symbol],
        'items': [{
            'symbol': symbol,
            'ranking_adjustment': adjustment,
            'deepseek_conviction': 91,
            'risk_flags': ['thin_liquidity'] if adjustment < 0 else [],
            'positive_evidence': ['multi-source confirmation'] if adjustment > 0 else [],
            'rationale_ko': '검증된 근거에 따른 제한적 순위 조정',
        }],
    }
    overlay.update(overrides)
    return overlay


def _apply(rows: list[dict], overlay: dict) -> list[dict]:
    return alpha_scanner._apply_deepseek_rerank_overlay(
        rows,
        overlay,
        validated_at='2026-09-03T06:32:00+00:00',
    )


def test_rerank_order_and_packet_identity_close_over_exact_validated_overlay():
    base = [_candidate('000001', 70.0), _candidate('000002', 68.0)]
    reviewed_candidate = next(row for row in base if row['symbol'] == '000002')
    expected_evidence_fingerprint = hashlib.sha256(
        json.dumps(
            {
                'source_cutoff': reviewed_candidate['source_cutoff'],
                'source_packets': reviewed_candidate['source_packets'],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(',', ':'),
            default=str,
        ).encode('utf-8')
    ).hexdigest()

    promoted = _apply(copy.deepcopy(base), _overlay('000002', 5.0))
    demoted = _apply(copy.deepcopy(base), _overlay('000002', -3.0))

    assert [row['symbol'] for row in promoted] == ['000002', '000001']
    assert [row['symbol'] for row in demoted] == ['000001', '000002']

    promoted_candidate = next(row for row in promoted if row['symbol'] == '000002')
    demoted_candidate = next(row for row in demoted if row['symbol'] == '000002')
    promoted_packet = workflow._build_candidate_packet(promoted_candidate, use_llm=True)
    demoted_packet = workflow._build_candidate_packet(demoted_candidate, use_llm=True)

    assert promoted_candidate['source_cutoff'] == '2026-09-03T06:31:00+00:00'
    assert promoted_candidate['replay_context']['source_cutoff'] == promoted_candidate['source_cutoff']
    assert promoted_candidate['replay_context']['lookahead_safe'] is True
    assert promoted_packet['as_of'] == promoted_candidate['source_cutoff']
    assert promoted_packet['fingerprint'] != demoted_packet['fingerprint']
    assert cache_key(promoted_packet) != cache_key(demoted_packet)

    rerank_source = next(
        source for source in promoted_packet['sources']
        if source['source'] == 'deepseek_rerank'
    )
    content = rerank_source['content']
    assert rerank_source['fetched_at'] == '2026-09-03T06:31:00+00:00'
    assert rerank_source['confidence'] == pytest.approx(0.91)
    assert content == {
        'provider': 'deepseek',
        'model': 'deepseek-v4-pro',
        'operation': 'scanner_rerank',
        'schema_version': 'mirofish.deepseek_rerank.v1',
        'status': 'applied',
        'validated': True,
        'result_at': '2026-09-03T06:31:00+00:00',
        'input_source_cutoff': '2026-09-03T06:30:00+00:00',
        'input_fingerprint': 'a' * 64,
        'input_evidence_fingerprint': expected_evidence_fingerprint,
        'normalized': {
            'symbol': '000002',
            'base_ranking_score': 68.0,
            'ranking_adjustment': 5.0,
            'final_ranking_score': 73.0,
            'deepseek_conviction': 91.0,
            'risk_flags': [],
            'positive_evidence': ['multi-source confirmation'],
            'rationale_ko': '검증된 근거에 따른 제한적 순위 조정',
        },
    }


def test_saved_rerank_packet_replays_without_a_live_deepseek_call(monkeypatch):
    applied = _apply([_candidate('000001', 70.0)], _overlay('000001', 4.0))[0]
    saved_candidate = json.loads(json.dumps(applied, ensure_ascii=False))

    monkeypatch.setattr(
        deepseek_client,
        'rerank_scanner_candidates',
        lambda *_args, **_kwargs: pytest.fail('saved packet replay must not call DeepSeek'),
    )
    first = workflow._build_candidate_packet(saved_candidate, use_llm=True)
    second = workflow._build_candidate_packet(saved_candidate, use_llm=True)

    assert first == second
    assert first['fingerprint'] == second['fingerprint']
    rerank = next(source for source in first['sources'] if source['source'] == 'deepseek_rerank')
    assert rerank['content']['normalized']['final_ranking_score'] == 74.0
    assert saved_candidate['ranking_score'] == 74.0


@pytest.mark.parametrize(
    ('overlay', 'expected_status', 'expected_reason'),
    [
        ({'enabled': False, 'applied': False, 'status': 'disabled'}, 'disabled', 'disabled'),
        ({'enabled': True, 'applied': False, 'status': 'error'}, 'failed', 'provider_error'),
        ({
            'enabled': True,
            'applied': False,
            'status': 'empty_overlay',
            'created_at': '2026-09-03T06:31:00+00:00',
        }, 'unused', 'empty_overlay'),
    ],
)
def test_rerank_non_applied_states_are_explicit_and_score_inert(
    overlay, expected_status, expected_reason,
):
    candidate = _candidate('000001', 70.0)

    result = _apply([candidate], overlay)[0]

    state = result['analysis_profile']['deepseek_rerank']
    assert state['status'] == expected_status
    assert state['reason'] == expected_reason
    assert state['applied'] is False
    assert state['base_ranking_score'] == state['final_ranking_score'] == 70.0
    assert result['ranking_score'] == 70.0
    assert result['source_cutoff'] == '2026-09-03T06:30:00+00:00'
    assert 'deepseek_rerank' not in result['replay_context']['data_sources']
    assert all(packet['source'] != 'deepseek_rerank' for packet in result['source_packets'])


@pytest.mark.parametrize('invalid_adjustment', [float('nan'), float('inf'), True])
def test_invalid_rerank_adjustment_fails_closed(invalid_adjustment):
    candidate = _candidate('000001', 70.0)
    overlay = _overlay('000001', invalid_adjustment)

    result = _apply([candidate], overlay)[0]

    assert math.isfinite(result['ranking_score'])
    assert result['ranking_score'] == 70.0
    state = result['analysis_profile']['deepseek_rerank']
    assert state['status'] == 'failed'
    assert state['reason'] == 'invalid_item'
    assert state['applied'] is False
    assert all(packet['source'] != 'deepseek_rerank' for packet in result['source_packets'])


def test_rerank_cannot_adjust_a_pool_symbol_outside_submitted_prefix():
    submitted = _candidate('000001', 70.0)
    outside_limit = _candidate('000002', 60.0)
    overlay = _overlay(
        '000002',
        8.0,
        input_symbols=['000001'],
    )

    result = _apply([submitted, outside_limit], overlay)
    by_symbol = {candidate['symbol']: candidate for candidate in result}

    assert by_symbol['000001']['ranking_score'] == 70.0
    assert by_symbol['000002']['ranking_score'] == 60.0
    state = by_symbol['000002']['analysis_profile']['deepseek_rerank']
    assert state['applied'] is False
    assert state['status'] == 'failed'
    assert state['reason'] == 'symbol_not_submitted'
    assert all(
        packet['source'] != 'deepseek_rerank'
        for packet in by_symbol['000002']['source_packets']
    )
    assert overlay['applied'] is False
    assert overlay['adjusted_count'] == 0


@pytest.mark.parametrize(
    ('field', 'invalid_value'),
    [
        ('risk_flags', 1),
        ('risk_flags', 'not-a-list'),
        ('risk_flags', [{'nested': 'object'}]),
        ('positive_evidence', {'not': 'a-list'}),
        ('positive_evidence', [False]),
        ('rationale_ko', {'not': 'text'}),
    ],
)
def test_malformed_rerank_qualitative_fields_fail_closed(field, invalid_value):
    candidate = _candidate('000001', 70.0)
    overlay = _overlay('000001', 5.0)
    overlay['items'][0][field] = invalid_value

    result = _apply([candidate], overlay)[0]

    assert result['ranking_score'] == 70.0
    state = result['analysis_profile']['deepseek_rerank']
    assert state['applied'] is False
    assert state['status'] == 'failed'
    assert state['reason'] == 'invalid_item'
    assert all(packet['source'] != 'deepseek_rerank' for packet in result['source_packets'])


@pytest.mark.parametrize(
    'response_symbol',
    [1, 'prefix-000001-suffix', '1000001', None, {}, ''],
)
def test_rerank_response_symbol_must_exactly_match_submitted_ticker(
    response_symbol,
):
    candidate = _candidate('000001', 70.0)
    overlay = _overlay('000001', 5.0)
    overlay['items'][0]['symbol'] = response_symbol

    result = _apply([candidate], overlay)[0]

    assert result['ranking_score'] == 70.0
    state = result['analysis_profile']['deepseek_rerank']
    assert state['applied'] is False
    assert state['status'] == 'failed'
    assert state['reason'] == 'invalid_item'
    assert all(packet['source'] != 'deepseek_rerank' for packet in result['source_packets'])


def test_non_mapping_rerank_item_is_failed_not_unused():
    candidate = _candidate('000001', 70.0)
    overlay = _overlay('000001', 5.0)
    overlay['items'] = [None]

    result = _apply([candidate], overlay)[0]

    assert result['ranking_score'] == 70.0
    state = result['analysis_profile']['deepseek_rerank']
    assert state['applied'] is False
    assert state['status'] == 'failed'
    assert state['reason'] == 'invalid_item'
