"""Chart similarity is research evidence, never an invented trading approval."""
import copy
import csv
import importlib
import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from app.services.mirofish import chart_analogue


def service():
    return importlib.import_module('app.services.mirofish.chart_analogue_kelly')


def sessions(count=1600):
    day = date(2020, 1, 2)
    result = []
    while len(result) < count:
        if day.weekday() < 5:
            result.append(day)
        day += timedelta(days=1)
    return result


def universe(days, symbols=5):
    ranked = [{'symbol': f'{i+1:06d}', 'name': f'Quality {i+1}', 'market': 'KOSPI',
               'rank': i+1, 'market_cap': (10-i)*1e12} for i in range(symbols)]
    return {'as_of': days[-1].isoformat(), 'ranking': {'as_of': days[-1].isoformat(), 'ranked': ranked},
            'quality': {'as_of': days[-1].isoformat(), 'passed': copy.deepcopy(ranked)}}


@pytest.fixture(scope='module')
def installed(tmp_path_factory):
    root = tmp_path_factory.mktemp('kelly-chart')
    source = root / 'source.csv'
    days = sessions()
    with source.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['ticker', 'date', 'name', 'current_price', 'update_time'])
        writer.writeheader()
        for owner in range(6):
            for i, day in enumerate(days):
                # Smooth same-shape histories with observed short-term variation.
                close = 100 * math.exp(.0007*i + .035*math.sin(i/20 + owner*.03))
                writer.writerow({'ticker': f'{owner+1:06d}', 'date': day.isoformat(),
                                 'name': f'Quality {owner+1}', 'current_price': close,
                                 'update_time': f'{day}T08:00:00Z'})
    chart_analogue.build_index(source, root, price_basis='provider_adjusted', source_id='fixture_closed')
    return root, days


def run(installed, **kwargs):
    root, days = installed
    return service().scan(universe(days), as_of=f'{days[-1]}T08:00:00Z', index_root=root, **kwargs)


def test_scope_cutoff_next_entry_cost_and_purged_samples(installed):
    report = run(installed)
    data, _ = chart_analogue._load(full=True, index_root=installed[0])
    assert report['status'] == 'ready'
    assert report['mode'] == 'research'
    assert report['universe']['processed'] == 5
    assert report['universe']['reference_symbols'] == 5
    assert all(row['symbol'] != '000006' for row in report['leaderboard'])
    split = report['source']['split_date']
    seen = []
    for cohorts in report['_audit']['cohorts'].values():
        for group in ('train', 'validation'):
            for row in cohorts[group]:
                assert row['symbol'] != '000006'
                assert row['anchor_date'] < row['entry_date'] < row['exit_date']
                owner = int(np.searchsorted(data['symbols'], row['symbol']))
                begin, finish = int(data['offsets'][owner]), int(data['offsets'][owner+1])
                dates = data['dates'][begin:finish]
                anchor = begin + int(np.searchsorted(dates, (date.fromisoformat(row['anchor_date'])-chart_analogue.EPOCH).days))
                assert row['entry_date'] == chart_analogue._date(data['dates'][anchor+1])
                assert row['exit_date'] == chart_analogue._date(data['dates'][anchor+21])
                assert row['entry_close'] == float(data['closes'][anchor+1])
                assert row['exit_close'] == float(data['closes'][anchor+21])
                assert row['captured_at'] <= report['as_of']
                assert row['net_return'] == pytest.approx(row['exit_close']/row['entry_close']-1-.0033)
                assert row['gross_return_pct'] == pytest.approx((row['exit_close']/row['entry_close']-1)*100)
                if group == 'train':
                    assert row['exit_date'] < split
                else:
                    assert row['start_date'] >= split
                seen.append(row)
        by_owner = {}
        for row in cohorts['train'] + cohorts['validation']:
            by_owner.setdefault(row['symbol'], []).append(row)
        for owner_rows in by_owner.values():
            ordered = sorted(owner_rows, key=lambda row: row['start_date'])
            assert all(a['exit_date'] < b['start_date'] for a, b in zip(ordered, ordered[1:]))
    assert seen
    assert report['approval']['status'] == 'held'
    assert report['approval']['approved_exposure'] == 0
    assert all(row['kelly']['approved_weight'] is None for row in report['leaderboard'])
    assert all(row['kelly']['research_weight'] == 0 for row in report['leaderboard'])
    json.dumps(report, allow_nan=False)


def test_same_target_cases_finish_before_query_input(installed):
    report = run(installed)
    for row in report['leaderboard']:
        for group in ('train', 'validation'):
            for case in report['_audit']['cohorts'][row['symbol']][group]:
                if case['symbol'] == row['symbol']:
                    assert case['exit_date'] < report['_audit']['cohorts'][row['symbol']]['query_start_date']


def test_pins_one_index_and_does_not_mutate_shared_arrays(installed, monkeypatch):
    root, _ = installed
    original = chart_analogue._load(full=True, index_root=root)
    hashes = {key: value.tobytes() for key, value in original[0].items() if isinstance(value, np.ndarray)}
    calls = []
    def load(**kwargs):
        calls.append(kwargs)
        return original
    monkeypatch.setattr(chart_analogue, '_load', load)
    first = run(installed)
    assert len(calls) == 1
    assert all(original[0][key].tobytes() == value for key, value in hashes.items())
    second = run(installed)
    for result in (first, second):
        result.pop('generated_at')
    assert first == second


@pytest.mark.parametrize('change,reason', [
    (lambda u: u['quality']['passed'].append(copy.deepcopy(u['quality']['passed'][0])), 'invalid_universe'),
    (lambda u: u['quality']['passed'][0].update(market='KOSDAQ'), 'invalid_universe'),
    (lambda u: u['quality']['passed'][0].update(symbol='000099'), 'invalid_universe'),
    (lambda u: u.update(as_of='2099-01-01'), 'future_universe'),
    (lambda u: u.update(as_of='2000-01-01'), 'stale_universe'),
    (lambda u: u['quality']['passed'][0].update(financial={'fetched_at': '2099-01-01T00:00:00Z'}), 'future_universe_capture'),
])
def test_bad_universe_is_blocked_without_loading_index(installed, monkeypatch, change, reason):
    root, days = installed
    scope = universe(days)
    change(scope)
    monkeypatch.setattr(chart_analogue, '_load', lambda **kwargs: pytest.fail('Invalid universe cannot inspect prices'))
    report = service().scan(scope, as_of=f'{days[-1]}T08:00:00Z', index_root=root)
    assert report['status'] == 'blocked'
    assert reason in report['warnings']
    assert report['candidates'] == []


@pytest.mark.parametrize('field,value,reason', [
    ('price_basis', 'unadjusted', 'unadjusted_index'),
    ('latest_session', '2000-01-01', 'stale_data'),
    ('captured_at', '2099-01-01T00:00:00Z', 'future_index_capture'),
])
def test_bad_source_cannot_generate_watchlist(installed, monkeypatch, field, value, reason):
    root, _ = installed
    data, error = chart_analogue._load(full=True, index_root=root)
    altered = {**data, 'metadata': copy.deepcopy(data['metadata'])}
    altered['metadata']['source'][field] = value
    monkeypatch.setattr(chart_analogue, '_load', lambda **kwargs: (altered, error))
    report = run(installed)
    assert report['status'] == 'blocked'
    assert reason in report['warnings']


def test_microsecond_future_prices_do_not_enter_selected_cases(installed, monkeypatch):
    root, days = installed
    data, _ = chart_analogue._load(full=True, index_root=root)
    altered = {**data, 'captures_actual_us': data['captures_actual_us'].copy()}
    # This completed price is in the current reference, but capture is 1us late.
    last = int(data['offsets'][1])-1
    altered['captures_actual_us'][last] += 1
    monkeypatch.setattr(chart_analogue, '_load', lambda **kwargs: (altered, None))
    report = run(installed)
    row = next(row for row in report['leaderboard'] if row['symbol'] == '000001')
    assert row['research_status'] == 'insufficient'
    assert 'future_query_capture' in row['reasons']
    assert row['kelly']['research_weight'] == 0


def test_chart_cases_are_observed_paths_not_predictions(installed):
    report = run(installed)
    for row in report['candidates']:
        assert len(row['chart']['query']) == 64
        assert row['chart']['query'][-1] == 100
        for case in row['chart']['cases']:
            assert len(case['input']) == 64 and case['input'][-1] == 100
            assert len(case['future']) == 21
            assert case['future'][-1]/case['future'][0]-1 == pytest.approx(case['gross_return_pct']/100, abs=1e-7)


def test_all_wins_do_not_fabricate_infinite_payoff_or_approval():
    svc = service()
    rows = [{'symbol': '000001', 'start_date': '2020-01-01', 'exit_date': '2021-02-01',
             'net_return': .02, 'similarity': .9} for _ in range(40)]
    metric = svc._metric(rows)
    assert metric['sample_count'] == 40 and metric['net_win_rate_pct'] == 100
    assert metric['payoff_ratio'] is None
    assert 'payoff_unavailable' in svc._gate(metric, 'validation')
    json.dumps(metric, allow_nan=False)


def test_cost_turns_small_gross_gain_into_loss_and_wilson_gate_is_stricter_than_raw_rate():
    rows = [{'symbol': '000001', 'start_date': '2020-01-01', 'exit_date': '2021-02-01',
             'net_return': (.003-.0033 if i >= 18 else .02), 'similarity': .9} for i in range(30)]
    metric = service()._metric(rows)
    assert metric['net_win_rate_pct'] == 60
    assert metric['wilson_lower_pct'] < 60
    assert 'validation_wilson_below_60' in service()._gate(metric, 'validation')


def test_missing_symbols_remain_visible_with_no_numeric_inventions(installed):
    root, days = installed
    scope = universe(days)
    scope['ranking']['ranked'][0]['symbol'] = scope['quality']['passed'][0]['symbol'] = '999999'
    report = service().scan(scope, as_of=f'{days[-1]}T08:00:00Z', index_root=root)
    missing = next(row for row in report['leaderboard'] if row['symbol'] == '999999')
    assert missing['train'] is missing['validation'] is None
    assert missing['current_close'] is None and missing['chart']['query'] == []
    assert missing['kelly']['empirical_fraction'] is None
    assert 'symbol_missing' in missing['reasons']
    assert missing not in report['candidates']


def test_stable_research_kelly_is_half_capped_guarded_and_never_approved():
    svc = service()
    cases = [{'symbol': f'{i+1:06d}', 'start_date': '2020-01-01', 'exit_date': '2021-02-01',
              'net_return': .05 if i < 32 else -.02, 'similarity': .9} for i in range(40)]
    metric = svc._metric(cases)
    assert svc._gate(metric, 'train') == svc._gate(metric, 'validation') == []
    kelly = svc._kelly(cases, .02)
    assert kelly['empirical_fraction'] == pytest.approx(1)
    assert kelly['half_fraction'] == pytest.approx(.5)
    assert kelly['capped_fraction'] == pytest.approx(.2)
    assert kelly['approved_weight'] is None
    guarded = svc._kelly(cases, .031)
    assert guarded['volatility_guard'] is True
    assert guarded['capped_fraction'] == pytest.approx(.1)
    rows = [{'symbol': f'{i+1:06d}', 'research_status': 'stable', 'kelly': copy.deepcopy(kelly),
             'score': 2., 'chart': {'cases': [{}]}} for i in range(4)]
    portfolio = svc._portfolio(rows)
    assert portfolio['research_exposure'] == pytest.approx(.6)
    assert portfolio['research_cash'] >= .4
    assert rows[-1]['kelly']['research_weight'] == 0
    assert all(row['kelly']['approved_weight'] is None for row in rows)
    pending = svc._kelly(cases[:29], .02)
    assert pending['empirical_fraction'] is pending['half_fraction'] is pending['capped_fraction'] is None


def test_invalid_bank_partition_and_future_midspan_are_not_selected(installed, monkeypatch):
    root, _ = installed
    data, _ = chart_analogue._load(full=True, index_root=root)
    altered = {**data, 'candidate_ends': data['candidate_ends'].copy(),
               'captures_actual_us': data['captures_actual_us'].copy()}
    altered['candidate_ends'][0] = int(data['offsets'][1])-10
    altered['captures_actual_us'][600] = 4_102_444_800_000_000  # 2100-01-01
    monkeypatch.setattr(chart_analogue, '_load', lambda **kwargs: (altered, None))
    report = run(installed)
    assert report['_audit']['bank_rejections']['cross_partition'] >= 1
    assert report['_audit']['bank_rejections']['invalid_or_future_case'] >= 1
    forbidden_day = chart_analogue._date(data['dates'][600])
    for cohorts in report['_audit']['cohorts'].values():
        for case in cohorts['train'] + cohorts['validation']:
            if case['symbol'] == '000001':
                assert not case['start_date'] <= forbidden_day <= case['exit_date']


def test_mutating_returned_metadata_does_not_poison_cached_index(installed):
    root, _ = installed
    report = run(installed)
    report['source']['collection_summary']['fresh_symbols'] = -99
    cached, _ = chart_analogue._load(full=True, index_root=root)
    assert cached['metadata']['source']['collection_summary']['fresh_symbols'] >= 0


def test_watch_score_has_percent_return_units_and_reject_counts_count_symbols(installed):
    report = run(installed)
    assert report['policy']['score_basis'] == 'net_expectancy_pct_plus_half_net_p10_pct'
    assert all(count <= report['universe']['processed'] for count in report['universe']['rejected'].values())
    for row in report['leaderboard']:
        if row['chart']['cases']:
            metric = row['validation'] or row['train']
            assert row['score'] == pytest.approx(metric['expectancy_pct']+.5*metric['p10_pct'])
    assert all(row['score'] > 0 for row in report['candidates'])
    assert [row['rank'] for row in report['candidates']] == list(range(1, len(report['candidates'])+1))


def test_nonpositive_historical_outcomes_do_not_pad_three_watch_candidates(installed, monkeypatch):
    svc = service()
    original = svc._case
    def losing(*args, **kwargs):
        row = original(*args, **kwargs)
        row.update(net_return=-.05, net_return_pct=-5.)
        return row
    monkeypatch.setattr(svc, '_case', losing)
    report = run(installed)
    assert report['candidates'] == []
    assert report['portfolio']['research_exposure'] == 0
    assert all(row['score'] <= 0 for row in report['leaderboard'])
