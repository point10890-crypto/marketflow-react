import importlib
import pytest


def research():
    try:
        return importlib.import_module('app.services.mirofish.semantic_research')
    except ModuleNotFoundError:
        pytest.fail('offline semantic research not implemented')


def rows():
    return [
        {'symbol': str(i), 'market': 'TEST', 'decision_at': f'2026-09-{day:02}T00:00:00+00:00',
         'available_at': f'2026-09-{day:02}T00:00:00+00:00',
         'label_end_at': f'2026-09-{day+1:02}T00:00:00+00:00',
         'event_id': f'{day}-{i}', 'features': {'alpha': float(i), 'semantic': float(i)},
         'baseline_score': float(-i), 'gross_return': i*.01,
         'benchmark_return': .005, 'cost_bps': 10, 'execution_status': 'filled'}
        for day in (1, 2, 3, 10, 11) for i in range(5)]


def test_chronological_model_uses_mature_train_labels_and_same_test_cohort():
    r = research().train_evaluate(rows(), train_before='2026-09-05T00:00:00Z',
        test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')
    assert r['train_rows'] == 15 and r['test_rows'] == 10
    assert r['metrics']['mean_excess_return_at3'] > r['metrics']['baseline_mean_excess_return_at3']
    assert r['ranking_effect'] == 'none'
    assert r['promotion'] == 'not_authorized'


def test_future_feature_rejected_and_missing_return_not_zero_filled():
    rs = rows()
    rs[0]['available_at'] = '2026-10-01T00:00:00Z'
    rs[1]['gross_return'] = None
    r = research().train_evaluate(rs, train_before='2026-09-05T00:00:00Z',
        test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')
    assert r['excluded_rows'] == 2 and r['train_rows'] == 13


def test_train_test_event_leakage_purged():
    rs = rows()
    rs[-1]['event_id'] = rs[0]['event_id']
    r = research().train_evaluate(rs, train_before='2026-09-05T00:00:00Z',
        test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')
    assert r['purged_event_rows'] == 1


def test_duplicate_identity_and_invalid_split_rejected():
    m = research()
    with pytest.raises(ValueError):
        m.train_evaluate(rows()+[rows()[0]], train_before='2026-09-05T00:00:00Z',
            test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')
    with pytest.raises(ValueError):
        m.train_evaluate(rows(), train_before='2026-09-15T00:00:00Z',
            test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')


def test_partial_source_overlap_purged_across_different_event_groups():
    rs = rows()
    rs[0]['event_ids'] = ['shared', 'train-only']
    rs[-1]['event_ids'] = ['shared', 'test-only']
    r = research().train_evaluate(rs, train_before='2026-09-05T00:00:00Z',
        test_from='2026-09-10T00:00:00Z', as_of='2026-09-15T00:00:00Z')
    assert r['purged_event_rows'] == 1
