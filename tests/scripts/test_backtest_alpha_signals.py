import importlib.util
import json
from pathlib import Path


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
