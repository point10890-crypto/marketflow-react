import pytest


def size(returns, stop=.08, **kw):
    from app.services.mirofish.alpha_lab.risk import size_from_returns
    return size_from_returns(returns, stop, **kw)


def test_same_realized_net_inputs_and_account_risk_cap():
    out = size([.03]*40+[-.01]*10)
    assert out['qualified']
    assert out['p'] == .8
    assert out['gain_fraction'] == .03
    assert out['loss_fraction'] == .01
    assert out['raw_fraction'] == pytest.approx(.8/.01-.2/.03)
    assert out['weight'] == pytest.approx(.125)
    assert out['planned_account_risk'] == pytest.approx(.01)
    assert out['approval_status'] == 'held'
    assert 0 < out['wilson_lower'] < out['p']


@pytest.mark.parametrize('returns,reason', [([.02]*20+[-.01]*5, 'insufficient_samples'),
                                          ([.02]*40, 'both_return_signs_required'),
                                          ([-.02]*20+[.01]*20, 'nonpositive_net_mean'),
                                          ([.011]*20+[-.01]*20, 't_stat_below_two')])
def test_holds_weak_or_incomplete_evidence(returns, reason):
    out = size(returns)
    assert not out['qualified']
    assert out['weight'] == 0
    assert reason in out['held_reasons']


def test_nonpositive_stress_outcomes_hold_otherwise_qualified_candidate():
    out = size([.03]*40+[-.01]*10, stress_returns=[-.01, .005])
    assert not out['qualified']
    assert 'nonpositive_stress_mean' in out['held_reasons']
    assert out['weight'] == 0


def test_empty_stress_is_not_positive_evidence():
    out = size([.03]*40+[-.01]*10, stress_returns=[])
    assert not out['qualified']
    assert 'missing_stress_outcomes' in out['held_reasons']


@pytest.mark.parametrize('returns,stop', [([float('nan')], .08), ([.01], 0), ([.01], float('inf'))])
def test_nonfinite_or_invalid_risk_inputs_are_rejected(returns, stop):
    with pytest.raises(ValueError):
        size(returns, stop)
