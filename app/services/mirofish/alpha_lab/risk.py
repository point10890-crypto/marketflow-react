"""Research sizing from completed net outcomes, never from planned gross odds."""
import math
from statistics import fmean, stdev

from ..kelly_position import fractional_kelly, two_point_kelly


def _values(returns):
    diagnostic = two_point_kelly(returns)
    return diagnostic


def size_from_returns(returns, stop_fraction, *, stress_returns=None):
    """Gate evidence then half-Kelly, 20% allocation and 1% planned risk caps.

    The Wilson lower bound is a diagnostic, not calibrated future probability.
    Stop gaps can exceed planned risk. Research qualification grants no approval.
    """
    if (isinstance(stop_fraction, bool) or not isinstance(stop_fraction, (int, float))
            or not math.isfinite(stop_fraction) or not 0 < stop_fraction < 1):
        raise ValueError('stop_fraction must be finite, positive and below one')
    values = list(returns)
    diagnostic = _values(values)
    n, mean = len(values), fmean(values) if values else None
    deviation = stdev(values) if n > 1 else 0.
    t_stat = mean/(deviation/math.sqrt(n)) if deviation > 0 else None
    reasons = []
    if n < 30:
        reasons.append('insufficient_samples')
    if diagnostic['status'] != 'ready':
        reasons.append('both_return_signs_required')
    if mean is None or mean <= 0:
        reasons.append('nonpositive_net_mean')
    if t_stat is None or t_stat < 2:
        reasons.append('t_stat_below_two')
    raw = diagnostic['raw_fraction']
    if raw is None or raw <= 0:
        reasons.append('nonpositive_generalized_kelly')
    stress_mean = None
    if stress_returns is not None:
        stressed = list(stress_returns)
        _values(stressed)
        stress_mean = fmean(stressed) if stressed else None
        if stress_mean is None:
            reasons.append('missing_stress_outcomes')
        elif stress_mean <= 0:
            reasons.append('nonpositive_stress_mean')
    directional = diagnostic['wins']+diagnostic['losses']
    p, lower, z = diagnostic['p'], None, 1.96
    if directional:
        lower = (p+z*z/(2*directional)-z*math.sqrt(p*(1-p)/directional+z*z/(4*directional**2))) / (1+z*z/directional)
    sizing = fractional_kelly(raw if raw is not None else 0.)
    qualified = not reasons
    weight = min(sizing['capped_fraction'], .01/stop_fraction) if qualified else 0.
    return dict(qualified=qualified, status='research' if qualified else 'held', weight=weight,
                held_reasons=reasons, reasons=list(reasons), sample_count=n,
                p=p, gain_fraction=diagnostic['gain_fraction'], loss_fraction=diagnostic['loss_fraction'],
                raw_fraction=raw, fractional_fraction=sizing['fractional_fraction'],
                capped_fraction=sizing['capped_fraction'], mean_net_return=mean, t_stat=t_stat,
                wilson_lower=lower, stress_mean=stress_mean, stop_fraction=stop_fraction,
                planned_account_risk=weight*stop_fraction, approval_status='held',
                model=diagnostic['model'], input_basis='completed_same_policy_net_returns',
                guarantees=[], warnings=['two_point_approximation', 'planned_stop_risk_can_be_exceeded_by_gaps',
                                         'research_qualification_is_not_production_approval'])
