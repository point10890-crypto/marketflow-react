"""Deterministic chart distributions must use completed, knowable sessions."""
import csv
import importlib
import json
import math
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest


def engine():
    try:
        return importlib.import_module('app.services.mirofish.chart_analogue')
    except ModuleNotFoundError:
        pytest.fail('Historical analogue engine is not implemented')


def sessions(count=650):
    current = date(2023, 1, 2)
    result = []
    while len(result) < count:
        if current.weekday() < 5:
            result.append(current)
        current += timedelta(days=1)
    return result


def prices(path, count=650, symbols=8, overrides=None):
    days = sessions(count)
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['ticker', 'date', 'name', 'current_price', 'update_time'])
        writer.writeheader()
        for number in range(symbols):
            symbol = f'{number + 1:06d}'
            for index, day in enumerate(days):
                row = {'ticker': symbol, 'date': day.isoformat(), 'name': f'Stock {number + 1}',
                       'current_price': 100 * (1.001 ** index),
                       'update_time': f'{day.isoformat()} 16:00:00'}
                if overrides:
                    row.update(overrides(symbol, index, row) or {})
                writer.writerow(row)
    return days


def install(tmp_path, monkeypatch, **kwargs):
    module = engine()
    source = tmp_path / 'prices.csv'
    days = prices(source, **kwargs)
    root = tmp_path / 'index'
    monkeypatch.setattr(module, 'INDEX_ROOT', root)
    summary = module.build_index(source, root)
    return module, source, days, summary


def cutoff(day):
    return f'{day.isoformat()}T08:00:00Z'


def test_missing_index_is_cheap_and_never_reads_prices(tmp_path, monkeypatch):
    module = engine()
    monkeypatch.setattr(module, 'INDEX_ROOT', tmp_path / 'missing')
    assert module.status()['status'] == 'missing_index'
    result = module.predict('000001')
    assert result['status'] == 'missing_index'
    assert result['mode'] == 'shadow'
    assert result['horizons'] == []
    assert not (tmp_path / 'missing').exists()


def test_empirical_returns_are_actual_sessions_and_neighbours_do_not_overlap(tmp_path, monkeypatch):
    module, source, days, summary = install(tmp_path, monkeypatch)
    result = module.predict('000001', as_of=cutoff(days[-1]))
    assert result['status'] == 'ready'
    assert result['target'] == 'Stock 1'
    assert result['sample_count'] >= 5
    assert len(result['history']) == 252
    assert len(result['fan']) == 41
    for horizon, expected in [(5, 0.501001), (20, 2.019114), (40, 4.078997)]:
        value = next(row for row in result['horizons'] if row['sessions'] == horizon)
        assert value['median_return_pct'] == pytest.approx(expected, abs=0.000002)
        assert value['up_frequency_pct'] == 100
        assert value['p10_return_pct'] <= value['median_return_pct'] <= value['p90_return_pct']
    neighbours = result['neighbors']
    for left in neighbours:
        assert left['outcome_end_date'] <= days[-1].isoformat()
        assert datetime.fromisoformat(left['captured_at'].replace('Z', '+00:00')) <= datetime.fromisoformat(cutoff(days[-1]).replace('Z', '+00:00'))
        for right in neighbours:
            if left is not right and left['symbol'] == right['symbol']:
                assert left['outcome_end_date'] < right['start_date'] or right['outcome_end_date'] < left['start_date']
    before = {item.name: item.stat().st_mtime_ns for item in (tmp_path / 'index').iterdir()}
    source.unlink()  # An API request must never need the 189 MB source CSV.
    assert module.predict('000001', as_of=cutoff(days[-1])) == result
    assert before == {item.name: item.stat().st_mtime_ns for item in (tmp_path / 'index').iterdir()}
    with np.load(tmp_path / 'index' / 'chart_analogue.npz', allow_pickle=False) as archive:
        assert all(archive[name].dtype.kind != 'O' for name in archive.files)


def test_capture_cutoff_rejects_future_known_prices_even_with_early_session_dates(tmp_path, monkeypatch):
    def late(symbol, index, row):
        if symbol != '000001':
            return {'update_time': '2030-01-01 16:00:00'}
    module, _, days, _ = install(tmp_path, monkeypatch, overrides=late)
    result = module.predict('000001', as_of=cutoff(days[-1]))
    assert result['status'] == 'insufficient_analogues'
    assert result['sample_count'] < 5
    assert result['horizons'] == []


def test_intraday_unknown_capture_and_duplicate_sessions_are_not_forecast_inputs(tmp_path, monkeypatch):
    module, source, days, _ = install(tmp_path, monkeypatch)
    with source.open('a', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['000001', days[-1].isoformat(), 'Stock 1', 9999, f'{days[-1]} 18:00:00'])
        next_day = sessions(651)[-1]
        writer.writerow(['000001', next_day.isoformat(), 'Stock 1', 9999, f'{next_day} 14:52:23'])
        writer.writerow(['000001', (next_day + timedelta(days=1)).isoformat(), 'Stock 1', 9999, ''])
    built = module.build_index(source, tmp_path / 'index')
    result = module.predict('000001', as_of=cutoff(days[-1]))
    assert result['status'] == 'ready'
    assert result['history'][-1]['close'] != 9999
    assert len({row['date'] for row in result['history']}) == 252
    rejected = built['diagnostics']['rejected']
    assert rejected['intraday'] == 1
    assert rejected['unknown_capture'] == 1
    assert rejected['duplicate_sessions'] == 1
    assert result['source']['captured_at'].endswith('Z')


@pytest.mark.parametrize('bad', ['nan', '0', '-1'])
def test_invalid_price_inside_target_window_blocks_forecast(tmp_path, monkeypatch, bad):
    module, _, days, built = install(tmp_path, monkeypatch, overrides=lambda symbol, index, row: {'current_price': bad} if symbol == '000001' and index == 600 else {})
    result = module.predict('000001', as_of=cutoff(days[-1]))
    assert result['status'] == 'insufficient_history'
    assert result['horizons'] == []
    assert built['diagnostics']['rejected']['bad_price'] == 1


def test_raw_price_discontinuity_blocks_uncertain_target_window(tmp_path, monkeypatch):
    module, _, days, _ = install(tmp_path, monkeypatch, overrides=lambda symbol, index, row: {'current_price': float(row['current_price']) * 2} if symbol == '000001' and index >= 600 else {})
    assert module.predict('000001', as_of=cutoff(days[-1]))['status'] == 'insufficient_history'


def test_stale_source_has_visible_history_but_no_actionable_forecast(tmp_path, monkeypatch):
    module, _, days, _ = install(tmp_path, monkeypatch)
    late = days[-1] + timedelta(days=8)
    result = module.predict('000001', as_of=cutoff(late))
    assert result['status'] == 'stale_data'
    assert result['history']
    assert result['horizons'] == [] and result['fan'] == []
    assert result['source']['freshness_days'] == 8


def test_parameter_bounds_and_naive_cutoff_are_rejected(tmp_path, monkeypatch):
    module = engine()
    for kwargs in ({'symbol': '../bad'}, {'symbol': '000001', 'lookback': 999999}, {'symbol': '000001', 'k': 10000}, {'symbol': '000001', 'horizons': [999999]}, {'symbol': '000001', 'as_of': '2025-01-01'}):
        with pytest.raises(ValueError):
            module.predict(**kwargs)


def test_corrupt_index_is_visible_as_unavailable(tmp_path, monkeypatch):
    module = engine()
    monkeypatch.setattr(module, 'INDEX_ROOT', tmp_path)
    (tmp_path / 'chart_analogue.npz').write_bytes(b'broken archive')
    assert module.status()['status'] == 'unavailable'
    assert module.predict('000001')['status'] == 'unavailable'


def test_index_with_incomplete_metadata_fails_closed(tmp_path, monkeypatch):
    module = engine()
    monkeypatch.setattr(module, 'INDEX_ROOT', tmp_path)
    np.savez(tmp_path / 'chart_analogue.npz', metadata=np.array(json.dumps({'model_version': module.MODEL_VERSION})))
    assert module.status()['status'] == 'unavailable'
    assert module.predict('000001')['status'] == 'unavailable'


def test_index_with_invalid_candidate_positions_fails_closed(tmp_path, monkeypatch):
    module, _, days, _ = install(tmp_path, monkeypatch)
    path = tmp_path / 'index' / 'chart_analogue.npz'
    with np.load(path, allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    arrays['candidate_ends'][0] = 999999999
    np.savez(path, **arrays)
    assert module.predict('000001', as_of=cutoff(days[-1]))['status'] == 'unavailable'


def test_date_only_capture_is_unknown_not_a_backdated_timestamp(tmp_path, monkeypatch):
    module, _, days, built = install(tmp_path, monkeypatch, overrides=lambda symbol, index, row: {'update_time': '2030-01-01'} if symbol == '000001' and index == 600 else {})
    assert built['diagnostics']['rejected']['unknown_capture'] == 1
    assert module.predict('000001', as_of=cutoff(days[-1]))['status'] == 'insufficient_history'


def test_weekend_rows_are_not_trading_observations(tmp_path, monkeypatch):
    module, source, days, _ = install(tmp_path, monkeypatch)
    weekend = days[-1]
    while weekend.weekday() != 5:
        weekend += timedelta(days=1)
    with source.open('a', encoding='utf-8', newline='') as stream:
        csv.writer(stream).writerow(['000001', weekend.isoformat(), 'Stock 1', 9999, f'{weekend} 16:00:00'])
    built = module.build_index(source, tmp_path / 'index')
    result = module.predict('000001', as_of=cutoff(weekend))
    assert result['status'] == 'ready'
    assert result['history'][-1]['date'] == days[-1].isoformat()
    assert built['diagnostics']['rejected']['non_session_date'] == 1


def test_large_calendar_gap_prevents_fake_contiguous_target_history(tmp_path, monkeypatch):
    def gap(symbol, index, row):
        if index >= 600:
            shifted = date.fromisoformat(row['date']) + timedelta(days=28)
            return {'date': shifted.isoformat(), 'update_time': f'{shifted} 16:00:00'}
    module, _, days, built = install(tmp_path, monkeypatch, overrides=gap)
    result = module.predict('000001', as_of=cutoff(days[-1] + timedelta(days=28)))
    assert result['status'] == 'insufficient_history'
    assert built['diagnostics']['rejected']['large_gaps'] == 8


def test_future_outcomes_at_cutoff_are_not_allowed_by_feature_end_date_alone(tmp_path, monkeypatch):
    module, _, days, _ = install(tmp_path, monkeypatch)
    result = module.predict('000001', as_of=cutoff(days[300]))
    assert result['status'] == 'ready'
    assert result['history'][-1]['date'] == days[300].isoformat()
    assert all(row['outcome_end_date'] <= days[300].isoformat() for row in result['neighbors'])
    assert all(row['end_date'] < days[300].isoformat() for row in result['neighbors'])


def test_future_append_and_duplicate_rows_cannot_change_past_sampling(tmp_path, monkeypatch):
    module = engine()
    monkeypatch.setattr(module, 'MAX_WINDOWS', 1100)
    def variable(symbol, index, row):
        number = int(symbol)
        return {'current_price': 100 * math.exp(0.0005 * index + 0.04 * math.sin(index / (12 + number)) + 0.00005 * number * index)}
    module, source, days, _ = install(tmp_path, monkeypatch, overrides=variable)
    before = module.predict('000001', as_of=cutoff(days[550]))
    assert before['status'] == 'ready'
    with source.open(encoding='utf-8', newline='') as stream:
        raw_rows = list(csv.DictReader(stream))
    with source.open('a', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(raw_rows[0]))
        writer.writerows(raw_rows[:1300])
        future = days[-1] + timedelta(days=1)
        while future.weekday() >= 5:
            future += timedelta(days=1)
        writer.writerow({'ticker': '000001', 'date': future.isoformat(), 'name': 'Stock 1', 'current_price': 150, 'update_time': f'{future} 16:00:00'})
    module.build_index(source, tmp_path / 'index')
    after = module.predict('000001', as_of=cutoff(days[550]))
    assert after['horizons'] == before['horizons']
    assert after['neighbors'] == before['neighbors']
    assert after['history'] == before['history']


def test_offline_cli_uses_explicit_source_and_output(tmp_path):
    engine()
    source = tmp_path / 'prices.csv'
    prices(source, count=300, symbols=1)
    command = [__import__('sys').executable, str(Path(__file__).resolve().parents[1] / 'scripts' / 'build_chart_analogue_index.py'), '--prices', str(source), '--output', str(tmp_path / 'cli')]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload['source']['rows'] == 300
    assert (tmp_path / 'cli' / 'chart_analogue.npz').exists()
