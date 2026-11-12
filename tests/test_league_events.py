import pytest

from app.services.forecast_league import events
from app.services.mirofish import paper_positions as pp


def _bar(day, open_, high, low, close):
    return {'date': f'2026-01-{day:02d}', 'open': open_, 'high': high, 'low': low, 'close': close}


FLAT = [_bar(day, 100, 103, 97, 100) for day in range(2, 10)]   # 8 거래일, 어느 쪽도 닿지 않음


def test_target_hit_is_a_success():
    result = events.evaluate_e1([_bar(2, 100, 104, 98, 103), _bar(3, 103, 108.5, 102, 107)], cost_pct=0.23)
    assert (result['outcome'], result['exit_reason'], result['exit_date']) == (1, 'target', '2026-01-03')
    assert result['entry_price'] == 100 and result['exit_price'] == pytest.approx(108.0)
    assert result['gross_return_pct'] == pytest.approx(8.0)
    assert result['net_return_pct'] == pytest.approx(7.77)


def test_stop_hit_is_a_failure():
    result = events.evaluate_e1([_bar(2, 100, 101, 92.5, 94)], cost_pct=0.23)
    assert (result['outcome'], result['exit_reason']) == (0, 'stop')
    assert result['exit_price'] == pytest.approx(93.0)
    assert result['net_return_pct'] == pytest.approx(-7.23)


def test_both_touched_on_the_same_day_is_a_failure():
    result = events.evaluate_e1([_bar(2, 100, 110, 92, 105)], cost_pct=0.0)
    assert (result['outcome'], result['exit_reason']) == (0, 'stop')


def test_expiry_on_the_eighth_session_is_a_failure_at_the_close():
    bars = FLAT[:7] + [_bar(9, 100, 104, 99, 104)]
    result = events.evaluate_e1(bars, cost_pct=0.0)
    assert (result['outcome'], result['exit_reason'], result['exit_date']) == (0, 'expiry', '2026-01-09')
    assert result['gross_return_pct'] == pytest.approx(4.0)


def test_undecided_until_enough_sessions_exist():
    assert events.evaluate_e1([], cost_pct=0.0) is None
    assert events.evaluate_e1(FLAT[:7], cost_pct=0.0) is None


def test_sessions_after_the_eighth_are_ignored():
    bars = FLAT + [_bar(12, 100, 200, 100, 200)]
    assert events.evaluate_e1(bars, cost_pct=0.0)['exit_reason'] == 'expiry'


def test_non_positive_entry_is_an_error():
    with pytest.raises(ValueError):
        events.evaluate_e1([_bar(2, 0, 1, 0, 1)], cost_pct=0.0)


@pytest.mark.parametrize('bars', [
    [_bar(2, 100, 104, 98, 103), _bar(3, 103, 108.5, 102, 107)],
    [_bar(2, 100, 101, 92.5, 94)],
    [_bar(2, 100, 110, 92, 105)],
    FLAT[:7] + [_bar(9, 100, 104, 99, 104)],
])
def test_matches_the_paper_position_engine(tmp_path, monkeypatch, bars):
    """CIO SELL 청산이 없는 사례에서 가상 매매 엔진과 같은 입력에 같은 결과."""
    monkeypatch.setattr(pp, 'LEDGER_PATH', str(tmp_path / 'paper.json'))
    for name in ('MIROFISH_PAPER_DISABLED', 'MIROFISH_PAPER_TARGET_PCT', 'MIROFISH_PAPER_STOP_PCT',
                 'MIROFISH_PAPER_MAX_DAYS'):
        monkeypatch.delenv(name, raising=False)
    pp.save_ledger({'pending': [{'symbol': '005930', 'name': 'x', 'market': '', 'detected_at': '2026-01-01',
                                 'workflow_id': '', 'run_id': '', 'score': None}], 'open': [], 'closed': []})
    feed = lambda symbol: bars  # noqa: E731
    pp.settle_pending(feed)
    paper = pp.evaluate_positions(feed, cio_actions={})[0]
    league = events.evaluate_e1(bars, cost_pct=0.0)
    assert league['exit_reason'] == paper['exit_reason']
    assert league['exit_date'] == paper['exit_date']
    assert league['exit_price'] == pytest.approx(paper['exit_price'], abs=1e-3)
    assert league['gross_return_pct'] == pytest.approx(paper['return_pct'], abs=0.006)
