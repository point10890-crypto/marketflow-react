import copy
import json
import threading
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask

import app.routes.admin_mirofish as admin_mirofish_routes
import app as marketflow_app
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
    packets = run['candidates'][0]['source_packets']
    assert packets and all(packet.get('observed_at') for packet in packets)
    assert run['candidates'][0]['source_cutoff'] == max(
        packet['observed_at'] for packet in packets
    )
    assert run['candidates'][0]['source_cutoff'] != run['generated_at']
    price_packet = next(packet for packet in packets if packet['source'] == 'daily_prices.csv')
    assert price_packet['content']['price']['current_price'] == 108.0
    assert price_packet['content']['evidence']

    saved = alpha_scanner.read_scanner_run(run['id'])
    candidate_payload = alpha_scanner.read_scanner_candidates(run['id'])

    assert saved['id'] == run['id']
    assert candidate_payload['candidate_count'] == 2
    assert candidate_payload['candidates'][0]['symbol'] == '000001'


def test_daily_bar_date_uses_korean_close_and_is_excluded_before_close():
    payload = {
        'price': {
            'date': '2026-09-03', 'open': 100, 'high': 110, 'low': 95,
            'current_price': 108, 'volume': 1_000,
        },
        'price_metrics': {'trend_5d_pct': 12.0},
    }
    before_close = '2026-09-03T05:00:00+00:00'  # 14:00 Asia/Seoul
    after_close = '2026-09-03T07:00:00+00:00'   # 16:00 Asia/Seoul

    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'daily_prices.csv': payload},
        required_sources=['daily_prices.csv'], cutoff_ceiling=before_close,
    )
    assert packets == [] and cutoff is None and missing == ['daily_prices.csv']

    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'daily_prices.csv': payload},
        required_sources=['daily_prices.csv'], cutoff_ceiling=after_close,
    )
    assert missing == []
    assert packets[0]['observed_at'] == '2026-09-03T06:30:00+00:00'
    assert cutoff == '2026-09-03T06:30:00+00:00'


@pytest.mark.parametrize('date_only_update', ['2026-09-03', '20260903'])
def test_daily_bar_date_only_update_field_does_not_bypass_session_close(date_only_update):
    payload = {
        'date': '2026-09-03',
        'updated_at': date_only_update,
        'current_price': 70000,
    }

    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'daily_prices.csv': payload},
        required_sources=['daily_prices.csv'],
        cutoff_ceiling='2026-09-03T05:00:00+00:00',
    )

    assert packets == [] and cutoff is None
    assert missing == ['daily_prices.csv']


def test_institutional_date_only_flow_is_available_at_korean_close():
    payload = {
        'scrape_date': '2026-09-03',
        'foreign_net_buy_5d': '1000',
        'institutional_net_buy_20d': '2000',
    }

    before, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'all_institutional_trend_data.csv': payload},
        required_sources=['all_institutional_trend_data.csv'],
        cutoff_ceiling='2026-09-03T05:00:00+00:00',
    )
    assert before == [] and cutoff is None
    assert missing == ['all_institutional_trend_data.csv']

    after, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'all_institutional_trend_data.csv': payload},
        required_sources=['all_institutional_trend_data.csv'],
        cutoff_ceiling='2026-09-03T07:00:00+00:00',
    )
    assert missing == []
    assert after[0]['observed_at'] == '2026-09-03T06:30:00+00:00'
    assert after[0]['content']['foreign_net_buy_5d'] == '1000'
    assert cutoff == '2026-09-03T06:30:00+00:00'


def test_institutional_date_only_flow_uses_later_precise_file_availability(monkeypatch):
    payload = {
        'scrape_date': '2026-09-03',
        'foreign_net_buy_5d': '1000',
        'institutional_net_buy_20d': '2000',
    }
    monkeypatch.setattr(
        alpha_scanner, '_source_files',
        lambda _artifacts: [{
            'file': 'data/all_institutional_trend_data.csv',
            'modified_at': '2026-09-03T07:20:00+00:00',
        }],
    )

    before, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'all_institutional_trend_data.csv': payload},
        required_sources=['all_institutional_trend_data.csv'],
        cutoff_ceiling='2026-09-03T07:00:00+00:00',
    )
    assert before == [] and cutoff is None
    assert missing == ['all_institutional_trend_data.csv']

    after, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={'all_institutional_trend_data.csv': payload},
        required_sources=['all_institutional_trend_data.csv'],
        cutoff_ceiling='2026-09-03T07:30:00+00:00',
    )
    assert missing == []
    assert after[0]['observed_at'] == '2026-09-03T07:20:00+00:00'
    assert cutoff == '2026-09-03T07:20:00+00:00'


def test_date_only_closing_artifact_uses_precise_file_availability():
    source = 'jongga_v2_latest.json'
    payload = {'stock_code': '005930', 'score': 88, 'date': '2026-09-03'}
    artifacts = {
        'jongga': {
            'generated_at': '2026-09-03',
            'mtime': '2026-09-03T07:15:00+00:00',
        },
    }

    before, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts=artifacts,
        sources={source: payload}, required_sources=[source],
        cutoff_ceiling='2026-09-03T07:00:00+00:00',
    )
    assert before == [] and cutoff is None and missing == [source]

    after, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts=artifacts,
        sources={source: payload}, required_sources=[source],
        cutoff_ceiling='2026-09-03T07:30:00+00:00',
    )
    assert missing == []
    assert after[0]['observed_at'] == '2026-09-03T07:15:00+00:00'
    assert cutoff == '2026-09-03T07:15:00+00:00'


def test_jongga_top_level_updated_at_beats_date_label_and_later_file_mtime(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    path = tmp_path / 'jongga_v2_latest.json'
    _write_json(path, {
        'date': '2026-04-14',
        'updated_at': '2026-04-14T15:25:00+09:00',
        'signals': [{'stock_code': '005930', 'score': 88, 'date': '2026-04-14'}],
    })
    later_mtime = datetime(2026, 4, 25, 4, 50, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(alpha_scanner.os.path, 'getmtime', lambda _path: later_mtime)

    artifact = alpha_scanner._load_json_artifact(path.name)
    payload = alpha_scanner._index_jongga(artifact['data'])['005930']
    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={'jongga': artifact},
        sources={path.name: payload}, required_sources=[path.name],
        cutoff_ceiling='2026-04-14T06:30:00+00:00',
    )

    assert artifact['generated_at'] == '2026-04-14T15:25:00+09:00'
    assert missing == []
    assert packets[0]['observed_at'] == '2026-04-14T06:25:00+00:00'
    assert cutoff == '2026-04-14T06:25:00+00:00'


def test_indexed_event_inherits_precise_top_level_generated_at_over_item_date(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    path = tmp_path / 'dart_event_latest.json'
    _write_json(path, {
        'generated_at': '2026-09-03T07:15:00+00:00',
        'entries': [{'symbol': '005930', 'date': '20260903', 'event': 'disclosure'}],
    })
    later_mtime = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(alpha_scanner.os.path, 'getmtime', lambda _path: later_mtime)

    indexed = alpha_scanner._load_indexed_resource_artifact(path.name)

    assert indexed['005930']['generated_at'] == '2026-09-03T07:15:00+00:00'
    assert alpha_scanner._source_available_at(
        path.name, indexed['005930'], file_observed_at='2026-09-04T01:00:00+00:00',
    ).isoformat() == '2026-09-03T07:15:00+00:00'


def test_indexed_event_availability_is_later_of_entry_and_artifact_envelope(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    path = tmp_path / 'dart_event_latest.json'
    _write_json(path, {
        'generated_at': '2026-09-03T07:15:00+00:00',
        'entries': [{
            'symbol': '005930',
            'observed_at': '2026-09-03T06:00:00+00:00',
            'event': 'disclosure',
        }],
    })
    later_mtime = datetime(2026, 9, 4, 1, 0, tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(alpha_scanner.os.path, 'getmtime', lambda _path: later_mtime)
    payload = alpha_scanner._load_indexed_resource_artifact(path.name)['005930']

    before, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={path.name: payload}, required_sources=[path.name],
        cutoff_ceiling='2026-09-03T06:30:00+00:00',
    )
    assert before == [] and cutoff is None and missing == [path.name]

    after, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={path.name: payload}, required_sources=[path.name],
        cutoff_ceiling='2026-09-03T07:30:00+00:00',
    )
    assert missing == []
    assert after[0]['observed_at'] == '2026-09-03T07:15:00+00:00'
    assert cutoff == '2026-09-03T07:15:00+00:00'


def test_authoritative_packet_freshness_uses_historical_cutoff_not_wall_clock():
    source = 'dart_event_latest.json'
    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[], artifacts={},
        sources={source: {
            'symbol': '005930',
            'observed_at': '2020-01-01T06:00:00+00:00',
            'event': 'historical disclosure',
        }},
        required_sources=[source],
        cutoff_ceiling='2020-01-02T06:00:00+00:00',
    )

    assert missing == []
    assert cutoff == '2020-01-01T06:00:00+00:00'
    assert packets[0]['freshness'] == 'fresh'


def test_tradingview_wrapper_uses_nested_signal_fetch_instant():
    available = alpha_scanner._source_available_at(
        'tradingview_mcp',
        {
            'signal': {'symbol': '005930', 'fetched_at': '2026-09-03T15:10:00+09:00'},
            'adjustment': {'applied': True},
        },
    )

    assert available is not None
    assert available.isoformat() == '2026-09-03T06:10:00+00:00'


@pytest.mark.parametrize(
    ('source', 'artifact_key', 'payload'),
    [
        ('kind_blacklist_latest.json', 'kind_blacklist', {
            'symbol': '005930', 'risk_level': 'hard_block',
        }),
        ('credit_balance_latest.json', 'credit_balance', {
            'symbol': '005930', 'credit_ratio_pct': 4.2, 'date': '20260903',
        }),
    ],
)
def test_entry_only_cache_sources_keep_envelope_fetch_availability(
    source, artifact_key, payload,
):
    packets, cutoff, missing = alpha_scanner._authoritative_source_packets(
        symbol='005930', evidence=[],
        artifacts={artifact_key: {
            'fetched_at': '2026-09-03T16:00:00+09:00',
            'entries': {'005930': payload},
        }},
        sources={source: payload}, required_sources=[source],
        cutoff_ceiling='2026-09-03T07:30:00+00:00',
    )

    assert missing == []
    assert packets[0]['observed_at'] == '2026-09-03T07:00:00+00:00'
    assert cutoff == '2026-09-03T07:00:00+00:00'


def _availability_gate_artifacts(*, envelope_time: str) -> dict:
    symbol = '005930'
    baseline = '2026-09-02T07:00:00+00:00'
    price = {
        'symbol': symbol, 'date': '2026-09-02', 'name': 'Samsung',
        'current_price': 100.0, 'change_rate': 3.0,
        'open': 99.0, 'high': 102.0, 'low': 98.0,
        'volume': 100_000_000, 'trading_value': 10_000_000_000.0,
    }
    return {
        'ticker_map': {symbol: {
            'symbol': symbol, 'market': 'KOSPI', 'display_name': 'Samsung',
        }},
        'daily_prices': {symbol: price},
        'price_history': {symbol: [price]},
        'screener': {
            'filename': 'screener_leading_latest.json', 'exists': True,
            'generated_at': baseline, 'mtime': baseline,
            'data': {'results': [{
                'code': symbol, 'name': 'Samsung',
                'score': {'total_enriched': 80},
            }]},
        },
        'vcp': {
            'filename': 'vcp_kr_latest.json', 'exists': True,
            'generated_at': baseline, 'mtime': baseline,
            'data': {'signals': [{
                'symbol': symbol, 'name': 'Samsung',
                'composite': {'composite_score': 85, 'entry_ready': True},
            }]},
        },
        'jongga': {
            'filename': 'jongga_v2_latest.json', 'exists': True,
            'generated_at': envelope_time, 'mtime': envelope_time,
            'data': {'signals': [{
                'stock_code': symbol, 'stock_name': 'Samsung',
                'score': {'total': 15},
            }]},
        },
        'tradingview': {'signals_by_symbol': {}},
        'institutional_trend': {symbol: {
            'scrape_date': '2026-09-03',
            'foreign_net_buy_5d': 1000,
            'institutional_net_buy_5d': 1000,
        }},
        'kind_blacklist': {
            'fetched_at': envelope_time,
            'entries': {symbol: {
                'symbol': symbol, 'risk_level': 'hard_block',
                'categories': ['trading_halt'],
            }},
        },
        'credit_balance': {
            'fetched_at': envelope_time,
            'entries': {symbol: {
                'symbol': symbol, 'date': '20260903', 'credit_ratio_pct': 8.0,
            }},
        },
        'rs_ratings': {'entries': {}},
        'kis_live': {symbol: {
            'fetched_at': envelope_time,
            'quote': {'current_price': 120.0, 'change_pct': 20.0},
        }},
        'dart_events': {symbol: {
            'generated_at': envelope_time, 'risk_level': 'high',
            'flags': ['trading_halt'],
        }},
        'news_theme_social': {symbol: {
            'generated_at': envelope_time, 'sentiment_score': 1.0,
            'theme_strength': 1.0,
        }},
        'candidate_symbols': {symbol},
    }


def test_sources_after_scanner_cutoff_are_excluded_before_scoring_and_gates(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setenv('ENABLE_ALPHA_PHASE_1_GATES', 'true')
    future = '2026-09-03T07:00:00+00:00'
    cutoff = '2026-09-03T05:00:00+00:00'

    candidate = alpha_scanner._build_candidate_pool(
        _availability_gate_artifacts(envelope_time=future),
        generated_at=cutoff, requested_symbols=set(), performance_advisory={},
    )[0]

    excluded = set(candidate['source_availability_excluded'])
    assert {
        'all_institutional_trend_data.csv', 'jongga_v2_latest.json',
        'kind_blacklist_latest.json', 'credit_balance_latest.json',
        'KIS API: live price/investor flow', 'dart_event_latest.json',
        'news_theme_social_latest.json',
    } <= excluded
    assert excluded.isdisjoint(candidate['replay_context']['data_sources'])
    assert candidate['analysis_profile']['capital_flow_confirmation']['status'] == 'missing'
    assert candidate['analysis_profile']['false_signal_gates']['hard_blockers'] == []


def test_future_only_artifact_does_not_improve_candidate_freshness_or_ranking(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    future = '2026-09-04T07:00:00+00:00'
    with_future = _availability_gate_artifacts(envelope_time=future)
    without_future = copy.deepcopy(with_future)
    without_future['jongga'] = {
        'filename': 'jongga_v2_latest.json', 'exists': False,
        'generated_at': None, 'mtime': None, 'data': None,
    }

    absent_candidate = alpha_scanner._build_candidate_pool(
        without_future, generated_at=cutoff,
        requested_symbols=set(), performance_advisory={},
    )[0]
    future_candidate = alpha_scanner._build_candidate_pool(
        with_future, generated_at=cutoff,
        requested_symbols=set(), performance_advisory={},
    )[0]

    for field in ('alpha_score', 'risk_score', 'ranking_score', 'action', 'freshness'):
        assert future_candidate[field] == absent_candidate[field]


def test_future_physical_source_is_missing_at_cutoff_for_freshness(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    future = '2026-09-04T07:00:00+00:00'
    artifacts = {
        'screener': {
            'filename': 'screener_leading_latest.json',
            'exists': True, 'generated_at': future, 'mtime': future,
        },
    }
    missing = alpha_scanner._aggregate_freshness(
        alpha_scanner._source_files(artifacts, cutoff_ceiling=cutoff),
    )
    _write_json(tmp_path / 'screener_leading_latest.json', {
        'generated_at': future, 'results': [],
    })

    future_files = alpha_scanner._source_files(
        artifacts, cutoff_ceiling=cutoff,
    )
    future_status = alpha_scanner._aggregate_freshness(future_files)
    screener = next(
        item for item in future_files
        if item['file'].endswith('screener_leading_latest.json')
    )

    assert screener['exists'] is True
    assert screener['available'] is False
    assert future_status == missing
    assert future_status['status'] == 'missing'


def test_fresh_artifact_without_symbol_is_not_a_staleness_penalty(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    artifacts = _availability_gate_artifacts(
        envelope_time='2026-09-02T07:00:00+00:00',
    )
    artifacts['screener']['data'] = {'results': []}
    artifacts['vcp']['data'] = {'signals': []}
    artifacts['jongga']['data'] = {'signals': []}

    candidate = alpha_scanner._build_candidate_pool(
        artifacts, generated_at=cutoff,
        requested_symbols={'005930'}, performance_advisory={},
    )[0]

    assert candidate['analysis_profile']['base_source_count'] == 1
    assert candidate['analysis_profile']['freshness_penalty'] == 0.0


def test_future_rs_rating_artifact_is_excluded_before_scoring(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    artifacts = _availability_gate_artifacts(
        envelope_time='2026-09-02T07:00:00+00:00',
    )
    without_rs = copy.deepcopy(artifacts)
    without_rs['rs_ratings'] = {
        'generated_at': '2026-09-04T07:00:00+00:00', 'entries': {},
    }
    artifacts['rs_ratings'] = {
        'generated_at': '2026-09-04T07:00:00+00:00',
        'entries': {'005930': {'rs_rating': 99, 'weighted_return': 1.5}},
    }

    baseline = alpha_scanner._build_candidate_pool(
        without_rs, generated_at=cutoff,
        requested_symbols=set(), performance_advisory={},
    )[0]
    candidate = alpha_scanner._build_candidate_pool(
        artifacts, generated_at=cutoff,
        requested_symbols=set(), performance_advisory={},
    )[0]

    assert candidate['alpha_score'] == baseline['alpha_score']
    assert candidate['ranking_score'] == baseline['ranking_score']
    assert 'alpha_rs_ratings.json' in candidate['source_availability_excluded']
    assert 'rs_market_leader' not in candidate['strategy_tags']


def test_future_only_artifact_symbol_does_not_enter_candidate_universe(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    future = '2026-09-04T07:00:00+00:00'
    artifacts = _availability_gate_artifacts(envelope_time=future)
    future_symbol = '999999'
    artifacts['jongga']['data']['signals'] = [{
        'stock_code': future_symbol, 'stock_name': 'Future Only',
        'score': {'total': 15},
    }]
    future_price = {
        'symbol': future_symbol, 'date': '2026-09-02', 'name': 'Future Only',
        'current_price': 100.0, 'change_rate': 2.0,
        'open': 99.0, 'high': 102.0, 'low': 98.0,
        'volume': 100_000_000, 'trading_value': 10_000_000_000.0,
    }
    artifacts['daily_prices'][future_symbol] = future_price
    artifacts['price_history'][future_symbol] = [future_price]
    artifacts['ticker_map'][future_symbol] = {
        'symbol': future_symbol, 'market': 'KOSPI', 'display_name': 'Future Only',
    }
    artifacts['candidate_symbols'].add(future_symbol)

    candidates = alpha_scanner._build_candidate_pool(
        artifacts, generated_at=cutoff,
        requested_symbols=set(), performance_advisory={},
    )

    assert {candidate['symbol'] for candidate in candidates} == {'005930'}


def test_current_scan_accepts_sources_collected_after_start_before_generated_at(
    tmp_path, monkeypatch,
):
    started = datetime(2026, 9, 3, 5, 0, 0, tzinfo=timezone.utc)
    collected = '2026-09-03T05:00:00.500000+00:00'
    completed = datetime(2026, 9, 3, 5, 0, 1, tzinfo=timezone.utc)

    class SequencedDateTime(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            cls.calls += 1
            value = started if cls.calls == 1 else completed
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(alpha_scanner, 'datetime', SequencedDateTime)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(
        alpha_scanner, '_load_artifacts',
        lambda: _availability_gate_artifacts(envelope_time=collected),
    )
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {})
    monkeypatch.setattr(alpha_scanner, 'write_json_atomic', lambda *args, **kwargs: None)
    monkeypatch.setenv('MIROFISH_DEEPSEEK_RERANK_ENABLED', '0')
    monkeypatch.setenv('ENABLE_ALPHA_PHASE_1_GATES', 'true')

    run = alpha_scanner.create_scanner_run({'limit': 1})
    candidate = run['candidates'][0]

    assert run['created_at'] == started.isoformat()
    assert run['generated_at'] == completed.isoformat()
    assert 'kind_blacklist_latest.json' not in candidate['source_availability_excluded']
    assert 'kind_blacklist_latest.json' in candidate['replay_context']['data_sources']
    assert 'kind_blacklist' in (
        candidate['analysis_profile']['false_signal_gates']['hard_blockers']
    )


def test_requested_live_kis_is_collected_before_generated_at_cutoff(
    tmp_path, monkeypatch,
):
    instants = [
        datetime(2026, 9, 3, 5, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 3, 5, 0, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 3, 5, 0, 2, tzinfo=timezone.utc),
    ]

    class SequencedDateTime(datetime):
        calls = 0

        @classmethod
        def now(cls, tz=None):
            index = min(cls.calls, len(instants) - 1)
            cls.calls += 1
            value = instants[index]
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    artifacts = _availability_gate_artifacts(
        envelope_time='2026-09-02T07:00:00+00:00',
    )
    artifacts['kis_live'] = {}
    monkeypatch.setattr(alpha_scanner, 'datetime', SequencedDateTime)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, '_load_artifacts', lambda: artifacts)
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {})
    monkeypatch.setattr(alpha_scanner, 'write_json_atomic', lambda *args, **kwargs: None)
    monkeypatch.setenv('MIROFISH_ALPHA_SCANNER_LIVE_KIS', '1')
    monkeypatch.setenv('MIROFISH_DEEPSEEK_RERANK_ENABLED', '0')

    def fetch_live(_symbol, _mapped):
        return {
            'symbol': '005930',
            'fetched_at': alpha_scanner.datetime.now(timezone.utc).isoformat(),
            'quote': {'current_price': 120.0, 'change_pct': 5.0},
        }

    monkeypatch.setattr(alpha_scanner, '_fetch_kis_live_snapshot_for_symbol', fetch_live)

    run = alpha_scanner.create_scanner_run({'symbols': ['005930'], 'limit': 1})
    candidate = run['candidates'][0]

    assert run['generated_at'] == instants[-1].isoformat()
    assert 'KIS API: live price/investor flow' not in candidate['source_availability_excluded']
    assert 'KIS API: live price/investor flow' in candidate['replay_context']['data_sources']
    assert candidate['analysis_profile']['kis_live_overlay']['applied'] is True


def test_resource_weight_does_not_treat_date_only_as_precise_midnight():
    weight = alpha_scanner._resource_weight({
        'date': '29991231', 'confidence': 1.0,
    })

    assert weight['freshness'] == 'unknown'
    assert weight['observed_at'] is None
    assert weight['score_weight'] == 0.45


def test_resource_weight_uses_scanner_cutoff_instead_of_wall_clock():
    item = {'fetched_at': '2026-09-01T06:00:00+00:00', 'confidence': 1.0}

    replay = alpha_scanner._resource_weight(
        item, max_age_days=7, as_of='2026-09-03T06:00:00+00:00',
    )
    later_replay = alpha_scanner._resource_weight(
        item, max_age_days=7, as_of='2026-10-03T06:00:00+00:00',
    )

    assert replay['age_days'] == 2.0
    assert replay['freshness'] == 'fresh'
    assert replay['score_weight'] == 1.0
    assert later_replay['age_days'] == 32.0
    assert later_replay['freshness'] == 'stale'
    assert later_replay['score_weight'] == 0.2


def test_future_performance_advisory_does_not_change_historical_ranking(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    cutoff = '2026-09-03T05:00:00+00:00'
    artifacts = _availability_gate_artifacts(
        envelope_time='2026-09-02T07:00:00+00:00',
    )
    future_advisory = {
        'available': True,
        'applied_to_scoring': True,
        'source': 'workflow_outcomes',
        'lookahead_safe': True,
        'asof': '2026-09-04T05:00:00+00:00',
        'evaluated_count': 20,
        'hit_rate_recent': 0.72,
        'recommendations': {
            'baseline_hit_rate': 0.50,
            'tag_score_adjust': {'leading_screener': 2.0},
        },
    }

    baseline = alpha_scanner._build_candidate_pool(
        copy.deepcopy(artifacts), generated_at=cutoff,
        requested_symbols={'005930'}, performance_advisory={},
    )[0]
    replay = alpha_scanner._build_candidate_pool(
        copy.deepcopy(artifacts), generated_at=cutoff,
        requested_symbols={'005930'}, performance_advisory=future_advisory,
    )[0]

    assert replay['ranking_score'] == baseline['ranking_score']
    assert replay['alpha_score'] == baseline['alpha_score']
    assert replay['analysis_profile']['performance_memory']['applied'] is False


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
        'asof': _fresh_artifact_timestamp(),
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
        'asof': _fresh_artifact_timestamp(),
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
        'asof': _fresh_artifact_timestamp(),
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


def test_latest_scanner_candidates_skips_empty_run_and_returns_compact_top_five(tmp_path, monkeypatch):
    runs_root = tmp_path / 'runs'
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(runs_root))
    completed_dir = runs_root / 'mfas_20260504000000_aaaaaaaaaaaa'
    running_dir = runs_root / 'mfas_20260505000000_bbbbbbbbbbbb'
    completed_dir.mkdir(parents=True)
    running_dir.mkdir(parents=True)
    _write_json(completed_dir / 'run.json', {
        'id': completed_dir.name,
        'status': 'completed',
        'generated_at': '2026-05-04T00:00:00+00:00',
        'source': 'local_marketflow_artifacts',
        'freshness': {'status': 'stale', 'stale_files': 2},
        'source_files': [
            {'file': 'daily_prices.csv', 'freshness': 'stale', 'as_of': '2026-05-03'},
        ],
        'candidates': [
            {
                'rank': rank,
                'symbol': f'00000{rank}',
                'display_name': f'Candidate {rank}',
                'market': 'KOSPI',
                'alpha_score': 60 + rank,
                'risk_score': 20 + rank,
                'action': 'WATCH',
                'horizon': 'SWING_5_20D',
                'price': {'current_price': rank * 1000, 'unused': 'large payload'},
                'evidence': [{'unused': True}],
            }
            for rank in range(1, 7)
        ],
    })
    _write_json(running_dir / 'run.json', {
        'id': running_dir.name,
        'status': 'running',
        'generated_at': '2026-05-05T00:00:00+00:00',
        'candidates': [],
    })

    payload = alpha_scanner.read_latest_scanner_candidates(limit=5)

    assert payload['run_id'] == completed_dir.name
    assert payload['source'] == 'local_marketflow_artifacts'
    assert payload['freshness'] == {'status': 'stale', 'stale_files': 2}
    assert payload['source_files'][0]['file'] == 'daily_prices.csv'
    assert payload['candidate_count'] == 6
    assert [item['rank'] for item in payload['candidates']] == [1, 2, 3, 4, 5]
    assert payload['candidates'][0]['price'] == 1000
    assert 'evidence' not in payload['candidates'][0]


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


def test_alert_delivery_guard_is_reentrant_when_commit_joins_transaction(tmp_path):
    """The shared transport guard must allow its commit helper to join without deadlock."""
    state_path = str(tmp_path / 'alert_state.json')
    completed = []

    def commit_inside_guard():
        with alpha_scanner.scanner_alert_delivery_guard(state_path, timeout=1):
            completed.append(alpha_scanner.commit_scanner_alert_events({
                'run': {
                    'id': 'guard-zero-event',
                    'generated_at': '2026-08-21T00:00:00+00:00',
                    'candidate_count': 0,
                },
                'events': [],
                'state_path': state_path,
            }))

    worker = threading.Thread(target=commit_inside_guard, daemon=True)
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive(), 'nested commit deadlocked on the canonical delivery guard'
    assert completed[0]['last_run_id'] == 'guard-zero-event'
    persisted = json.loads((tmp_path / 'alert_state.json').read_text(encoding='utf-8'))
    assert persisted['last_new_event_count'] == 0


def test_alert_delivery_guard_timeout_bounds_local_thread_wait(tmp_path):
    """The timeout covers the in-process RLock, not only the cross-process FileLock."""
    state_path = str(tmp_path / 'alert_state.json')
    holder_ready = threading.Event()
    release_holder = threading.Event()
    outcome = []

    def holder():
        with alpha_scanner.scanner_alert_delivery_guard(state_path, timeout=1):
            holder_ready.set()
            release_holder.wait(timeout=2)

    def challenger():
        started = time.monotonic()
        try:
            with alpha_scanner.scanner_alert_delivery_guard(state_path, timeout=0.1):
                outcome.append(('acquired', time.monotonic() - started))
        except Exception as exc:
            outcome.append((type(exc).__name__, time.monotonic() - started))

    owner = threading.Thread(target=holder, daemon=True)
    contender = threading.Thread(target=challenger, daemon=True)
    owner.start()
    assert holder_ready.wait(timeout=1)
    contender.start()
    contender.join(timeout=0.4)
    completed_within_deadline = not contender.is_alive()
    release_holder.set()
    owner.join(timeout=1)
    contender.join(timeout=1)

    assert completed_within_deadline is True
    assert outcome[0][0] == 'Timeout'
    assert outcome[0][1] < 0.35


def test_canonical_alert_commit_preserves_first_writer_event_identity(tmp_path):
    """A later workflow commit cannot overwrite the run that first delivered an event."""
    state_path = str(tmp_path / 'alert_state.json')
    candidate = {
        'symbol': '000001',
        'display_name': 'Alpha One',
        'market': 'KOSPI',
        'action': 'BUY_CANDIDATE',
        'price': {'date': '2026-08-21', 'current_price': 100},
    }
    event = {
        'event_key': '000001:BUY_CANDIDATE:2026-08-21',
        'candidate': candidate,
    }
    first = {
        'run': {'id': 'verified-first', 'generated_at': '2026-08-21T00:00:00+00:00', 'candidate_count': 1},
        'events': [event],
        'state_path': state_path,
    }
    later = {
        'run': {'id': 'workflow-later', 'generated_at': '2026-08-21T00:05:00+00:00', 'candidate_count': 1},
        'events': [event],
        'state_path': state_path,
    }

    alpha_scanner.commit_scanner_alert_events(first)
    summary = alpha_scanner.commit_scanner_alert_events(later)
    persisted = json.loads((tmp_path / 'alert_state.json').read_text(encoding='utf-8'))

    assert persisted['sent_events'][event['event_key']]['run_id'] == 'verified-first'
    assert persisted['last_new_event_count'] == 0
    assert summary['sent_event_count'] == 1
    assert len(persisted['history']) == 1


def test_workflow_delivery_revalidation_fails_closed_on_canonical_overlap(tmp_path):
    """A workflow must re-check canonical BUY keys immediately before transport."""
    state_path = str(tmp_path / 'alert_state.json')
    event_key = '000001:BUY_CANDIDATE:2026-08-21'
    (tmp_path / 'alert_state.json').write_text(json.dumps({
        'version': 2,
        'sent_events': {event_key: {'run_id': 'verified-first'}},
    }), encoding='utf-8')
    candidates = [{
        'symbol': '000001',
        'action': 'BUY_CANDIDATE',
        'price': {'date': '2026-08-21'},
    }]

    check = alpha_scanner.revalidate_scanner_alert_delivery(candidates, state_path=state_path)

    assert check == {
        'ok': False,
        'status': 'event_overlap',
        'event_keys': [event_key],
        'conflicting_event_keys': [event_key],
    }


@pytest.mark.parametrize(
    'state_payload',
    [
        {'version': 'bad', 'sent_events': {}},
        {'version': True, 'sent_events': {}},
        {'version': 0, 'sent_events': {}},
        {'version': 3, 'sent_events': {}},
        {
            'version': 2,
            'sent_events': {},
            'committed_runs': {
                'run-bad-marker': {
                    'event_count': '0',
                    'committed_at': '2026-08-21T00:00:00+00:00',
                },
            },
        },
    ],
)
def test_workflow_delivery_revalidation_rejects_corrupt_canonical_state(tmp_path, state_payload):
    """Transport callers must fail closed before sending when state metadata is corrupt."""
    state_path = tmp_path / 'alert_state.json'
    state_path.write_text(json.dumps(state_payload), encoding='utf-8')

    check = alpha_scanner.revalidate_scanner_alert_delivery([{
        'symbol': '000001',
        'action': 'BUY_CANDIDATE',
        'price': {'date': '2026-08-21'},
    }], state_path=str(state_path))

    assert check == {
        'ok': False,
        'status': 'invalid_alert_state',
        'event_keys': [],
        'conflicting_event_keys': [],
    }


def test_workflow_delivery_revalidation_requires_at_least_one_buy_event_key(tmp_path):
    """WATCH-only analysis has no canonical claim identity and cannot be transported."""
    state_path = tmp_path / 'alert_state.json'
    state_path.write_text(json.dumps({'version': 2, 'sent_events': {}}), encoding='utf-8')

    check = alpha_scanner.revalidate_scanner_alert_delivery([{
        'symbol': '000001',
        'action': 'WATCH',
        'price': {'date': '2026-08-21'},
    }], state_path=str(state_path))

    assert check == {
        'ok': False,
        'status': 'missing_event_candidates',
        'event_keys': [],
        'conflicting_event_keys': [],
    }


def test_scanner_alert_state_keeps_pending_latest_run_out_of_feed(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = tmp_path / 'alert_state.json'
    sent_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_json(state_path, {
        'version': 2,
        'last_checked_at': sent_at,
        'last_sent_at': sent_at,
        'last_candidate_count': 1,
        'sent_events': {
            '999999:BUY_CANDIDATE:2026-05-01': {
                'sent_at': sent_at,
                'run_id': 'old_run',
                'rank': 1,
                'symbol': '999999',
                'display_name': 'Old Event',
                'market': 'KOSPI',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 71,
                'risk_score': 21,
                'price': {'current_price': 1000, 'change_rate': 1.0, 'date': '2026-05-01'},
            },
        },
    })

    latest_run = alpha_scanner.create_scanner_run({'limit': 5})
    state = alpha_scanner.read_scanner_alert_state(str(state_path))

    assert state['recent_sent_events'][0]['symbol'] == '999999'
    assert state['latest_run_id'] == latest_run['id']
    assert state['latest_candidate_count'] == latest_run['candidate_count']
    assert state['latest_candidate_events'][0]['symbol'] == '000001'
    assert state['latest_candidate_events'][0]['source'] == 'latest_run'
    assert state['latest_new_event_count'] == 1
    assert state['latest_new_events'][0]['symbol'] == '000001'
    assert state['latest_new_events'][0]['source'] == 'latest_run_new'
    assert state['latest_new_events'][0]['pending_commit'] is True
    assert state['feed_events'][0]['symbol'] == '999999'
    assert state['feed_events'][0]['run_id'] == 'old_run'


def test_scanner_alert_state_keeps_recent_cache_without_recreating_sent_latest_run(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = tmp_path / 'alert_state.json'
    latest_run = alpha_scanner.create_scanner_run({'limit': 5})
    # Sent a couple of hours ago — still within SCANNER_FEED_MAX_AGE_HOURS, so the
    # feed should keep showing it even though this run found no brand-new events.
    sent_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    _write_json(state_path, {
        'version': 2,
        'last_checked_at': sent_at,
        'last_sent_at': sent_at,
        'last_candidate_count': 1,
        'sent_events': {
            '000001:BUY_CANDIDATE:2026-05-03': {
                'sent_at': sent_at,
                'run_id': latest_run['id'],
                'rank': 1,
                'symbol': '000001',
                'display_name': 'Alpha One',
                'market': 'KOSPI',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 80,
                'risk_score': 20,
                'price': {'current_price': 108, 'change_rate': 8.0, 'date': '2026-05-03'},
            },
        },
    })

    state = alpha_scanner.read_scanner_alert_state(str(state_path))

    assert state['latest_run_id'] == latest_run['id']
    assert state['latest_new_event_count'] == 0
    assert state['latest_new_events'] == []
    assert state['recent_sent_events'][0]['symbol'] == '000001'
    assert state['feed_events'][0]['symbol'] == '000001'
    assert state['feed_events'][0].get('pending_commit') is None


def test_scanner_alert_state_feed_excludes_recent_watch_events(tmp_path, monkeypatch):
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = tmp_path / 'alert_state.json'
    buy_sent_at = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    watch_sent_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    _write_json(state_path, {
        'version': 2,
        'last_checked_at': watch_sent_at,
        'last_sent_at': watch_sent_at,
        'last_candidate_count': 2,
        'sent_events': {
            '000001:BUY_CANDIDATE:2026-05-03': {
                'sent_at': buy_sent_at,
                'run_id': 'mfas_buy_run',
                'rank': 1,
                'symbol': '000001',
                'display_name': 'Alpha One',
                'market': 'KOSPI',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 80,
                'risk_score': 20,
                'price': {'current_price': 108, 'change_rate': 8.0, 'date': '2026-05-03'},
            },
            '000002:WATCH:2026-05-03': {
                'sent_at': watch_sent_at,
                'run_id': 'mfas_watch_run',
                'rank': 2,
                'symbol': '000002',
                'display_name': 'Watch Two',
                'market': 'KOSPI',
                'action': 'WATCH',
                'alpha_score': 74,
                'risk_score': 55,
                'price': {'current_price': 205, 'change_rate': 4.0, 'date': '2026-05-03'},
            },
        },
    })

    state = alpha_scanner.read_scanner_alert_state(str(state_path))

    assert state['recent_sent_events'][0]['symbol'] == '000002'
    assert [event['symbol'] for event in state['feed_events']] == ['000001']


def test_scanner_alert_state_excludes_stale_events_from_feed(tmp_path, monkeypatch):
    """Regression test: a sent event past SCANNER_FEED_MAX_AGE_HOURS must not
    linger in feed_events forever just because it's still within the top-20
    count-based slice. recent_sent_events (the raw audit trail) stays unfiltered.
    """
    _seed_artifacts(tmp_path)
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    state_path = tmp_path / 'alert_state.json'
    latest_run = alpha_scanner.create_scanner_run({'limit': 5})
    stale_sent_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    _write_json(state_path, {
        'version': 2,
        'last_checked_at': stale_sent_at,
        'last_sent_at': stale_sent_at,
        'last_candidate_count': 1,
        'sent_events': {
            # Key must match the scanner's real _candidate_event_key format
            # (symbol:action:price_date) so this run's candidate for 000001 is
            # correctly recognized as "already sent" (latest_new_event_count stays
            # 0) — only the recency of the sent_at timestamp is under test here.
            '000001:BUY_CANDIDATE:2026-05-03': {
                'sent_at': stale_sent_at,
                'run_id': 'mfas_stale_run',
                'rank': 1,
                'symbol': '000001',
                'display_name': 'Alpha One',
                'market': 'KOSPI',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 80,
                'risk_score': 20,
                'price': {'current_price': 108, 'change_rate': 8.0, 'date': '2026-05-03'},
            },
        },
    })

    state = alpha_scanner.read_scanner_alert_state(str(state_path))

    assert state['latest_run_id'] == latest_run['id']
    assert state['latest_new_event_count'] == 0
    # Raw audit trail still reports the stale event...
    assert state['recent_sent_events'][0]['symbol'] == '000001'
    # ...but the dashboard feed must not present it as if it were a fresh detection.
    assert state['feed_events'] == []


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


def test_admin_alert_route_holds_canonical_guard_through_transport_and_commit(monkeypatch):
    """The manual admin sender must not release the shared guard between selection and commit."""
    active = {'value': False, 'entries': 0}

    @contextmanager
    def guard(*args, **kwargs):
        active['entries'] += 1
        active['value'] = True
        try:
            yield 'canonical-state.json'
        finally:
            active['value'] = False

    result = {
        'run': {'id': 'admin-guard-run', 'candidate_count': 1},
        'events': [{'event_key': '000001:BUY_CANDIDATE:2026-08-21'}],
        'message': '<b>guarded</b>',
        'state': {},
        'alert_blocked': False,
        'blocked_reason': None,
    }

    def scan(*args, **kwargs):
        assert active['value'] is True
        return result

    def commit(payload):
        assert active['value'] is True
        return {'committed': True}

    def send(message, **kwargs):
        assert active['value'] is True
        return True

    monkeypatch.setattr(alpha_scanner, 'scanner_alert_delivery_guard', guard)
    monkeypatch.setattr(admin_mirofish_routes.mirofish, 'run_scanner_alert_check', scan)
    monkeypatch.setattr(admin_mirofish_routes.mirofish, 'commit_scanner_alert_events', commit)
    from app.utils import scheduler
    monkeypatch.setattr(scheduler, '_send_telegram_long', send)
    app = Flask(__name__)

    with app.test_request_context(
        '/api/admin/mirofish/scanner/alerts/check',
        method='POST',
        json={'send_telegram': True},
    ):
        response = admin_mirofish_routes.check_scanner_alerts.__wrapped__()

    assert response.get_json()['status'] == 'sent'
    assert active == {'value': False, 'entries': 1}


@pytest.mark.parametrize(
    ('request_payload', 'expected_status'),
    [
        ({'dry_run': True, 'send_telegram': True}, 'dry_run'),
        ({'dry_run': False, 'send_telegram': False}, 'preview'),
    ],
)
def test_admin_alert_preview_and_dry_run_never_claim_canonical_state(
    monkeypatch,
    request_payload,
    expected_status,
):
    """Read-only admin checks cannot occupy delivered event identities."""
    result = {
        'run': {'id': 'admin-read-only-run', 'candidate_count': 1},
        'events': [{'event_key': '000001:BUY_CANDIDATE:2026-08-21'}],
        'message': '<b>preview</b>',
        'state': {'sent_event_count': 0},
        'alert_blocked': False,
        'blocked_reason': None,
    }
    monkeypatch.setattr(
        alpha_scanner,
        'scanner_alert_delivery_guard',
        lambda *args, **kwargs: nullcontext('canonical-state.json'),
    )
    monkeypatch.setattr(admin_mirofish_routes.mirofish, 'run_scanner_alert_check', lambda *args, **kwargs: result)
    monkeypatch.setattr(
        admin_mirofish_routes.mirofish,
        'commit_scanner_alert_events',
        lambda *_args, **_kwargs: pytest.fail('read-only route committed canonical state'),
    )
    from app.utils import scheduler
    monkeypatch.setattr(
        scheduler,
        '_send_telegram_long',
        lambda *_args, **_kwargs: pytest.fail('read-only route sent Telegram'),
    )
    monkeypatch.setattr(admin_mirofish_routes, '_telegram_config_status', lambda: {'configured': False})
    app = Flask(__name__)

    with app.test_request_context(
        '/api/admin/mirofish/scanner/alerts/check',
        method='POST',
        json=request_payload,
    ):
        response = admin_mirofish_routes.check_scanner_alerts.__wrapped__()

    payload = response.get_json()
    assert payload['status'] == expected_status
    assert payload['telegram_sent'] is False
    assert payload['state_committed'] is False


def _minimal_corrupt_state_alert_run() -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        'id': 'mfas_corrupt_canonical',
        'status': 'completed',
        'generated_at': generated_at,
        'candidate_count': 1,
        'candidates': [{
            'rank': 1,
            'symbol': '000001',
            'display_name': 'Alpha One',
            'market': 'KOSPI',
            'action': 'BUY_CANDIDATE',
            'alpha_score': 82,
            'risk_score': 24,
            'price': {'date': generated_at[:10], 'current_price': 100},
        }],
        'freshness': {'status': 'fresh'},
    }


def test_realtime_monitor_fails_before_transport_on_malformed_canonical_state(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    state_path = tmp_path / 'admin_mirofish' / 'alpha_scanner_alert_state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{broken', encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'create_scanner_run', lambda payload: _minimal_corrupt_state_alert_run())

    with pytest.raises(ValueError, match='canonical alert state'):
        alpha_scanner.run_scanner_realtime_monitor_check(
            {},
            force=True,
            send_fn=pytest.fail,
        )


def test_realtime_monitor_rejects_transport_when_canonical_commit_is_disabled(monkeypatch):
    """An exported caller cannot send successfully while leaving the event resendable."""
    monkeypatch.setattr(alpha_scanner, 'create_scanner_run', pytest.fail)

    with pytest.raises(ValueError, match='commit_monitor_state'):
        alpha_scanner.run_scanner_realtime_monitor_check(
            {},
            force=True,
            commit_monitor_state=False,
            send_fn=pytest.fail,
        )


def test_alert_state_io_uses_guard_canonical_path_not_caller_alias(tmp_path, monkeypatch):
    """Read/write/result paths must follow the guard's realpath to preserve one namespace."""
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    canonical_path = tmp_path / 'admin_mirofish' / 'alpha_scanner_alert_state.json'
    alias_path = tmp_path / 'alert-state-alias.json'
    writes = []

    @contextmanager
    def guard(*args, **kwargs):
        yield str(canonical_path)

    monkeypatch.setattr(alpha_scanner, 'scanner_alert_delivery_guard', guard)
    monkeypatch.setattr(alpha_scanner, 'create_scanner_run', lambda payload: _minimal_corrupt_state_alert_run())
    monkeypatch.setattr(
        alpha_scanner,
        'write_json_atomic',
        lambda path, payload, **kwargs: writes.append((path, payload)),
    )
    from app.services.mirofish import scanner_deepverify
    monkeypatch.setattr(scanner_deepverify, 'enqueue_new_events', lambda *args, **kwargs: None)

    selected = alpha_scanner.run_scanner_alert_check(
        {},
        state_path=str(alias_path),
        block_on_stale=False,
    )

    assert selected['state_path'] == str(canonical_path)
    assert writes[0][0] == str(canonical_path)

    writes.clear()
    committed = alpha_scanner.commit_scanner_alert_events({
        **selected,
        'state_path': str(alias_path),
    })

    assert committed['state_path'] == str(canonical_path)
    assert writes[0][0] == str(canonical_path)


def test_admin_alert_sender_fails_before_transport_on_invalid_canonical_version(tmp_path, monkeypatch):
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(tmp_path))
    state_path = tmp_path / 'admin_mirofish' / 'alpha_scanner_alert_state.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({'version': 'bad', 'sent_events': {}}), encoding='utf-8')
    monkeypatch.setattr(alpha_scanner, 'create_scanner_run', lambda payload: _minimal_corrupt_state_alert_run())
    from app.utils import scheduler
    monkeypatch.setattr(scheduler, '_send_telegram_long', pytest.fail)
    app = Flask(__name__)

    with app.test_request_context(
        '/api/admin/mirofish/scanner/alerts/check',
        method='POST',
        json={'send_telegram': True},
    ):
        response, status_code = admin_mirofish_routes.check_scanner_alerts.__wrapped__()

    assert status_code == 400
    assert 'canonical alert state' in response.get_json()['error']


@pytest.mark.parametrize('telegram_enabled', [False, True])
def test_flask_alpha_monitor_worker_requires_explicit_telegram_opt_in(monkeypatch, telegram_enabled):
    """The app auto-start worker may scan by default but only an opt-in wires transport."""
    captured = {}
    sent_messages = []

    class StopWorker(Exception):
        pass

    class CapturingThread:
        def __init__(self, *, target, daemon, name):
            captured.update({'target': target, 'daemon': daemon, 'name': name})

        def start(self):
            captured['started'] = True

    class FakeApp:
        @staticmethod
        def app_context():
            return nullcontext()

    sleep_calls = {'count': 0}

    def bounded_sleep(_seconds):
        sleep_calls['count'] += 1
        if sleep_calls['count'] > 1:
            raise StopWorker()

    def monitor(*args, send_fn=None, **kwargs):
        captured['monitor_called'] = True
        if telegram_enabled:
            assert send_fn is not None
            assert send_fn('<b>alert</b>') is True
            status = 'sent'
        else:
            assert send_fn is None
            status = 'pending_send'
        captured['monitor_completed'] = True
        return {
            'status': status,
            'new_event_count': 1,
            'run': {'id': 'worker-run'},
        }

    monkeypatch.setenv('ALPHA_SCANNER_ENABLED', 'true')
    monkeypatch.setenv('ALPHA_SCANNER_REALTIME_ENABLED', 'true')
    monkeypatch.setenv('ALPHA_SCANNER_TELEGRAM_ENABLED', 'true' if telegram_enabled else 'false')
    monkeypatch.setattr(threading, 'Thread', CapturingThread)
    monkeypatch.setattr(time, 'sleep', bounded_sleep)
    monkeypatch.setattr(alpha_scanner, 'run_scanner_realtime_monitor_check', monitor)
    from app.services.mirofish import auto_runner
    monkeypatch.setattr(auto_runner, 'start_worker', lambda: False)
    from app.utils import scheduler as app_scheduler
    monkeypatch.setattr(
        app_scheduler,
        '_send_telegram_long',
        lambda message, channel=False: sent_messages.append((message, channel)) or True,
    )

    marketflow_app._start_alpha_scanner_monitor_worker(FakeApp())
    assert captured['started'] is True
    with pytest.raises(StopWorker):
        captured['target']()

    assert captured['monitor_called'] is True
    assert captured['monitor_completed'] is True
    assert sent_messages == ([('<b>alert</b>', False)] if telegram_enabled else [])


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

    assert '/api/admin/mirofish/alpha-dashboard' in rules
    assert '/api/admin/mirofish/scanner/runs' in rules
    assert '/api/admin/mirofish/scanner/status' in rules
    assert '/api/admin/mirofish/scanner/diagnostics' in rules
    assert '/api/admin/mirofish/scanner/alerts/check' in rules
    assert '/api/admin/mirofish/scanner/alerts/state' in rules
    assert '/api/admin/mirofish/scanner/monitor/check' in rules
    assert '/api/admin/mirofish/scanner/monitor/status' in rules
    assert '/api/admin/mirofish/scanner/runs/latest' in rules
    assert '/api/admin/mirofish/scanner/candidates/latest' in rules
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
