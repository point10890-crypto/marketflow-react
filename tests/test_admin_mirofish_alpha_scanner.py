import json
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

from app.routes.admin_mirofish import admin_mirofish_bp
from app.services.mirofish import alpha_research, alpha_scanner, deepseek_client, learning_policy


@pytest.fixture(autouse=True)
def _disable_tradingview_provider_by_default(monkeypatch):
    monkeypatch.setenv('TRADINGVIEW_MCP_MODE', 'disabled')
    monkeypatch.delenv('TRADINGVIEW_CACHE_PATH', raising=False)
    monkeypatch.delenv('TRADINGVIEW_LIVE_IN_SCANNER', raising=False)


@pytest.fixture(autouse=True)
def _isolate_learning_policy_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(learning_policy, 'ALPHA_BACKTEST_DAILY_PATH', tmp_path / 'alpha_backtest_daily.json')
    monkeypatch.setattr(learning_policy, 'ALPHA_BACKTEST_ROLLING_PATH', tmp_path / 'alpha_backtest_rolling_7d.json')
    monkeypatch.setattr(learning_policy, 'TOP3_METRICS_PATH', tmp_path / 'top3_metrics.json')
    monkeypatch.setattr(learning_policy, 'LEARNING_GUARD_PATH', tmp_path / 'learning_guard.json')
    monkeypatch.delenv('MIROFISH_LEARNING_DISABLED', raising=False)


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def _fresh_artifact_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_artifacts(data_dir):
    fresh_at = _fresh_artifact_timestamp()
    fresh_date = fresh_at[:10]
    (data_dir / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000001,KOSPI,000001.KS,Alpha One',
            '000002,KOSDAQ,000002.KQ,Beta Two',
        ]),
        encoding='utf-8',
    )
    (data_dir / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000001,2026-05-02,Alpha One,100,0,1.0,101,98,99,100000,2026-05-02 16:00:00',
            '000001,2026-05-03,Alpha One,108,0,8.0,110,100,101,600000000,2026-05-03 16:00:00',
            '000002,2026-05-03,Beta Two,50,0,22.0,59,47,48,1000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    _write_json(data_dir / 'screener_leading_latest.json', {
        'timestamp': fresh_at,
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })
    _write_json(data_dir / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': fresh_at},
        'signals': [
            {
                'symbol': '000001',
                'name': 'Alpha One',
                'market': 'KR',
                'composite': {'composite_score': 90, 'entry_ready': 'True'},
            },
        ],
    })
    _write_json(data_dir / 'jongga_v2_latest.json', {
        'date': fresh_date,
        'signals': [
            {
                'stock_code': '000001',
                'stock_name': 'Alpha One',
                'market': 'KOSPI',
                'score': {'total': 12},
                'checklist': {'negative_news': False, 'upper_wick_long': False},
            },
            {
                'stock_code': '000002',
                'stock_name': 'Beta Two',
                'market': 'KOSDAQ',
                'score': {'total': 6},
                'checklist': {'negative_news': True, 'upper_wick_long': True},
            },
        ],
    })


def _seed_advanced_artifacts(data_dir):
    fresh_at = _fresh_artifact_timestamp()
    fresh_date = fresh_at[:10]
    (data_dir / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000010,KOSPI,000010.KS,Steady Accumulator',
            '000020,KOSPI,000020.KS,Single Day Spike',
        ]),
        encoding='utf-8',
    )
    price_rows = ['ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time']
    steady_prices = [100, 102, 103, 105, 107, 109, 111, 114, 116, 120]
    steady_volumes = [900000, 950000, 1000000, 1100000, 1250000, 1400000, 1600000, 1900000, 2300000, 4200000]
    spike_prices = [95, 96, 96, 97, 98, 99, 100, 101, 102, 132]
    spike_volumes = [800000, 820000, 780000, 850000, 870000, 880000, 910000, 920000, 950000, 8000000]
    for index, close in enumerate(steady_prices):
        previous = steady_prices[index - 1] if index else close
        change_rate = ((close / previous) - 1) * 100 if index else 0
        price_rows.append(
            f"000010,2026-05-{index + 1:02d},Steady Accumulator,{close},0,{change_rate:.2f},"
            f"{close * 1.02:.2f},{close * 0.98:.2f},{previous},{steady_volumes[index]},2026-05-{index + 1:02d} 16:00:00"
        )
    for index, close in enumerate(spike_prices):
        previous = spike_prices[index - 1] if index else close
        change_rate = ((close / previous) - 1) * 100 if index else 0
        high = 160 if index == len(spike_prices) - 1 else close * 1.02
        low = 94 if index == len(spike_prices) - 1 else close * 0.98
        price_rows.append(
            f"000020,2026-05-{index + 1:02d},Single Day Spike,{close},0,{change_rate:.2f},"
            f"{high:.2f},{low:.2f},{previous},{spike_volumes[index]},2026-05-{index + 1:02d} 16:00:00"
    )
    (data_dir / 'daily_prices.csv').write_text('\n'.join(price_rows), encoding='utf-8')
    _write_json(data_dir / 'screener_leading_latest.json', {
        'timestamp': fresh_at,
        'results': [
            {'code': '000010', 'name': 'Steady Accumulator', 'score': {'total_enriched': 88}},
            {'code': '000020', 'name': 'Single Day Spike', 'score': {'total_enriched': 90}},
        ],
    })
    _write_json(data_dir / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': fresh_at},
        'signals': [
            {'symbol': '000010', 'name': 'Steady Accumulator', 'market': 'KR', 'composite': {'composite_score': 91, 'entry_ready': 'True'}},
            {'symbol': '000020', 'name': 'Single Day Spike', 'market': 'KR', 'composite': {'composite_score': 92, 'entry_ready': 'True'}},
        ],
    })
    _write_json(data_dir / 'jongga_v2_latest.json', {
        'date': fresh_date,
        'signals': [
            {'stock_code': '000010', 'stock_name': 'Steady Accumulator', 'market': 'KOSPI', 'score': {'total': 13}, 'checklist': {'negative_news': False, 'upper_wick_long': False}},
            {'stock_code': '000020', 'stock_name': 'Single Day Spike', 'market': 'KOSPI', 'score': {'total': 13}, 'checklist': {'negative_news': False, 'upper_wick_long': True}},
        ],
    })


def test_alpha_scanner_creates_ranked_deterministic_run(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})

    assert run['status'] == 'completed'
    assert run['source'] == 'local_marketflow_artifacts'
    assert run['candidate_count'] == 2
    assert run['scoring_schema']['ranking'] == 'rank by alpha_score - 0.55 * risk_score + conviction_adjustment + bounded MCP/outcome adjustments, descending.'
    assert run['goal_harness']['primary_objective'] == 'detect profitable stock candidates from reliable data'
    assert run['goal_harness']['ranking_effect'] == 'direct_bounded_quality_adjustment'
    assert run['candidates'][0]['symbol'] == '000001'
    assert run['candidates'][0]['rank'] == 1
    assert run['candidates'][0]['action'] == 'BUY_CANDIDATE'
    assert run['candidates'][0]['signal_quality'] in {'actionable', 'high_conviction'}
    assert run['candidates'][0]['analysis_profile']['source_count'] == 4
    assert run['candidates'][0]['analysis_profile']['profitability_scorecard']['goal_fit_score'] > 0
    assert run['candidates'][0]['analysis_profile']['profitability_scorecard']['mcp_role'] == 'score_risk_confirmation_with_supporting_signal_limits'
    assert run['candidates'][0]['entry_plan']['risk_reward'] >= 2
    assert run['candidates'][0]['replay_context']['lookahead_safe'] is True
    assert run['candidates'][0]['name'] == run['candidates'][0]['display_name']
    assert run['candidates'][0]['alpha_score'] > run['candidates'][1]['alpha_score']
    assert run['candidates'][1]['risk_score'] > run['candidates'][0]['risk_score']
    assert {'rank', 'symbol', 'name', 'display_name', 'market', 'alpha_score', 'risk_score'} <= set(run['candidates'][0])
    assert run['candidates'][0]['evidence']

    saved = alpha_scanner.read_scanner_run(run['id'])
    candidate_payload = alpha_scanner.read_scanner_candidates(run['id'])

    assert saved['id'] == run['id']
    assert candidate_payload['candidate_count'] == 2
    assert candidate_payload['candidates'][0]['symbol'] == '000001'


def test_alpha_scanner_applies_deepseek_v4_bounded_rerank(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('MIROFISH_DEEPSEEK_RERANK_ENABLED', '1')

    calls = []

    def fake_rerank(candidates, **kwargs):
        calls.append({'candidates': candidates, 'kwargs': kwargs})
        return {
            'provider': 'deepseek',
            'model': 'deepseek-v4-pro',
            'candidate_count': len(candidates),
            'thinking': True,
            'reasoning_effort': 'max',
            'max_abs_adjustment': kwargs.get('max_adjustment', 8),
            'overlay': {
                'portfolio_note_ko': '품질 좋은 후보를 상향합니다.',
                'items': [{
                    'symbol': '000001',
                    'deepseek_conviction': 91,
                    'ranking_adjustment': 5,
                    'risk_flags': [],
                    'positive_evidence': ['다중 소스 확인'],
                    'rationale_ko': '가격, 거래대금, VCP 근거가 동시 확인됩니다.',
                }],
            },
            'usage': {'total_tokens': 42},
            'finish_reason': 'stop',
            'created_at': '2026-05-05T00:00:00+00:00',
        }

    monkeypatch.setattr(deepseek_client, 'rerank_scanner_candidates', fake_rerank)

    run = alpha_scanner.create_scanner_run({'limit': 2})
    first = next(item for item in run['candidates'] if item['symbol'] == '000001')
    artifact = alpha_scanner.read_scanner_run_artifact(run['id'], 'deepseek_rerank.json')

    assert calls
    assert calls[0]['kwargs']['max_adjustment'] == 8
    assert run['providers']['deepseek_rerank']['status'] == 'applied'
    assert run['providers']['deepseek_rerank']['model'] == 'deepseek-v4-pro'
    assert first['analysis_profile']['deepseek_rerank']['ranking_adjustment'] == 5
    assert 'deepseek_v4_confirmed' in first['strategy_tags']
    assert artifact['status'] == 'applied'
    assert artifact['items'][0]['symbol'] == '000001'


def test_alpha_scanner_retries_deepseek_rerank_with_compact_limit(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('MIROFISH_DEEPSEEK_RERANK_ENABLED', '1')
    attempts = []

    def fake_rerank(candidates, **kwargs):
        attempts.append(kwargs.get('limit'))
        if len(attempts) == 1:
            raise deepseek_client.DeepSeekError('DeepSeek response content is not valid JSON')
        return {
            'provider': 'deepseek',
            'model': 'deepseek-v4-pro',
            'candidate_count': len(candidates[:kwargs.get('limit', 5)]),
            'overlay': {'items': []},
        }

    monkeypatch.setattr(deepseek_client, 'rerank_scanner_candidates', fake_rerank)

    run = alpha_scanner.create_scanner_run({'limit': 2})
    artifact = alpha_scanner.read_scanner_run_artifact(run['id'], 'deepseek_rerank.json')

    assert attempts[0] > attempts[1]
    assert artifact['status'] == 'empty_overlay_retry_compact'
    assert artifact['initial_error'].startswith('DeepSeekError:')


def test_alpha_scanner_plan_a_blocks_kind_blacklist(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    _write_json(tmp_path / 'kind_blacklist_latest.json', {
        'schema_version': 'mirofish.kind_blacklist.v1',
        'source': 'KIND/KRX public disclosure risk cache',
        'status': 'fresh',
        'fetched_at': _fresh_artifact_timestamp(),
        'entry_count': 1,
        'entries': {
            '000001': {
                'symbol': '000001',
                'categories': ['관리종목'],
                'risk_level': 'hard_block',
            },
        },
        'lookahead_safe': True,
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    gates = candidate['analysis_profile']['false_signal_gates']
    assert candidate['symbol'] == '000001'
    assert candidate['action'] == 'REJECT'
    assert candidate['alpha_score'] == 0.0
    assert 'kind_blacklist' in candidate['strategy_tags']
    assert 'kind_blacklist' in gates['hard_blockers']
    assert candidate['analysis_profile']['profitability_scorecard']['goal_verdict'] == 'blocked_by_guardrail'

    rejected = alpha_scanner.read_scanner_run_artifact(run['id'], 'rejected_candidates.json')
    reasons = rejected['candidates'][0]['rejection_reasons']
    assert 'false_signal:kind_blacklist' in reasons


def test_alpha_scanner_plan_a_adds_dual_flow_confirmation(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    (tmp_path / 'all_institutional_trend_data.csv').write_text(
        '\n'.join([
            'ticker,scrape_date,institutional_net_buy_20d,institutional_net_buy_5d,foreign_net_buy_20d,foreign_net_buy_5d',
            '000001,2026-05-03,200000000,80000000,300000000,90000000',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    profile = candidate['analysis_profile']
    scorecard = profile['profitability_scorecard']
    assert profile['capital_flow_confirmation']['passed'] is True
    assert profile['source_count'] == 5
    assert candidate['alpha_score'] > profile['base_alpha_score']
    assert 'dual_flow_buy' in candidate['strategy_tags']
    assert 'all_institutional_trend_data.csv' in candidate['replay_context']['data_sources']
    assert 'capital_flow' not in scorecard['missing_confirmations']


def test_alpha_scanner_applies_kis_live_price_flow_to_scores(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    fresh_at = _fresh_artifact_timestamp()
    _write_json(tmp_path / 'kis_live_snapshot_latest.json', {
        'generated_at': fresh_at,
        'entries': {
            '000001': {
                'symbol': '000001',
                'source': 'KIS API',
                'fetched_at': fresh_at,
                'confidence': 0.96,
                'quote': {
                    'price': 112,
                    'change_pct': 9.0,
                    'trading_value': 220_000_000_000,
                    'volume': 3_500_000,
                },
                'investor': {
                    'foreign_net_qty': 12000,
                    'institution_net_qty': 8000,
                    'foreign_net_value': 4_500_000_000,
                    'institution_net_value': 3_000_000_000,
                },
            },
        },
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    profile = candidate['analysis_profile']
    adjustment = profile['mcp_quality_adjustment']
    assert profile['kis_live_overlay']['applied'] is True
    assert adjustment['alpha_delta'] > 0
    assert 'kis_live_dual_flow' in candidate['strategy_tags']
    assert candidate['price']['current_price'] == 112
    assert candidate['price']['trading_value'] == 220_000_000_000
    assert 'KIS API: live price/investor flow' in candidate['replay_context']['data_sources']


def test_alpha_scanner_applies_dart_event_as_risk_filter(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    fresh_at = _fresh_artifact_timestamp()
    _write_json(tmp_path / 'dart_event_latest.json', {
        'generated_at': fresh_at,
        'entries': {
            '000001': {
                'symbol': '000001',
                'risk_level': 'high',
                'risk_flags': ['audit_opinion'],
                'summary': 'audit_opinion review required',
                'source_grade': 'S',
            },
        },
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    adjustment = candidate['analysis_profile']['mcp_quality_adjustment']
    assert adjustment['risk_delta'] > 0
    assert 'dart_hard_risk' in candidate['strategy_tags']
    assert candidate['risk_score'] > candidate['analysis_profile']['base_risk_score']
    assert 'dart_event_latest.json' in candidate['replay_context']['data_sources']


def test_alpha_scanner_limits_news_theme_social_to_supporting_signal(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    fresh_at = _fresh_artifact_timestamp()
    _write_json(tmp_path / 'news_theme_social_latest.json', {
        'generated_at': fresh_at,
        'entries': {
            '000001': {
                'symbol': '000001',
                'sentiment_score': 95,
                'social_heat': 92,
                'source_grade': 'C',
            },
        },
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    adjustment = candidate['analysis_profile']['mcp_quality_adjustment']
    assert adjustment['alpha_delta'] < 0
    assert adjustment['risk_delta'] > 0
    assert 'news_theme_social_supporting_only' in candidate['strategy_tags']
    assert 'support_signal_without_core_confirmation' in candidate['strategy_tags']
    assert 'news_theme_social_latest.json' in candidate['replay_context']['data_sources']


def test_alpha_scanner_applies_replay_safe_outcome_memory(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {
        'available': True,
        'applied_to_scoring': True,
        'source': 'workflow_outcomes',
        'lookahead_safe': True,
        'evaluated_count': 20,
        'hit_rate_recent': 0.72,
        'recommendations': {
            'baseline_hit_rate': 0.50,
            'tag_score_adjust': {'leading_screener': 1.4},
        },
    })

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    profile = candidate['analysis_profile']
    assert profile['mcp_ranking_delta'] > 0
    assert profile['performance_memory']['applied'] is True
    assert profile['performance_memory']['tag_adjustment']['matched_tags']['leading_screener'] == 1.4
    assert 'outcome_tag_memory_adjusted' in candidate['strategy_tags']


def test_alpha_scanner_applies_maturing_learning_caps_to_outcome_memory(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    policy = learning_policy.build_learning_policy(
        {
            'available': True,
            'evaluated_count': 20,
            'hit_rate_recent': 0.72,
            'lookahead_safe': True,
        },
        daily_report={
            'generated_at': _fresh_artifact_timestamp(),
            'lookahead_safe': True,
            'enhanced': {
                'sample_count': 52,
                'expectancy_r': 0.19,
                'information_coefficient': 0.09,
            },
        },
        rolling_report={},
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {
        'available': True,
        'applied_to_scoring': True,
        'source': 'workflow_outcomes',
        'lookahead_safe': True,
        'evaluated_count': 20,
        'hit_rate_recent': 0.72,
        'recommendations': {
            'baseline_hit_rate': 0.50,
            'tag_score_adjust': {'leading_screener': 1.4},
        },
        'learning_policy': policy,
    })

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    profile = run['candidates'][0]['analysis_profile']
    assert profile['performance_memory']['learning_policy_status'] == 'bounded_maturing'
    assert profile['performance_memory']['tag_adjustment']['ranking_delta'] == 0.75
    assert profile['performance_memory']['tag_adjustment']['learning_policy_status'] == 'bounded_maturing'


def test_alpha_scanner_blocks_outcome_memory_when_learning_policy_observes_only(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {
        'available': True,
        'applied_to_scoring': False,
        'source': 'workflow_outcomes',
        'lookahead_safe': True,
        'evaluated_count': 20,
        'hit_rate_recent': 0.72,
        'recommendations': {
            'baseline_hit_rate': 0.50,
            'tag_score_adjust': {'leading_screener': 1.4},
        },
        'learning_policy': {
            'score_control': {
                'outcome_memory_enabled': False,
                'status': 'observe_only',
                'reason': 'backtest sample is below the minimum learning gate',
            },
        },
    })

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    profile = candidate['analysis_profile']
    assert profile['mcp_ranking_delta'] == 0
    assert profile['performance_memory']['applied'] is False
    assert profile['performance_memory']['reason'] == 'backtest sample is below the minimum learning gate'
    assert 'outcome_tag_memory_adjusted' not in candidate['strategy_tags']


def test_performance_advisory_merges_agent_overlay(monkeypatch):
    from app.services.mirofish import agent_actions, outcome_tracker

    monkeypatch.setattr(
        outcome_tracker,
        'get_advisory_feedback',
        lambda **_kw: {
            'evaluated_count': 20,
            'hit_rate_recent': 0.6,
            'horizon_days': 5,
            'lookahead_safe': True,
            'asof': '2026-06-12T00:00:00+00:00',
            'workflow_count_scanned': 10,
            'recommendations': {
                'tag_score_adjust': {'volume_surge': 0.5},
                'baseline_hit_rate': 0.5,
            },
        },
    )
    monkeypatch.setattr(
        agent_actions,
        'scoring_overlay_deltas',
        lambda: {'volume_surge': 1.0, 'agent_only_tag': -1.5},
    )

    advisory = alpha_scanner._performance_advisory()
    adjust = advisory['recommendations']['tag_score_adjust']

    assert adjust['volume_surge'] == 1.5
    assert adjust['agent_only_tag'] == -1.5
    assert advisory['recommendations']['agent_overlay_applied'] is True


def test_performance_advisory_clamps_merged_overlay(monkeypatch):
    from app.services.mirofish import agent_actions, outcome_tracker

    monkeypatch.setattr(
        outcome_tracker,
        'get_advisory_feedback',
        lambda **_kw: {
            'evaluated_count': 20,
            'hit_rate_recent': 0.6,
            'horizon_days': 5,
            'lookahead_safe': True,
            'asof': '2026-06-12T00:00:00+00:00',
            'workflow_count_scanned': 10,
            'recommendations': {
                'tag_score_adjust': {'volume_surge': 1.8},
                'baseline_hit_rate': 0.5,
            },
        },
    )
    monkeypatch.setattr(agent_actions, 'scoring_overlay_deltas', lambda: {'volume_surge': 1.8})

    advisory = alpha_scanner._performance_advisory()

    assert advisory['recommendations']['tag_score_adjust']['volume_surge'] == 2.0


def test_alpha_scanner_plan_a_blocks_credit_pressure_cache(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    _write_json(tmp_path / 'credit_balance_latest.json', {
        'schema_version': 'mirofish.credit_balance.v1',
        'source': 'KRX credit balance cache',
        'status': 'fresh',
        'fetched_at': _fresh_artifact_timestamp(),
        'entry_count': 1,
        'entries': {
            '000001': {
                'symbol': '000001',
                'balance_shares': 6000000,
                'listed_shares': 100000000,
                'credit_ratio_pct': 6.0,
            },
        },
        'lookahead_safe': True,
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    assert candidate['action'] == 'REJECT'
    assert 'credit_pressure' in candidate['analysis_profile']['false_signal_gates']['hard_blockers']
    assert 'credit_balance_latest.json' in candidate['replay_context']['data_sources']


def test_alpha_scanner_plan_a_env_toggle_disables_gates(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    _write_json(tmp_path / 'kind_blacklist_latest.json', {
        'schema_version': 'mirofish.kind_blacklist.v1',
        'source': 'KIND/KRX public disclosure risk cache',
        'status': 'fresh',
        'fetched_at': _fresh_artifact_timestamp(),
        'entry_count': 1,
        'entries': {'000001': {'symbol': '000001', 'categories': ['관리종목']}},
        'lookahead_safe': True,
    })
    monkeypatch.setenv('ENABLE_ALPHA_PHASE_1_GATES', '0')
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000001'], 'limit': 5})

    candidate = run['candidates'][0]
    assert candidate['analysis_profile']['false_signal_gates']['enabled'] is False
    assert candidate['action'] != 'REJECT'


def test_alpha_scanner_persists_analysis_artifacts(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 1})

    assert run['candidate_count'] == 1
    assert run['screened_count'] == 2
    assert run['rejected_candidate_count'] >= 1
    assert run['performance_advisory']['applied_to_scoring'] is False
    assert run['performance_advisory']['source'] == 'workflow_outcomes'
    assert run['analysis_artifacts']['feature_vectors'].endswith('/feature-vectors')
    assert run['analysis_artifacts']['evidence_ledger'].endswith('/evidence')
    assert run['analysis_artifacts']['rejected_candidates'].endswith('/rejects')
    assert run['candidates'][0]['analysis_profile']['evidence_quality']['grade'] in {'strong', 'moderate', 'weak'}
    assert run['candidates'][0]['analysis_profile']['confidence_cap'] <= 0.95

    features = alpha_scanner.read_scanner_run_artifact(run['id'], 'feature_vectors.json')
    ledger = alpha_scanner.read_scanner_run_artifact(run['id'], 'evidence_ledger.json')
    rejected = alpha_scanner.read_scanner_run_artifact(run['id'], 'rejected_candidates.json')

    assert features['run_id'] == run['id']
    assert features['feature_count'] == 1
    assert features['features'][0]['symbol'] == run['candidates'][0]['symbol']
    assert features['features'][0]['lookahead_safe'] is True
    assert features['features'][0]['profitability_scorecard']['ranking_effect'] == 'direct_bounded_quality_adjustment'
    assert features['features'][0]['goal_fit_score'] == features['features'][0]['profitability_scorecard']['goal_fit_score']
    assert features['features'][0]['data_sources']
    assert ledger['candidate_count'] == 1
    assert any(item['selection_status'] == 'selected' for item in ledger['items'])
    assert any(item['selection_status'] == 'rejected' for item in ledger['items'])
    assert rejected['rejected_candidate_count'] >= 1
    assert rejected['candidates'][0]['rejection_reasons']
    assert rejected['candidates'][0]['feature_vector']['symbol'] == rejected['candidates'][0]['symbol']


def test_alpha_research_snapshot_recommends_mcp_evidence_clusters(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 1})
    snapshot = alpha_research.build_alpha_research_snapshot(run['id'])

    assert snapshot['ok'] is True
    assert snapshot['schema_version'] == 'mirofish.alpha_research.v1'
    assert snapshot['run']['id'] == run['id']
    assert 'highest forward profit potential' in snapshot['mission']['primary_objective']
    assert snapshot['mission']['mcp_role'].startswith('supporting')
    assert snapshot['lookahead_safe'] is True
    assert snapshot['mutates_scanner_scores'] is False
    assert snapshot['profit_detection_scorecard']['primary_objective'] == 'detect profitable stock candidates from reliable data'
    assert snapshot['profit_detection_scorecard']['ranking_effect'] == 'direct_bounded_quality_adjustment'
    assert snapshot['candidate_diagnostics'][0]['symbol'] == run['candidates'][0]['symbol']
    assert snapshot['candidate_diagnostics'][0]['goal_fit_score'] > 0
    assert snapshot['candidate_diagnostics'][0]['profitability_scorecard']['goal'] == 'detect profitable stock candidates from reliable data'
    assert any(
        item['code'] == 'capital_flow_confirmation_missing'
        for item in snapshot['research_findings']
    )
    assert any(
        call['tool'] == 'get_kiwoom_institution_trend'
        for call in snapshot['candidate_diagnostics'][0]['recommended_mcp_calls']
    )
    assert snapshot['automation_mcp_blueprint']['implemented_tools'][0]['name'] == 'get_alpha_research_snapshot'


def test_alpha_scanner_reads_price_chart_from_daily_prices(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))

    chart = alpha_scanner.read_price_chart('000001', limit=20)

    assert chart['symbol'] == '000001'
    assert chart['source'] == 'daily_prices.csv'
    assert chart['count'] == 2
    assert chart['target'] == 'Alpha One'
    assert chart['chart'][-1] == {
        'date': '2026-05-03',
        'open': 101.0,
        'high': 110.0,
        'low': 100.0,
        'close': 108.0,
        'volume': 600000000,
        'change_rate': 8.0,
        'update_time': '2026-05-03 16:00:00',
    }


def test_alpha_scanner_applies_tradingview_cached_confirmation(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    cache_path = tmp_path / 'tradingview_signals.json'
    _write_json(cache_path, {
        'signals': [
            {
                'symbol': '000001',
                'recommendation': 'STRONG_BUY',
                'timeframes': {'1D': 'BUY', '1W': 'STRONG_BUY'},
                'relative_volume': 1.8,
                'fetched_at': '2026-05-10T00:00:00+00:00',
            },
        ],
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('TRADINGVIEW_MCP_MODE', 'cache')
    monkeypatch.setenv('TRADINGVIEW_CACHE_PATH', str(cache_path))
    monkeypatch.setenv('TRADINGVIEW_CACHE_TTL_SEC', '99999999')

    run = alpha_scanner.create_scanner_run({'limit': 5})
    by_symbol = {candidate['symbol']: candidate for candidate in run['candidates']}
    candidate = by_symbol['000001']

    assert run['providers']['tradingview']['provider'] == 'tradingview_mcp'
    assert run['providers']['tradingview']['enabled'] is True
    assert candidate['analysis_profile']['base_source_count'] == 4
    assert candidate['analysis_profile']['source_count'] == 5
    assert candidate['analysis_profile']['tradingview_adjustment']['applied'] is True
    assert candidate['analysis_profile']['tradingview_adjustment']['recommendation'] == 'STRONG_BUY'
    assert candidate['tradingview']['applied'] is True
    assert candidate['alpha_score'] > candidate['analysis_profile']['base_alpha_score']
    assert candidate['risk_score'] <= candidate['analysis_profile']['base_risk_score']
    assert 'tradingview_mcp' in candidate['replay_context']['data_sources']
    assert any(item['source'] == 'tradingview_mcp' for item in candidate['evidence'])
    assert 'tradingview_confirmed' in candidate['strategy_tags']


def test_alpha_scanner_applies_tradingview_warning_filter(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    cache_path = tmp_path / 'tradingview_signals.json'
    _write_json(cache_path, {
        'signals': [
            {
                'symbol': '000001',
                'recommendation': 'SELL',
                'timeframes': {'1D': 'SELL', '1W': 'NEUTRAL'},
                'relative_volume': 0.6,
                'fetched_at': '2026-05-10T00:00:00+00:00',
            },
        ],
    })
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('TRADINGVIEW_MCP_MODE', 'cache')
    monkeypatch.setenv('TRADINGVIEW_CACHE_PATH', str(cache_path))
    monkeypatch.setenv('TRADINGVIEW_CACHE_TTL_SEC', '99999999')

    run = alpha_scanner.create_scanner_run({'limit': 5})
    candidate = {item['symbol']: item for item in run['candidates']}['000001']
    adjustment = candidate['analysis_profile']['tradingview_adjustment']

    assert adjustment['applied'] is True
    assert adjustment['alpha_delta'] < 0
    assert adjustment['risk_delta'] > 0
    assert candidate['alpha_score'] < candidate['analysis_profile']['base_alpha_score']
    assert candidate['risk_score'] > candidate['analysis_profile']['base_risk_score']
    assert 'tradingview_warning' in candidate['strategy_tags']


def test_alpha_scanner_advanced_analysis_penalizes_single_day_spikes(tmp_path, monkeypatch):
    _seed_advanced_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    by_symbol = {candidate['symbol']: candidate for candidate in run['candidates']}

    steady = by_symbol['000010']
    spike = by_symbol['000020']
    assert run['candidates'][0]['symbol'] == '000010'
    assert steady['ranking_score'] > spike['ranking_score']
    assert steady['analysis_profile']['profitability_scorecard']['goal_fit_score'] > spike['analysis_profile']['profitability_scorecard']['goal_fit_score']
    assert spike['analysis_profile']['profitability_scorecard']['goal_verdict'] in {'watch_only', 'reject_for_now', 'blocked_by_guardrail'}
    assert steady['analysis_profile']['trend_quality'] > 0
    assert steady['analysis_profile']['volume_accumulation'] > 0
    assert steady['analysis_profile']['volume_ratio'] > 1
    assert steady['signal_quality'] in {'actionable', 'high_conviction'}
    assert spike['risk_score'] > steady['risk_score']
    assert spike['analysis_profile']['over_ma20_pct'] > steady['analysis_profile']['over_ma20_pct']
    assert spike['action'] != 'BUY_CANDIDATE'


def test_alpha_scanner_handles_missing_optional_artifacts(tmp_path, monkeypatch):
    (tmp_path / 'daily_prices.csv').write_text(
        '\n'.join([
            'ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time',
            '000003,2026-05-03,Fallback Three,20,0,5.0,21,19,20,3000000,2026-05-03 16:00:00',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 3})

    assert run['candidate_count'] == 1
    assert run['freshness']['status'] == 'partial'
    assert run['freshness']['missing_files'] >= 3
    assert run['candidates'][0]['symbol'] == '000003'
    assert run['candidates'][0]['source'] == 'local_marketflow_artifacts'


def test_alpha_scanner_prefers_canonical_stock_name_alias(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    (tmp_path / 'ticker_to_yahoo_map.csv').write_text(
        '\n'.join([
            'ticker,market,yahoo_ticker,name',
            '000001,KOSPI,000001.KS,???',
            '000002,KOSDAQ,000002.KQ,???',
        ]),
        encoding='utf-8',
    )
    (tmp_path / 'korean_stocks_list.csv').write_text(
        '\n'.join([
            'ticker,name,market',
            '000001,정식알파,KOSPI',
            '000002,정식베타,KOSDAQ',
        ]),
        encoding='utf-8',
    )
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})

    by_symbol = {candidate['symbol']: candidate for candidate in run['candidates']}
    assert by_symbol['000001']['display_name'] == '정식알파'
    assert by_symbol['000001']['name'] == '정식알파'
    assert by_symbol['000001']['market'] == 'KOSPI'


def test_alpha_scanner_can_filter_requested_symbols(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'symbols': ['000002'], 'limit': 5})

    assert run['candidate_count'] == 1
    assert run['requested_symbols'] == ['000002']
    assert run['candidates'][0]['symbol'] == '000002'


def test_alpha_scanner_latest_run_returns_newest_and_skips_bad_files(tmp_path, monkeypatch):
    runs_root = tmp_path / 'runs'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(runs_root))
    older_dir = runs_root / 'mfas_20260504000000_aaaaaaaaaaaa'
    newer_dir = runs_root / 'mfas_20260505000000_bbbbbbbbbbbb'
    bad_dir = runs_root / 'mfas_20260506000000_badbadbadbad'
    unsafe_dir = runs_root / '..escape'
    for path in (older_dir, newer_dir, bad_dir, unsafe_dir):
        path.mkdir(parents=True, exist_ok=True)
    _write_json(older_dir / 'run.json', {
        'id': older_dir.name,
        'status': 'completed',
        'generated_at': '2026-05-04T00:00:00+00:00',
        'candidate_count': 1,
        'candidates': [{'symbol': '000001'}],
    })
    _write_json(newer_dir / 'run.json', {
        'id': newer_dir.name,
        'status': 'completed',
        'generated_at': '2026-05-05T00:00:00+00:00',
        'candidate_count': 2,
        'candidates': [{'symbol': '000002'}],
    })
    (bad_dir / 'run.json').write_text('{bad json', encoding='utf-8')

    latest = alpha_scanner.read_latest_scanner_run()
    summaries = alpha_scanner.list_scanner_runs(limit=10)

    assert latest['id'] == newer_dir.name
    assert latest['candidates'][0]['symbol'] == '000002'
    assert [item['id'] for item in summaries] == [newer_dir.name, older_dir.name]
    assert 'candidates' not in summaries[0]


def test_alpha_scanner_status_without_runs_reports_schedule_and_freshness(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setenv('ALPHA_SCANNER_TIMES', '09:20,bad,16:10')

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['enabled'] is True
    assert status['last_run_at'] is None
    assert status['scheduled_times'] == ['09:20', '16:10']
    assert status['next_scheduled_at'].startswith('2026-05-06T09:20:00')
    assert status['freshness']['available_files'] == 5
    assert status['source_files']


def test_alpha_scanner_status_uses_latest_run_metadata(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 17, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['last_run_id'] == run['id']
    assert status['last_run_at'] == run['generated_at']
    assert status['candidate_count'] == run['candidate_count']
    assert status['freshness'] == run['freshness']
    assert status['next_scheduled_at'].startswith('2026-05-07T09:20:00')


def test_alpha_scanner_status_treats_scheduler_last_run_as_kst(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'scheduler_last_run.json', {
        'alpha_scanner_0920': '2026-05-11T09:20:30',
        'alpha_scanner_monitor': '2026-05-11T09:24:30',
        'crypto': '2026-05-11T12:00:00',
    })

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 11, 9, 25, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['scheduler_last_run_at'] == '2026-05-11T09:24:30+09:00'


def test_alpha_scanner_status_reports_current_source_freshness(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    run = alpha_scanner.create_scanner_run({'limit': 5})
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
        ],
    })

    status = alpha_scanner.get_scanner_schedule_status(
        now=datetime(2026, 5, 6, 17, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert status['last_run_id'] == run['id']
    assert status['latest_run_freshness'] == run['freshness']
    assert status['freshness']['status'] == 'stale'
    assert any(
        item['file'] == 'data/screener_leading_latest.json'
        and item['freshness'] == 'stale'
        and item['max_age_days'] == 7
        for item in status['source_files']
    )


def test_alpha_scanner_alert_check_only_returns_new_events(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = str(tmp_path / 'alert_state.json')

    first = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
    )
    second = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
    )

    assert first['new_event_count'] == 1
    assert first['events'][0]['candidate']['symbol'] == '000001'
    assert 'MiroFish 알파 스캐너 신규 후보' in first['message']
    assert 'Alpha One' in first['message']
    assert '매수 후보' in first['message']
    assert second['new_event_count'] == 0
    assert second['events'] == []


def test_alpha_scanner_alert_check_can_defer_state_until_send_success(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = str(tmp_path / 'alert_state.json')

    pending = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )
    retry = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )
    state = alpha_scanner.commit_scanner_alert_events(pending)
    after_commit = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=state_path,
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert pending['new_event_count'] == 1
    assert retry['new_event_count'] == 1
    assert state['sent_event_count'] == 1
    assert state['version'] == 2
    assert state['last_sent_at'] == state['recent_sent_events'][0]['sent_at']
    assert state['recent_sent_events'][0]['symbol'] == '000001'
    assert state['recent_sent_events'][0]['price']['current_price'] == 108.0
    persisted = json.loads((tmp_path / 'alert_state.json').read_text(encoding='utf-8'))
    assert persisted['history'][0]['event_key'] == state['recent_sent_events'][0]['event_key']
    assert after_commit['new_event_count'] == 0


def test_alpha_scanner_alert_check_blocks_stale_core_source_alerts(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is True
    assert result['blocked_reason'] == 'source_freshness:stale'
    assert result['new_event_count'] == 0
    assert '알림 차단' in result['message']


def test_alpha_scanner_alert_check_allows_stale_supporting_sources(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'vcp_kr_latest.json', {
        'metadata': {'generated_at': '2026-01-01T00:00:00+00:00'},
        'signals': [
            {
                'symbol': '000001',
                'name': 'Alpha One',
                'market': 'KR',
                'composite': {'composite_score': 90, 'entry_ready': 'True'},
            },
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is False
    assert result['source_warning'] == 'source_freshness:stale'
    assert result['new_event_count'] == 1


def test_alpha_scanner_alert_check_can_allow_stale_core_for_workflow_batches(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'timestamp': '2026-01-01T00:00:00+00:00',
        'results': [
            {'code': '000001', 'name': 'Alpha One', 'score': {'total_enriched': 80}},
            {'code': '000002', 'name': 'Beta Two', 'score': {'total_enriched': 30}},
        ],
    })

    result = alpha_scanner.run_scanner_alert_check(
        {'limit': 5},
        state_path=str(tmp_path / 'alert_state.json'),
        min_alpha=70,
        max_risk=45,
        commit_state=False,
        block_on_stale=False,
    )

    assert result['run']['freshness']['status'] == 'stale'
    assert result['alert_blocked'] is False
    assert result['source_warning'] == 'source_freshness:stale'
    assert result['new_event_count'] == 1


def test_alpha_scanner_realtime_monitor_sends_after_source_change(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')
    sent_messages = []

    first = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )
    second = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )

    assert first['status'] == 'sent'
    assert first['new_event_count'] == 1
    assert first['telegram_sent'] is True
    assert first['state_committed'] is True
    assert sent_messages and 'Alpha One' in sent_messages[0]
    assert second['status'] == 'unchanged'
    assert second['source_changed'] is False
    assert second['monitor_state_committed'] is True
    assert second['monitor_state']['last_status'] == 'unchanged'
    saved_state = json.loads((tmp_path / 'monitor_state.json').read_text(encoding='utf-8'))
    assert saved_state['last_status'] == 'unchanged'
    assert saved_state['last_checked_at']


def test_alpha_scanner_realtime_monitor_rechecks_legacy_blocked_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = tmp_path / 'monitor_state.json'
    alert_state_path = str(tmp_path / 'alert_state.json')
    source = alpha_scanner.get_scanner_source_signature()
    _write_json(monitor_state_path, {
        'version': 1,
        'last_status': 'blocked',
        'last_source_fingerprint': source['fingerprint'],
        'last_processed_at': '2026-05-10T00:00:00+00:00',
    })
    sent_messages = []

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=str(monitor_state_path),
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        send_fn=lambda message: sent_messages.append(message) or True,
    )

    assert result['status'] == 'sent'
    assert result['source_changed'] is True
    assert result['monitor_state']['version'] == alpha_scanner.MONITOR_STATE_VERSION
    assert sent_messages and 'Alpha One' in sent_messages[0]


def test_alpha_scanner_realtime_monitor_retries_when_telegram_fails(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    first = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        retry_seconds=300,
        send_fn=lambda message: False,
    )
    second = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        retry_seconds=300,
        send_fn=lambda message: True,
    )

    assert first['status'] == 'send_failed'
    assert first['state_committed'] is False
    assert second['status'] == 'retry_wait'


def test_alpha_scanner_realtime_monitor_dry_run_does_not_commit_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=70,
        max_risk=45,
        commit_monitor_state=False,
        send_fn=None,
    )

    assert result['status'] == 'pending_send'
    assert result['monitor_state_committed'] is False
    assert not (tmp_path / 'monitor_state.json').exists()
    assert not (tmp_path / 'alert_state.json').exists()


def test_alpha_scanner_realtime_monitor_dry_run_no_events_does_not_commit_state(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monitor_state_path = str(tmp_path / 'monitor_state.json')
    alert_state_path = str(tmp_path / 'alert_state.json')

    result = alpha_scanner.run_scanner_realtime_monitor_check(
        {'limit': 5},
        monitor_state_path=monitor_state_path,
        alert_state_path=alert_state_path,
        min_alpha=999,
        max_risk=45,
        commit_monitor_state=False,
        send_fn=None,
    )

    assert result['status'] == 'no_new_events'
    assert result['state_committed'] is False
    assert result['monitor_state_committed'] is False
    assert not (tmp_path / 'monitor_state.json').exists()
    assert not (tmp_path / 'alert_state.json').exists()


def test_alpha_scanner_diagnostics_reports_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)

    diagnostics = alpha_scanner.get_scanner_diagnostics(
        now=datetime(2026, 5, 6, 8, 0, tzinfo=timezone(timedelta(hours=9))),
    )

    assert diagnostics['health'] == 'error'
    assert diagnostics['source']['missing_files'] == len(alpha_scanner.WATCHED_SOURCE_FILES)
    assert diagnostics['source_freshness']['status'] == 'missing'
    assert diagnostics['source_freshness']['missing_required_files'] == 5
    assert len(diagnostics['source_files']) == len(alpha_scanner.WATCHED_SOURCE_FILES)
    assert diagnostics['schedule']['freshness']['status'] == 'missing'
    assert {issue['code'] for issue in diagnostics['issues']} >= {
        'missing_source_files',
        'telegram_not_configured',
    }


def test_alpha_scanner_rejects_unsafe_run_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))

    try:
        alpha_scanner.read_scanner_run('../escape')
    except ValueError as exc:
        assert 'invalid scanner run_id' in str(exc)
    else:
        raise AssertionError('unsafe scanner run id should be rejected')


def test_admin_mirofish_scanner_routes_are_registered():
    app = Flask(__name__)
    app.register_blueprint(admin_mirofish_bp, url_prefix='/api/admin/mirofish')

    rules = {str(rule) for rule in app.url_map.iter_rules()}

    assert '/api/admin/mirofish/scanner/runs' in rules
    assert '/api/admin/mirofish/scanner/status' in rules
    assert '/api/admin/mirofish/scanner/diagnostics' in rules
    assert '/api/admin/mirofish/scanner/alerts/check' in rules
    assert '/api/admin/mirofish/scanner/alerts/state' in rules
    assert '/api/admin/mirofish/scanner/monitor/check' in rules
    assert '/api/admin/mirofish/scanner/monitor/status' in rules
    assert '/api/admin/mirofish/scanner/runs/latest' in rules
    assert '/api/admin/mirofish/scanner/research' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/candidates' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/feature-vectors' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/evidence' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/rejects' in rules
    assert '/api/admin/mirofish/scanner/runs/<run_id>/research' in rules
    assert '/api/admin/mirofish/tradingview/status' in rules
    assert '/api/admin/mirofish/kalman/status' in rules
    assert '/api/admin/mirofish/kalman/runs' in rules
    assert '/api/admin/mirofish/kalman/runs/<run_id>' in rules
    assert '/api/admin/mirofish/kalman/runs/<run_id>/signals' in rules
    assert '/api/admin/mirofish/price-chart/<symbol>' in rules
    assert '/api/admin/mirofish/workflow/status' in rules
    assert '/api/admin/mirofish/workflow/scan-analyze' in rules
    assert '/api/admin/mirofish/learning/readiness' in rules
