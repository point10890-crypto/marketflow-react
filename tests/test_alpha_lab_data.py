import csv
import hashlib
import json

import pytest

from app.services.mirofish.alpha_lab.data import load_inputs


def inputs(tmp_path, rows=None, quality=True):
    prices = tmp_path / 'prices.csv'
    rows = rows or [dict(symbol='005930', date='2026-10-02', open=100, high=110,
                        low=90, close=105, volume=100, captured_at='2026-10-03T01:00:00+00:00')]
    with prices.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(prices_sha256=hashlib.sha256(prices.read_bytes()).hexdigest(),
        source='naver_sise_json_public', price_basis='provider_reported_unverified',
        analysis_ready=False, corporate_action_adjustment_verified=False,
        historical_vintage_verified=False, point_in_time_universe_verified=False)), encoding='utf-8')
    scope = tmp_path / 'scope.json'
    report = dict(as_of='2026-10-01', ranking=dict(ranked=[
        dict(symbol='005930', name='삼성전자', market='KOSPI', rank=1)]))
    if quality:
        report['quality'] = dict(results=[dict(symbol='005930', quality_pass=True)])
    scope.write_text(json.dumps(report), encoding='utf-8')
    return prices, manifest, scope


def test_actual_scope_preserves_code_and_unknown_history(tmp_path):
    result = load_inputs(*inputs(tmp_path), as_of='2026-10-04')
    assert result['status'] == 'ready'
    assert list(result['prices_by_symbol']) == ['005930']
    assert result['names']['005930'] == '삼성전자'
    assert result['provenance']['analysis_ready'] is False
    assert result['provenance']['point_in_time_universe_verified'] is False
    assert result['provenance']['current_cohort_bias'] is True
    assert result['universe']['quality_count'] == 1
    assert result['latest_session'] == '2026-10-02'


def test_manifest_mismatch_fails_without_data(tmp_path):
    prices, manifest, scope = inputs(tmp_path)
    prices.write_text(prices.read_text() + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='hash'):
        load_inputs(prices, manifest, scope, as_of='2026-10-04')


def test_missing_quality_never_falls_back_to_all_prices(tmp_path):
    with pytest.raises(ValueError, match='quality'):
        load_inputs(*inputs(tmp_path, quality=False), as_of='2026-10-04')


def test_duplicate_identity_is_rejected(tmp_path):
    row = dict(symbol='005930', date='2026-10-02', open=100, high=110, low=90, close=105, volume=1)
    with pytest.raises(ValueError, match='duplicate'):
        load_inputs(*inputs(tmp_path, [row, row]), as_of='2026-10-04')


def test_invalid_bar_excluded_but_positive_zero_volume_retained(tmp_path):
    rows = [dict(symbol='005930', date='2026-10-01', open=100, high=90, low=80, close=105, volume=5),
            dict(symbol='005930', date='2026-10-02', open=100, high=110, low=90, close=105, volume=0)]
    result = load_inputs(*inputs(tmp_path, rows), as_of='2026-10-04')
    assert len(result['prices_by_symbol']['005930']) == 1
    assert result['prices_by_symbol']['005930'][0]['volume'] == 0
    assert result['diagnostics']['excluded_rows']['invalid_ohlcv'] == 1


def test_stale_scope_is_held_and_future_prices_are_withheld(tmp_path):
    result = load_inputs(*inputs(tmp_path), as_of='2026-10-12')
    assert result['status'] == 'held' and 'stale_scope' in result['reasons']
    with pytest.raises(ValueError, match='future'):
        load_inputs(*inputs(tmp_path), as_of='2026-09-30')


def test_symbols_outside_quality_scope_are_not_loaded(tmp_path):
    rows = [dict(symbol='005930', date='2026-10-02', open=100, high=110, low=90, close=105, volume=5),
            dict(symbol='000660', date='2026-10-02', open=100, high=110, low=90, close=105, volume=5)]
    result = load_inputs(*inputs(tmp_path, rows), as_of='2026-10-04')
    assert set(result['prices_by_symbol']) == {'005930'}


def test_data_fingerprint_changes_with_scope_not_execution_clock(tmp_path):
    args = inputs(tmp_path)
    first = load_inputs(*args, as_of='2026-10-04')
    second = load_inputs(*args, as_of='2026-10-05')
    assert first['input_fingerprint'] == second['input_fingerprint']
    scope = json.loads(args[2].read_text())
    scope['as_of'] = '2026-10-02'
    args[2].write_text(json.dumps(scope), encoding='utf-8')
    assert load_inputs(*args, as_of='2026-10-04')['input_fingerprint'] != first['input_fingerprint']


def test_future_capture_cannot_claim_ready_source(tmp_path):
    rows = [dict(symbol='005930', date='2026-10-02', open=100, high=110, low=90, close=105,
                 volume=5, captured_at='2099-10-03T01:00:00+00:00')]
    result = load_inputs(*inputs(tmp_path, rows), as_of='2026-10-04')
    assert result['status'] == 'held'
    assert 'future_source_capture' in result['reasons']


def test_explicit_invalid_source_flag_is_excluded_even_with_numeric_ohlc(tmp_path):
    rows = [dict(symbol='005930', date='2026-10-01', open=100, high=110, low=90, close=105,
                 volume=5, quality_flags='invalid_ohlcv'),
            dict(symbol='005930', date='2026-10-02', open=100, high=110, low=90, close=105,
                 volume=5, quality_flags='provider_basis_unverified')]
    result = load_inputs(*inputs(tmp_path, rows), as_of='2026-10-04')
    assert [row['date'] for row in result['prices_by_symbol']['005930']] == ['2026-10-02']
    assert result['diagnostics']['excluded_rows']['fatal_source_flag'] == 1
