import importlib.util
import json
import os
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[2] / 'scripts' / 'backtest_alpha_signals.py'
SPEC = importlib.util.spec_from_file_location('backtest_alpha_signals', SCRIPT_PATH)
backtest_alpha_signals = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(backtest_alpha_signals)


def test_backtest_alpha_signals_compares_plan_a_filter(tmp_path):
    prices = tmp_path / 'daily_prices.csv'
    prices.write_text(
        '\n'.join([
            'ticker,date,current_price',
            '000001,2026-05-01,100',
            '000001,2026-05-02,102',
            '000001,2026-05-03,104',
            '000001,2026-05-04,106',
            '000001,2026-05-05,108',
            '000001,2026-05-06,110',
            '000002,2026-05-01,100',
            '000002,2026-05-02,99',
            '000002,2026-05-03,98',
            '000002,2026-05-04,97',
            '000002,2026-05-05,96',
            '000002,2026-05-06,95',
        ]),
        encoding='utf-8',
    )
    run_dir = tmp_path / 'scanner_runs' / 'mfas_test'
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(json.dumps({
        'id': 'mfas_test',
        'generated_at': '2026-05-01T00:00:00+00:00',
        'candidates': [
            {
                'symbol': '000001',
                'display_name': 'Winner',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 80,
                'risk_score': 20,
                'ranking_score': 69,
                'replay_context': {'price_date': '2026-05-01'},
                'entry_plan': {'stop_pct': 5},
                'analysis_profile': {'false_signal_gates': {'gates': []}},
            },
            {
                'symbol': '000002',
                'display_name': 'Filtered',
                'action': 'BUY_CANDIDATE',
                'alpha_score': 75,
                'risk_score': 25,
                'ranking_score': 61,
                'replay_context': {'price_date': '2026-05-01'},
                'entry_plan': {'stop_pct': 5},
                'analysis_profile': {
                    'false_signal_gates': {
                        'gates': [{'gate': 'thin_liquidity_spike', 'status': 'fail'}],
                    },
                },
            },
        ],
    }), encoding='utf-8')

    report = backtest_alpha_signals.evaluate_runs(
        scanner_root=str(tmp_path / 'scanner_runs'),
        prices_path=str(prices),
        horizon_days=5,
    )

    assert report['baseline']['sample_count'] == 2
    assert report['plan_a_false_signal_filter']['sample_count'] == 1
    assert report['plan_a_false_signal_filter']['win_rate'] == 1.0
    assert 'expectancy_r' in report['baseline']
    assert 'information_coefficient' in report['baseline']
    assert 'thresholds_met' in report['enhanced']
    assert report['enhanced']['thresholds_met']['sample_count'] is False
    assert report['plan_a_success'] is False
    assert report['delta']['sample_count'] == -1
    assert report['lookahead_safe'] is True


def test_backtest_alpha_signals_writes_rolling_report(tmp_path):
    report = {
        'enhanced': {
            'expectancy_r': 0.4,
            'information_coefficient': 0.12,
            'win_rate': 0.6,
            'profit_factor': 1.8,
        },
    }
    output = tmp_path / 'alpha_backtest_rolling_7d.json'

    rolling = backtest_alpha_signals.write_rolling_report(
        current_report=report,
        output_path=str(output),
        daily_report_dir=str(tmp_path),
    )

    assert output.is_file()
    assert rolling['avg_expectancy_r'] == 0.4
    assert rolling['avg_information_coefficient'] == 0.12


def test_load_runs_applies_limit_before_json_load(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    for idx in range(5):
        run_dir = root / f'mfas_20260501000{idx}_test'
        run_dir.mkdir(parents=True)
        run_path = run_dir / 'run.json'
        run_path.write_text(json.dumps({'id': f'run_{idx}', 'candidates': []}), encoding='utf-8')
        ts = 1_700_000_000 + idx
        run_path.touch()
        import os
        os.utime(run_path, (ts, ts))

    opened = []
    import builtins
    real_open = builtins.open

    def counting_open(path, *args, **kwargs):
        if str(path).endswith('run.json'):
            opened.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(backtest_alpha_signals, 'open', counting_open, raising=False)

    runs = backtest_alpha_signals._load_runs(str(root), limit_runs=2)

    assert [run['id'] for run in runs] == ['run_4', 'run_3']
    assert len(opened) == 2


def test_load_runs_filters_runs_newer_than_mature_cutoff(tmp_path):
    root = tmp_path / 'scanner_runs'
    for name in [
        'mfas_20260510000000_recent',
        'mfas_20260503000000_mature',
        'mfas_20260502000000_older',
    ]:
        run_dir = root / name
        run_dir.mkdir(parents=True)
        (run_dir / 'run.json').write_text(json.dumps({'id': name, 'candidates': []}), encoding='utf-8')

    runs = backtest_alpha_signals._load_runs(
        str(root),
        limit_runs=10,
        mature_cutoff_date='2026-05-03',
    )

    assert [run['id'] for run in runs] == [
        'mfas_20260503000000_mature',
        'mfas_20260502000000_older',
    ]


def test_evaluate_runs_reports_mature_cutoff(tmp_path):
    prices = tmp_path / 'daily_prices.csv'
    prices.write_text(
        '\n'.join([
            'ticker,date,current_price',
            '000001,2026-05-01,100',
            '000001,2026-05-02,102',
            '000001,2026-05-03,104',
        ]),
        encoding='utf-8',
    )
    run_dir = tmp_path / 'scanner_runs' / 'mfas_20260501000000_test'
    run_dir.mkdir(parents=True)
    (run_dir / 'run.json').write_text(json.dumps({
        'id': 'mfas_20260501000000_test',
        'generated_at': '2026-05-01T00:00:00+00:00',
        'candidates': [{
            'symbol': '000001',
            'action': 'BUY_CANDIDATE',
            'ranking_score': 70,
            'replay_context': {'price_date': '2026-05-01'},
            'entry_plan': {'stop_pct': 5},
        }],
    }), encoding='utf-8')

    report = backtest_alpha_signals.evaluate_runs(
        scanner_root=str(tmp_path / 'scanner_runs'),
        prices_path=str(prices),
        horizon_days=2,
    )

    assert report['mature_cutoff_date'] == '2026-05-01'
    assert report['baseline']['sample_count'] == 1


def test_load_prices_filters_to_requested_symbols(tmp_path):
    prices = tmp_path / 'daily_prices.csv'
    prices.write_text(
        '\n'.join([
            'ticker,date,current_price',
            '000001,2026-05-01,100',
            '000002,2026-05-01,200',
            '000003,2026-05-01,300',
        ]),
        encoding='utf-8',
    )

    rows = backtest_alpha_signals._load_prices(str(prices), symbols={'000002'})

    assert set(rows) == {'000002'}
    assert rows['000002'][0]['price'] == 200.0


def _write_run(root, day, suffix, *, mtime, generated_at=None, payload=None):
    directory = root / f'mfas_{day}090000_{suffix:012x}'
    directory.mkdir(parents=True)
    path = directory / 'run.json'
    value = payload if payload is not None else {
        'id': directory.name, 'generated_at': generated_at or day, 'candidates': [],
    }
    path.write_text(json.dumps(value), encoding='utf-8')
    os.utime(path, (mtime, mtime))
    return path


def _legacy_load_runs(root, limit, cutoff):
    paths = []
    for directory, _, files in os.walk(root):
        if 'run.json' not in files:
            continue
        path = os.path.join(directory, 'run.json')
        day = backtest_alpha_signals._run_path_date(path)
        if cutoff and day and day > cutoff:
            continue
        paths.append((day or '', os.path.getmtime(path), path))
    paths.sort(reverse=True)
    if limit:
        paths = paths[:max(0, int(limit))]
    records = []
    for _, _, path in paths:
        try:
            run = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            continue
        if isinstance(run, dict):
            records.append((str(run.get('generated_at') or run.get('created_at') or ''), path, run))
    records.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in records][:limit] if limit else [item[2] for item in records]


def test_bounded_run_discovery_does_not_open_old_or_immature_directories(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    for idx in range(30):
        _write_run(root, '20260501', idx, mtime=200 + idx)
    for idx in range(4):
        _write_run(root, '20260503', idx, mtime=100 + idx)
    for idx in range(10):
        _write_run(root, '20260504', idx, mtime=300 + idx)
    expected = _legacy_load_runs(root, 2, '2026-05-03')
    real_scandir = os.scandir
    visited = []
    def track_scandir(path):
        visited.append(os.fspath(path))
        return real_scandir(path)
    monkeypatch.setattr(backtest_alpha_signals.os, 'scandir', track_scandir)
    runs = backtest_alpha_signals._load_runs(str(root), limit_runs=2, mature_cutoff_date='2026-05-03')
    assert runs == expected
    assert visited == [str(root)]


@pytest.mark.parametrize('limit', [None, 0, -1, 1, 3, 8, 20])
def test_bounded_selection_preserves_mtime_ties_maturity_and_corrupt_slots(tmp_path, limit):
    root = tmp_path / 'scanner_runs'
    _write_run(root, '20260501', 0, mtime=9999, generated_at='2026-05-09')
    _write_run(root, '20260502', 0, mtime=103, generated_at='2026-05-01')
    _write_run(root, '20260502', 1, mtime=102, generated_at='2026-05-06')
    _write_run(root, '20260502', 2, mtime=102, generated_at='2026-05-06')
    _write_run(root, '20260502', 3, mtime=104, payload=['not a run'])
    broken = _write_run(root, '20260502', 4, mtime=105)
    broken.write_text('{broken', encoding='utf-8')
    os.utime(broken, (105, 105))
    _write_run(root, '20260503', 0, mtime=9999)
    legacy = root / 'legacy' / 'mfas_20260502000000_imported'
    legacy.mkdir(parents=True)
    (legacy / 'run.json').write_text(json.dumps({'id': 'legacy', 'created_at': '2026-05-04'}), encoding='utf-8')
    unknown = root / 'undated'
    unknown.mkdir()
    (unknown / 'run.json').write_text(json.dumps({'id': 'undated', 'generated_at': '2026-05-08'}), encoding='utf-8')
    expected = _legacy_load_runs(root, limit, '2026-05-02')
    assert backtest_alpha_signals._load_runs(
        str(root), limit_runs=limit, mature_cutoff_date='2026-05-02',
    ) == expected


@pytest.mark.parametrize('rolling', [False, True])
def test_report_write_failure_preserves_previous_valid_report(tmp_path, monkeypatch, rolling):
    target = tmp_path / ('alpha_backtest_rolling_7d.json' if rolling else 'alpha_backtest_daily.json')
    original = '{"previous":"valid"}'
    target.write_text(original, encoding='utf-8')
    def fail_dump(value, handle, **kwargs):
        handle.write('{"incomplete":')
        raise OSError('simulated full disk')
    monkeypatch.setattr(backtest_alpha_signals.json, 'dump', fail_dump)
    with pytest.raises(OSError):
        if rolling:
            backtest_alpha_signals.write_rolling_report(current_report={'enhanced': {}}, output_path=str(target))
        else:
            backtest_alpha_signals.write_report({'new': 'report'}, str(target))
    assert target.read_text(encoding='utf-8') == original
    assert list(tmp_path.iterdir()) == [target]


def test_evaluation_projection_preserves_full_report_and_discards_large_evidence(tmp_path, monkeypatch):
    root = tmp_path / 'scanner_runs'
    prices = tmp_path / 'prices.csv'
    prices.write_text('ticker,date,current_price\n000001,2026-05-01,100\n000001,2026-05-02,105\n'
                      '000002,2026-05-01,100\n000002,2026-05-02,95\n', encoding='utf-8')
    for index in range(3):
        payload = {
            'id': f'run_{index}', 'generated_at': f'2026-05-01T0{index}:00:00Z',
            'source_files': {'unused': 'x' * 100_000},
            'candidates': [
                {'symbol': '000001', 'action': 'BUY_CANDIDATE', 'ranking_score': 75 + index,
                 'price': {'date': '2026-05-01', 'unused': 'x' * 100_000},
                 'entry_plan': {'stop_pct': 5}, 'evidence': ['x' * 100_000],
                 'analysis_profile': {'false_signal_gates': {'hard_blockers': [], 'gates': [{'status': 'pass'}]}}},
                {'symbol': '000002', 'action': 'WATCH', 'ranking_score': 60,
                 'replay_context': {'price_date': '2026-05-01'}, 'entry_plan': {'stop_pct': 2},
                 'strategy_tags': ['credit_pressure'], 'evidence': ['x' * 100_000]},
            ],
        }
        _write_run(root, '20260501', index, mtime=100 + index, payload=payload)
    projected = backtest_alpha_signals._load_runs(str(root), limit_runs=3, candidate_fields_only=True)
    assert len(json.dumps(projected)) < 5000
    optimized = backtest_alpha_signals.evaluate_runs(
        scanner_root=str(root), prices_path=str(prices), horizon_days=1, limit_runs=3,
    )
    real_load_runs = backtest_alpha_signals._load_runs
    def full_load(*args, **kwargs):
        kwargs.pop('candidate_fields_only', None)
        return real_load_runs(*args, **kwargs)
    monkeypatch.setattr(backtest_alpha_signals, '_load_runs', full_load)
    reference = backtest_alpha_signals.evaluate_runs(
        scanner_root=str(root), prices_path=str(prices), horizon_days=1, limit_runs=3,
    )
    optimized.pop('generated_at')
    reference.pop('generated_at')
    assert optimized == reference
    assert optimized['baseline']['sample_count'] == 2
    assert optimized['enhanced']['sample_count'] == 1
