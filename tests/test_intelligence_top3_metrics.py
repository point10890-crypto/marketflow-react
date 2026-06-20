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
