# -*- coding: utf-8 -*-
"""Detection lab v3.1 reproducibility and fail-closed harness contracts."""
import csv
import json

from scripts import detection_lab_run as runner


def _write_prices(path):
    fields = ['ticker', 'date', 'open', 'high', 'low', 'current_price', 'update_time']
    with path.open('w', encoding='utf-8', newline='') as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows([
            {'ticker': 'AAA', 'date': '2026-06-01', 'open': 100, 'high': 101,
             'low': 99, 'current_price': 100, 'update_time': '2026-06-01 15:00:00'},
            {'ticker': 'AAA', 'date': '2026-06-01', 'open': 101, 'high': 103,
             'low': 100, 'current_price': 102, 'update_time': '2026-06-01 15:10:00'},
            {'ticker': 'AAA', 'date': '2026-06-02', 'open': 103, 'high': 105,
             'low': 102, 'current_price': 104, 'update_time': '2026-06-02 15:10:00'},
            # Later malformed OHLC must not replace the latest valid candidate.
            {'ticker': 'AAA', 'date': '2026-06-02', 'open': 110, 'high': 105,
             'low': 102, 'current_price': 104, 'update_time': '2026-06-02 15:20:00'},
            # Non-finite OHLC is rejected explicitly.
            {'ticker': 'AAA', 'date': '2026-06-03', 'open': 104, 'high': 'NaN',
             'low': 103, 'current_price': 104, 'update_time': '2026-06-03 15:10:00'},
        ])


def test_load_series_deduplicates_ohlc_and_exposes_stats(tmp_path):
    price_path = tmp_path / 'daily_prices.csv'
    _write_prices(price_path)

    series, quality = runner.load_series({'AAA'}, path=price_path, return_quality=True)

    assert len(series['AAA']) == 2
    assert series['AAA'][0]['open'] == 101.0
    assert series['AAA'][0]['close'] == 102.0
    assert quality['duplicate_keys'] == 1
    assert quality['conflicting_duplicate_keys'] == 1
    assert quality['invalid_ohlc_rows'] == 1
    assert quality['invalid_numeric_price_rows'] == 1
    assert quality['max_data_date'] == '2026-06-02'


def test_manifest_contains_hashes_ruleset_coverage_and_fails_closed(tmp_path, monkeypatch):
    price_path = tmp_path / 'daily_prices.csv'
    regime_path = tmp_path / 'regime_timeline.json'
    _write_prices(price_path)
    regime_path.write_text(json.dumps({
        'schema_version': 'mirofish.regime_timeline.v2',
        'method_version': 'test-regime',
        'data_quality': {'duplicate_keys': 0},
        'by_date': {'2026-06-01': {'regime': 'RISK_ON', 'breadth': 0.7}},
    }), encoding='utf-8')
    detections = [
        {'date': '2026-06-01', 'symbol': 'AAA'},
        {'date': '2026-06-20', 'symbol': 'AAA'},
    ]
    series, quality = runner.load_series({'AAA'}, path=price_path, return_quality=True)
    monkeypatch.setattr(runner, '_git_metadata', lambda: {
        'revision': 'abc123', 'tracked_worktree_dirty': False,
    })

    manifest = runner.build_manifest(
        detections=detections,
        symbols={'AAA'},
        series=series,
        phases={'2026-06-01': 'leader_market'},
        price_quality=quality,
        daily_prices_path=price_path,
        regime_timeline_path=regime_path,
    )

    assert manifest['method_version'] == runner.dl.DETECTION_LAB_METHOD_VERSION
    assert len(manifest['inputs']['daily_prices']['sha256']) == 64
    assert len(manifest['inputs']['regime_timeline']['sha256']) == 64
    assert len(manifest['inputs']['detections']['sha256']) == 64
    assert manifest['max_data_date'] == '2026-06-02'
    assert manifest['duplicate_stats']['duplicate_keys'] == 1
    assert manifest['coverage']['phase']['coverage_ratio'] == 0.5
    assert manifest['validation']['status'] == 'failed'
    assert manifest['validation']['eligible_for_policy_decision'] is False
    assert 'phase_coverage' in manifest['validation']['failed_checks']
    assert manifest['live_phase_gate_blocked'] == ['downtrend', 'rebound_early']
    assert manifest['rulesets'][1]['regime_gate'] is True


def test_validation_passes_only_when_both_coverages_meet_threshold():
    coverage = {
        'phase': {'coverage_ratio': 0.95},
        'price_detections_with_future_bar': {'coverage_ratio': 0.99},
    }
    result = runner.validate_coverage(coverage)
    assert result['status'] == 'passed'
    assert result['eligible_for_policy_decision'] is True
