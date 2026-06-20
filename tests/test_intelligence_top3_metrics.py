"""TOP3 detection scorecard tests — deterministic, lookahead-safe, no network."""
from app.services.mirofish.intelligence import top3_metrics


def _item(rank, ret, hit, *, symbol=None, ranking_score=0.0, status='evaluated'):
    return {
        'rank': rank,
        'symbol': symbol or f'{rank:06d}',
        'status': status,
        'hit': hit,
        'forward_return_pct': ret,
        'entry_date': '2026-06-10',
        'feature_snapshot': {'ranking_score': ranking_score},
    }


def test_ordered_items_filters_and_sorts():
    items = [
        _item(3, 1.0, True),
        _item(1, 9.0, True),
        {'rank': 2, 'symbol': 'x', 'status': 'pending', 'hit': None, 'forward_return_pct': None},
        _item(2, 4.0, False),
    ]
    ordered = top3_metrics._ordered_items(items)
    assert [it['rank'] for it in ordered] == [1, 2, 3]  # pending dropped, rank-sorted


def test_perfect_ranking_scores_top():
    # rank 1..4 with monotonically decreasing returns, top3 all hits
    items = [_item(1, 12.0, True), _item(2, 8.0, True), _item(3, 5.0, True), _item(4, -3.0, False)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf1', entry_date='2026-06-10')
    assert m['n'] == 4
    assert m['precision_at_3'] == 1.0
    assert m['ndcg_at_3'] == 1.0
    assert m['rank_ic'] == 1.0
    assert m['baseline_hit_rate'] == 0.75
    assert m['hit_lift_at_3'] == 0.25
    assert m['insufficient'] is False


def test_reverse_ranking_negative_rank_ic():
    # scanner ranks ascending but realized returns ascending → bad ordering
    items = [_item(1, -3.0, False), _item(2, 5.0, True), _item(3, 8.0, True), _item(4, 12.0, True)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf2')
    assert m['rank_ic'] == -1.0
    assert m['precision_at_3'] < 1.0


def test_small_run_marks_insufficient_and_null_rank_ic():
    items = [_item(1, 5.0, True), _item(2, -2.0, False)]
    m = top3_metrics._compute_run_metrics(items, workflow_id='wf3')
    assert m['n'] == 2
    assert m['insufficient'] is True
    assert m['rank_ic'] is None
    assert m['precision_at_1'] == 1.0


def _run(wf, triples):
    # triples: list of (rank, ret, hit)
    return {'workflow_id': wf, 'entry_date': '2026-06-10',
            'items': [_item(r, ret, hit) for (r, ret, hit) in triples]}


def test_aggregate_pooled_and_macro():
    runs = [
        _run('wf1', [(1, 10.0, True), (2, 6.0, True), (3, 4.0, True), (4, -2.0, False)]),
        _run('wf2', [(1, 8.0, True), (2, -1.0, False), (3, 3.0, True), (4, -5.0, False)]),
    ]
    agg = top3_metrics._aggregate_runs(runs)
    assert agg['evaluated_runs'] == 2
    assert agg['qualified_runs'] == 2
    assert agg['total_evaluated_items'] == 8
    # pooled top3 = 6 items (3 per run), 5 hits → 0.8333
    assert agg['pooled']['top3_item_count'] == 6
    assert agg['pooled']['top3_hit_rate'] == round(5 / 6, 4)
    assert agg['pooled']['baseline_item_count'] == 8
    assert agg['pooled']['top3_hit_lift'] is not None
    assert agg['macro']['run_count'] == 2
    assert agg['macro']['precision_at_3'] is not None


def test_build_envelope_empty_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    env = top3_metrics.build_top3_metrics(runs=[], write=True)
    assert env['schema_version'] == 'mirofish.top3_metrics.v1'
    assert env['evaluated_runs'] == 0
    assert env['insufficient'] is True
    assert env['pooled']['top3_hit_rate'] is None
    assert env['macro']['precision_at_3'] is None
    # round-trips from disk
    assert top3_metrics.read_top3_metrics()['evaluated_runs'] == 0


def test_min_runs_gate_flags_insufficient(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    runs = [_run(f'wf{i}', [(1, 5.0, True), (2, 3.0, True), (3, 1.0, False)]) for i in range(3)]
    env = top3_metrics.build_top3_metrics(runs=runs, write=False)
    assert env['qualified_runs'] == 3
    assert env['insufficient'] is True  # 3 < MIN_RUNS (5)
    assert len(env['runs']) == 3


def test_summary_compact_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(top3_metrics, 'TOP3_METRICS_PATH', str(tmp_path / 't3.json'))
    top3_metrics.build_top3_metrics(runs=[_run('wf1', [(1, 5.0, True), (2, 3.0, True), (3, 1.0, False)])], write=True)
    s = top3_metrics.top3_metrics_summary()
    assert set(['evaluated_runs', 'qualified_runs', 'insufficient', 'pooled', 'macro']).issubset(s.keys())
    assert 'runs' not in s
