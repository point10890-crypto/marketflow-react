import json

from app.services.mirofish import dual_kalman
from app.services.mirofish import alpha_scanner


def _candidate(symbol, name, alpha=80, risk=25, rank=1):
    return {
        'rank': rank,
        'symbol': symbol,
        'name': name,
        'display_name': name,
        'market': 'KOSPI',
        'action': 'BUY_CANDIDATE',
        'alpha_score': alpha,
        'risk_score': risk,
        'ranking_score': alpha - risk * 0.55,
        'signal_quality': 'actionable',
        'analysis_profile': {'source_count': 4},
        'price': {'current_price': 1000, 'date': '2026-05-30'},
    }


def _write_price_history(path):
    rows = ['ticker,date,name,current_price,change,change_rate,high,low,open,volume,update_time']
    steady_prices = [100, 101, 102, 103, 104, 106, 108, 110, 112, 115, 118, 120, 122, 124, 126]
    spike_prices = [100, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 101, 100, 135]
    for index, close in enumerate(steady_prices, start=1):
        previous = steady_prices[index - 2] if index > 1 else close
        rows.append(
            f"000010,2026-05-{index:02d},Steady,{close},0,0,{close * 1.01:.2f},"
            f"{close * 0.99:.2f},{previous},{1000000 + index * 100000},now"
        )
    for index, close in enumerate(spike_prices, start=1):
        previous = spike_prices[index - 2] if index > 1 else close
        high = 170 if index == len(spike_prices) else close * 1.01
        rows.append(
            f"000020,2026-05-{index:02d},Spike,{close},0,0,{high:.2f},"
            f"{close * 0.98:.2f},{previous},{1000000 + index * 900000},now"
        )
    path.write_text('\n'.join(rows), encoding='utf-8')


def test_dual_kalman_gate_passes_stable_candidate_and_blocks_spike(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_price_history(data_dir / 'daily_prices.csv')
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(data_dir))
    monkeypatch.setattr(dual_kalman, 'KALMAN_RUNS_ROOT', str(tmp_path / 'kalman_runs'))

    scanner_run = {
        'id': 'mfas_test',
        'freshness': {'status': 'fresh'},
        'candidates': [
            _candidate('000010', 'Steady', alpha=82, risk=20, rank=1),
            _candidate('000020', 'Spike', alpha=86, risk=22, rank=2),
        ],
    }

    run = dual_kalman.run_dual_kalman_signal_gate(
        scanner_run,
        scanner_run['candidates'],
        min_confidence=0.55,
        persist=True,
    )

    by_symbol = {item['symbol']: item for item in run['signals']}
    assert run['lookahead_safe'] is True
    assert run['mutates_scanner_scores'] is False
    assert by_symbol['000010']['gate'] == 'pass'
    assert by_symbol['000010']['score_delta'] > 0
    assert by_symbol['000020']['gate'] == 'block'
    assert by_symbol['000020']['score_delta'] < 0
    assert (tmp_path / 'kalman_runs' / run['id'] / 'run.json').is_file()
    assert (tmp_path / 'kalman_runs' / run['id'] / 'signals.json').is_file()


def test_apply_dual_kalman_gate_attaches_shadow_metadata_and_drops_blocks():
    candidates = [
        _candidate('000010', 'Steady', rank=1),
        _candidate('000020', 'Spike', rank=2),
    ]
    kalman_run = {
        'signals': [
            {
                'symbol': '000010',
                'gate': 'pass',
                'score_delta': 2.5,
                'shadow_alpha_score': 82.5,
                'reason': 'ok',
                'kalman': {
                    'signal_confidence': 0.7,
                    'latent_return_z': 1.1,
                    'innovation_z': 0.4,
                    'fair_value_gap_z': 0.8,
                    'volatility_state': 'normal',
                },
            },
            {
                'symbol': '000020',
                'gate': 'block',
                'score_delta': -7,
                'shadow_alpha_score': 73,
                'reason': 'spike',
                'kalman': {'signal_confidence': 0.2},
            },
        ],
    }

    enriched = dual_kalman.apply_dual_kalman_gate_to_candidates(candidates, kalman_run)

    assert [item['symbol'] for item in enriched] == ['000010']
    assert enriched[0]['analysis_profile']['dual_kalman_gate']['gate'] == 'pass'
    assert enriched[0]['shadow_ranking_score'] == round(candidates[0]['ranking_score'] + 2.5, 2)
    assert 'kalman_pass' in enriched[0]['strategy_tags']


def test_create_dual_kalman_run_uses_latest_scanner_run(tmp_path, monkeypatch):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    _write_price_history(data_dir / 'daily_prices.csv')
    monkeypatch.setattr(alpha_scanner, 'DATA_ROOT', str(data_dir))
    monkeypatch.setattr(dual_kalman, 'KALMAN_RUNS_ROOT', str(tmp_path / 'kalman_runs'))
    monkeypatch.setattr(alpha_scanner, 'read_latest_scanner_run', lambda: {
        'id': 'mfas_latest',
        'freshness': {'status': 'fresh'},
        'candidates': [_candidate('000010', 'Steady')],
    })

    run = dual_kalman.create_dual_kalman_run({'scanner_run_id': 'latest', 'limit': 1})
    saved = dual_kalman.read_dual_kalman_run(run['id'])
    signals = dual_kalman.read_dual_kalman_signals(run['id'])

    assert saved['id'] == run['id']
    assert signals['signals'][0]['symbol'] == '000010'


def test_dual_kalman_rejects_unsafe_run_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(dual_kalman, 'KALMAN_RUNS_ROOT', str(tmp_path / 'kalman_runs'))

    try:
        dual_kalman.read_dual_kalman_run('../escape')
    except ValueError as exc:
        assert 'invalid dual kalman run_id' in str(exc)
    else:
        raise AssertionError('unsafe run id should be rejected')
