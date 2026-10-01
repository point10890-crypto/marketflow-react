"""Scanner shadow evidence must never influence existing candidate selection."""

import copy
import json
import sys
from types import SimpleNamespace

import pytest

from app.services import mirofish
from app.services.mirofish import alpha_scanner, semantic_ranking


SOURCE = {
    'name': 'local daily chart index',
    'source_id': 'fixture-prices-v1',
    'latest_session': '2026-09-30',
    'captured_at': '2026-09-30T07:30:00+00:00',
    'price_basis': 'unadjusted',
    'built_at': '2026-09-30T08:00:00+00:00',
    'rows': 24000,
    'symbols': 40,
}


def _candidates(count=4):
    return [{
        'symbol': f'{index + 1:06d}',
        'name': f'Candidate {index + 1}',
        'display_name': f'Candidate {index + 1}',
        'market': 'KR',
        'pool_rank': index + 1,
        'ranking_score': 91 - index,
        'alpha_score': 83 - index,
        'risk_score': 12 + index,
        'action': 'BUY_CANDIDATE',
        'signal_quality': 'actionable',
        'price': {'current_price': 1000 + index, 'date': '2026-09-30'},
        'evidence': [{'source': 'daily_prices.csv', 'field': 'trend', 'score': 8, 'value': 4}],
        'freshness': {'status': 'fresh'},
        'analysis_profile': {'source_count': 4},
    } for index in range(count)]


def _prediction(symbol, *, as_of, status='ready', **kwargs):
    return {
        'symbol': symbol,
        'target': f'Candidate {int(symbol)}',
        'status': status,
        'mode': 'shadow',
        'model_version': 'chart-analogue-v1',
        'as_of': as_of,
        'lookback_sessions': 252,
        'source': copy.deepcopy(SOURCE),
        'diagnostics': {'eligible_windows': 21},
        'sample_count': 20 if status == 'ready' else 0,
        'history': [{'date': '2026-09-30', 'close': 1000}],
        'horizons': [{
            'sessions': 20,
            'median_return_pct': -2.5 if symbol == '000001' else 25,
            'p10_return_pct': -10,
            'p90_return_pct': 30,
            'up_frequency_pct': 55,
            'median_price': 975,
            'lower_price': 900,
            'upper_price': 1300,
        }] if status == 'ready' else [],
        'fan': [{'session': 20, 'median_price': 975, 'p10_price': 900, 'p90_price': 1300}],
        'neighbors': [{
            'symbol': '000099', 'target': 'Historical candidate',
            'start_date': '2023-01-01', 'end_date': '2023-12-28',
            'similarity': 0.91, 'returns': {'5': 1, '20': -2.5, '40': 4},
            'outcome_end_date': '2024-02-28', 'captured_at': '2024-02-28T07:30:00+00:00',
        }],
        'warnings': ['raw_price_corporate_action_uncertainty'],
    }


@pytest.fixture
def scanner_harness(monkeypatch, tmp_path):
    """Isolate prepared inputs and optional providers; retain real run persistence."""
    state = {'rows': _candidates(), 'calls': [], 'status_calls': 0}

    def engine_status():
        state['status_calls'] += 1
        return {'status': 'ready', 'model_version': 'chart-analogue-v1', 'source': copy.deepcopy(SOURCE)}

    def engine_predict(symbol, **kwargs):
        state['calls'].append((symbol, kwargs))
        return _prediction(symbol, **kwargs)

    engine = SimpleNamespace(status=engine_status, predict=engine_predict)
    monkeypatch.setattr(mirofish, 'chart_analogue', engine, raising=False)
    monkeypatch.setitem(sys.modules, 'app.services.mirofish.chart_analogue', engine)
    monkeypatch.setattr(alpha_scanner, 'SCANNER_RUNS_ROOT', str(tmp_path / 'runs'))
    monkeypatch.setattr(alpha_scanner, '_load_artifacts', lambda: {'candidate_symbols': {r['symbol'] for r in state['rows']}})
    monkeypatch.setattr(alpha_scanner, '_collect_requested_kis_live', lambda *args: None)
    monkeypatch.setattr(alpha_scanner, '_performance_advisory', lambda: {})
    monkeypatch.setattr(alpha_scanner, '_build_candidate_pool', lambda *args, **kwargs: copy.deepcopy(state['rows']))
    monkeypatch.setattr(alpha_scanner, '_maybe_deepseek_rerank_candidates', lambda *args, **kwargs: {'enabled': False, 'status': 'disabled'})
    monkeypatch.setattr(alpha_scanner, '_source_files', lambda *args, **kwargs: [])
    monkeypatch.setattr(semantic_ranking, 'apply', lambda rows, **kwargs: (rows, {'status': 'disabled'}))
    state['engine'] = engine
    state['root'] = tmp_path / 'runs'
    return state


def test_shadow_evidence_is_added_before_selection_and_preserves_existing_scores(scanner_harness, monkeypatch):
    original_select = alpha_scanner._select_candidates

    def select_after_shadow(rows, limit):
        assert all(row.get('chart_analogue', {}).get('mode') == 'shadow' for row in rows)
        return original_select(rows, limit)

    monkeypatch.setattr(alpha_scanner, '_select_candidates', select_after_shadow)
    run = alpha_scanner.create_scanner_run({'limit': 3})

    assert [(r['symbol'], r['ranking_score'], r['alpha_score'], r['risk_score'], r['action']) for r in run['candidates']] == [
        ('000001', 91, 83, 12, 'BUY_CANDIDATE'),
        ('000002', 90, 82, 13, 'BUY_CANDIDATE'),
        ('000003', 89, 81, 14, 'BUY_CANDIDATE'),
    ]
    assert [r['rank'] for r in run['candidates']] == [1, 2, 3]
    assert [symbol for symbol, _ in scanner_harness['calls']] == ['000001', '000002', '000003', '000004']
    assert all(kwargs['as_of'] == run['generated_at'] for _, kwargs in scanner_harness['calls'])
    assert run['chart_analogue']['ranking_effect'] == 'none'
    assert run['chart_analogue']['applied_to_scoring'] is False
    assert run['chart_analogue']['ready_count'] == 4
    for candidate in run['candidates']:
        shadow = next(e for e in candidate['evidence'] if e['source'] == 'chart_analogue')
        assert shadow['score'] == 0
        assert shadow['value']['as_of'] == run['generated_at']
        assert 'fan' not in candidate['chart_analogue']
        assert 'history' not in candidate['chart_analogue']


def test_full_shadow_artifact_keeps_rejected_pool_results_and_replay_cutoff(scanner_harness):
    run = alpha_scanner.create_scanner_run({'limit': 1})
    artifact = alpha_scanner.read_scanner_run_artifact(run['id'], 'chart_analogue.json')
    assert run['analysis_artifacts']['chart_analogue'].endswith('/artifacts/chart_analogue.json')
    assert artifact['run_id'] == run['id']
    assert artifact['generated_at'] == run['generated_at']
    assert artifact['as_of'] == run['generated_at']
    assert artifact['mode'] == 'shadow'
    assert artifact['source'] == SOURCE
    assert artifact['ranking_effect'] == 'none'
    assert len(artifact['items']) == 4
    assert artifact['items'][0]['fan'][0]['median_price'] == 975
    assert artifact['items'][0]['neighbors'][0]['returns']['20'] == -2.5
    rejected = alpha_scanner.read_scanner_run_artifact(run['id'], 'rejected_candidates.json')
    assert rejected['candidates'][0]['chart_analogue']['mode'] == 'shadow'
    compact = alpha_scanner.read_latest_scanner_candidates(limit=1)
    assert compact['candidates'][0]['chart_analogue']['sample_count'] == 20
    assert compact['candidates'][0]['chart_analogue']['horizons'][0]['sessions'] == 20
    assert compact['chart_analogue']['ready_count'] == 4
    assert 'neighbors' not in compact['candidates'][0]['chart_analogue']


@pytest.mark.parametrize('status', ['missing_index', 'stale_data', 'invalid_index'])
def test_unready_index_skips_prediction_and_remains_visible_without_blocking_run(scanner_harness, status):
    scanner_harness['engine'].status = lambda: {'status': status, 'source': SOURCE, 'warnings': ['refresh_offline_index']}

    def forbidden_predict(*args, **kwargs):
        pytest.fail('An unready index must not start per-candidate prediction work')

    scanner_harness['engine'].predict = forbidden_predict
    run = alpha_scanner.create_scanner_run({'limit': 3})
    assert run['status'] == 'completed'
    assert [c['symbol'] for c in run['candidates']] == ['000001', '000002', '000003']
    assert run['chart_analogue']['status'] == status
    assert run['chart_analogue']['attempted_count'] == 0
    assert run['chart_analogue']['ready_count'] == 0
    assert run['candidates'][0]['chart_analogue']['status'] == status
    assert run['candidates'][0]['chart_analogue']['warnings'] == ['refresh_offline_index']


def test_prediction_error_is_isolated_to_its_candidate_and_stored(scanner_harness):
    def predict_with_error(symbol, **kwargs):
        if symbol == '000002':
            raise RuntimeError('private provider failure text')
        return _prediction(symbol, **kwargs)

    scanner_harness['engine'].predict = predict_with_error
    run = alpha_scanner.create_scanner_run({'limit': 3})
    assert [(c['symbol'], c['ranking_score']) for c in run['candidates']] == [('000001', 91), ('000002', 90), ('000003', 89)]
    assert run['candidates'][1]['chart_analogue']['status'] == 'error'
    assert run['chart_analogue']['status_counts'] == {'ready': 3, 'error': 1}
    artifact = alpha_scanner.read_scanner_run_artifact(run['id'], 'chart_analogue.json')
    assert artifact['items'][1]['warnings'] == ['chart_analogue_prediction_failed:RuntimeError']
    assert 'private provider failure text' not in json.dumps(artifact)


def test_status_error_fails_open_and_does_not_start_predictions(scanner_harness):
    def failed_status():
        raise OSError('private local path')

    scanner_harness['engine'].status = failed_status
    run = alpha_scanner.create_scanner_run({'limit': 1})
    assert run['status'] == 'completed'
    assert run['candidates'][0]['ranking_score'] == 91
    assert run['chart_analogue']['status'] == 'error'
    assert run['chart_analogue']['attempted_count'] == 0
    assert scanner_harness['calls'] == []
    assert run['candidates'][0]['chart_analogue']['warnings'] == ['chart_analogue_status_failed:OSError']


def test_shadow_work_is_bounded_for_a_large_candidate_pool(scanner_harness):
    scanner_harness['rows'] = _candidates(40)
    run = alpha_scanner.create_scanner_run({'limit': 40})
    assert len(scanner_harness['calls']) == 30
    assert scanner_harness['status_calls'] == 1
    assert run['chart_analogue']['attempted_count'] == 30
    assert run['chart_analogue']['skipped_count'] == 10
    assert run['candidates'][29]['chart_analogue']['symbol'] == '000030'
    assert 'chart_analogue' not in run['candidates'][30]
    assert [c['ranking_score'] for c in run['candidates']] == list(range(91, 51, -1))


def test_shadow_preserves_overlay_order_for_tied_scores_at_selection_boundary(scanner_harness, monkeypatch):
    scanner_harness['rows'] = _candidates(31)

    def established_overlay_order(rows, **kwargs):
        # Model the ordering already chosen by existing rerank/semantic stages.
        ordered = [rows[-1], *rows[:-1]]
        for index, row in enumerate(ordered):
            row['ranking_score'] = 77
            row['base_ranking_score'] = 74
            row['ranking_provenance'] = {'deepseek_rerank': {'ranking_adjustment': 3}}
            row['evidence'] *= index + 1
        return ordered, {'status': 'applied'}

    monkeypatch.setattr(semantic_ranking, 'apply', established_overlay_order)
    run = alpha_scanner.create_scanner_run({'limit': 3})
    assert [c['symbol'] for c in run['candidates']] == ['000031', '000001', '000002']
    assert [symbol for symbol, _ in scanner_harness['calls'][:3]] == ['000031', '000001', '000002']
    assert all(c['ranking_score'] == 77 and c['base_ranking_score'] == 74 for c in run['candidates'])
    assert all(c['ranking_provenance']['deepseek_rerank']['ranking_adjustment'] == 3 for c in run['candidates'])


@pytest.mark.parametrize('status', ['insufficient_history', 'insufficient_analogues', 'stale_data'])
def test_candidate_data_failures_are_honestly_preserved(scanner_harness, status):
    scanner_harness['engine'].predict = lambda symbol, **kwargs: _prediction(symbol, status=status, **kwargs)
    run = alpha_scanner.create_scanner_run({'limit': 1})
    assert run['chart_analogue']['status'] == status
    assert run['chart_analogue']['status_counts'] == {status: 4}
    assert run['chart_analogue']['ready_count'] == 0
    assert run['candidates'][0]['chart_analogue']['horizons'] == []
    assert run['candidates'][0]['ranking_score'] == 91


@pytest.mark.parametrize('invalid', ['identity', 'cutoff', 'status_type'])
def test_malformed_prediction_fails_open_without_attaching_wrong_snapshot(scanner_harness, invalid):
    def invalid_prediction(symbol, **kwargs):
        result = _prediction(symbol, **kwargs)
        if invalid == 'identity':
            result['symbol'] = '999999'
        elif invalid == 'cutoff':
            result['as_of'] = '2099-01-01T00:00:00+00:00'
        else:
            result['status'] = ['ready']
        return result

    scanner_harness['engine'].predict = invalid_prediction
    run = alpha_scanner.create_scanner_run({'limit': 1})
    assert run['status'] == 'completed'
    assert run['candidates'][0]['chart_analogue']['status'] == 'error'
    assert run['candidates'][0]['chart_analogue']['symbol'] == '000001'
    assert run['candidates'][0]['chart_analogue']['as_of'] == run['generated_at']
    assert run['candidates'][0]['chart_analogue']['horizons'] == []


def test_malformed_index_status_skips_prediction_and_fails_open(scanner_harness):
    scanner_harness['engine'].status = lambda: {'status': ['ready']}
    run = alpha_scanner.create_scanner_run({'limit': 1})
    assert run['status'] == 'completed'
    assert run['chart_analogue']['status'] == 'error'
    assert run['chart_analogue']['attempted_count'] == 0


def test_reading_an_old_run_never_creates_a_retroactive_forecast(scanner_harness):
    run_dir = scanner_harness['root'] / 'old-run1'
    run_dir.mkdir(parents=True)
    old = {'id': 'old-run1', 'status': 'completed', 'generated_at': '2024-01-01T09:00:00+00:00', 'candidates': [{**_candidates(1)[0], 'rank': 1}]}
    run_path = run_dir / 'run.json'
    saved = json.dumps(old)
    run_path.write_text(saved, encoding='utf-8')

    def forbidden_engine(*args, **kwargs):
        pytest.fail('Reading persisted runs must not calculate new historical forecasts')

    scanner_harness['engine'].status = forbidden_engine
    scanner_harness['engine'].predict = forbidden_engine
    compact = alpha_scanner.read_latest_scanner_candidates()
    assert compact['run_id'] == 'old-run1'
    assert 'chart_analogue' not in compact['candidates'][0]
    assert alpha_scanner.read_scanner_run('old-run1') == old
    assert run_path.read_text(encoding='utf-8') == saved
