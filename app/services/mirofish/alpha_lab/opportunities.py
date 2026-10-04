"""Manual buy opinions from separate conditional setup research, never orders."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import re
import math

from .proposals import (_mapping, _number, _timestamp, _stamp, _session,
                        _recent_session, _blocked_source, _plan_valid, LABELS, KST)

POLICY = 'quality-setup-opportunity-v1'
BASIS = 'calibration_stress_mean_then_confirmation'
SETUPS = {'momentum': '추세 지속', 'liquidity_breakout': '거래량 동반 돌파', 'mean_reversion': '과매도 회복'}


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_phase(raw, minimum):
    phase = _mapping(raw)
    numbers = [phase.get(key) for key in ('samples', 'wins', 'losses', 'zeros')]
    if not all(_count(value) for value in numbers):
        return False
    n, wins, losses, zeros = numbers
    if n < minimum or wins <= 0 or losses <= 0 or wins+losses+zeros != n:
        return False
    rate = _number(phase.get('win_rate'))
    if rate is None or not math.isclose(rate, wins/n, rel_tol=1e-9, abs_tol=1e-10):
        return False
    for field in ('mean_net_return', 'stress_mean_net_return', 'compounded_trade_return', 'stress_compounded_trade_return'):
        value = _number(phase.get(field))
        if value is None or value <= 0:
            return False
    if phase['stress_mean_net_return'] > phase['mean_net_return']+1e-10:
        return False
    dates = [_session(phase.get(key)) for key in ('start', 'end', 'last_exit_session')]
    return all(dates) and dates[0] <= dates[2] <= dates[1]


def _decision(status, report, row, now, decision, valid_until):
    wait = ('wait', '매수 근거가 최신 조건과 일치하지 않아 새 검출을 기다립니다.',
            '검출 갱신을 눌러 종목별 근거와 가격 계획을 다시 확인하세요.', 0.)
    scan = _mapping(report.get('opportunity_scan'))
    if status.get('state') not in {'ready', 'held'} or scan.get('status') != 'ready':
        return wait
    if 'proposal_window' in report:
        if decision is None or valid_until is None:
            return ('wait', '공식 다음 거래일과 최초 제안의 유효기간을 확인 중입니다.',
                    '거래일 감시 작업의 확인 결과를 기다리세요.', 0.)
        if now >= valid_until:
            return ('wait', '이 제안의 다음 거래일 진입 기간이 종료됐습니다.',
                    '새 장 마감 데이터에서 검출된 다음 제안을 확인하세요. 같은 데이터의 재검출로 기간은 연장되지 않습니다.', 0.)
    if (scan.get('policy_version') != POLICY or scan.get('selection_basis') != BASIS
            or scan.get('latest_session') != report.get('latest_session')
            or scan.get('horizon_sessions') != 10 or scan.get('lookback_sessions') != 1260
            or scan.get('calibration_sessions') != 1008 or scan.get('confirmation_sessions') != 252
            or row.get('strategy_id') not in SETUPS or row.get('setup_active') is not True):
        return wait
    evidence = _mapping(row.get('evidence'))
    calibration, confirmation = (_mapping(evidence.get(key)) for key in ('calibration', 'confirmation'))
    if (evidence.get('selection_basis') != BASIS or evidence.get('retrospective') is not True
            or evidence.get('independent_validation') is not False
            or not isinstance(evidence.get('stronger_evidence'), bool)
            or not _positive_phase(calibration, 30) or not _positive_phase(confirmation, 10)
            or calibration['end'] >= confirmation['start']
            or confirmation['end'] != report.get('latest_session')):
        return wait
    if _blocked_source(report, row) or any('refresh_failed' in str(reason) for reason in scan.get('reasons', [])):
        return wait
    capture = _timestamp(_mapping(report.get('provenance')).get('captured_at'))
    if (decision is None or decision > now or valid_until is None or now >= valid_until
            or capture is None or capture > decision or capture > now
            or not _recent_session(capture.astimezone(KST).date().isoformat(), now)
            or not _recent_session(report.get('latest_session'), now)
            or not _recent_session(_mapping(report.get('universe')).get('scope_date'), now)
            or row.get('quote_session') != report.get('latest_session') or not _plan_valid(row)):
        return wait
    risk = _mapping(row.get('risk'))
    weight, raw, quarter, p = [_number(risk.get(key)) for key in ('research_weight', 'kelly_raw', 'quarter_kelly_fraction', 'p')]
    if (risk.get('weight') != 0 or isinstance(risk.get('weight'), bool)
            or weight is None or not 0 < weight <= .05 or raw is None or raw <= 0
            or quarter is None or not math.isclose(quarter, raw*.25, rel_tol=1e-9, abs_tol=1e-10)
            or p is None or not 0 < p < 1
            or not math.isclose(p, calibration['wins']/(calibration['wins']+calibration['losses']), rel_tol=1e-9)
            or not math.isclose(weight, min(quarter, .05, .01/row['plan']['loss_fraction']), rel_tol=1e-9, abs_tol=1e-10)
            or _number(row.get('score')) is None
            or not math.isclose(row['score'], calibration['stress_mean_net_return'], rel_tol=1e-9, abs_tol=1e-10)):
        return wait
    return ('buy', f"{SETUPS[row['strategy_id']]} 조건이 활성화됐습니다. 이 종목의 앞 기간 {calibration['samples']}건·뒤 기간 {confirmation['samples']}건에서 비용 2배 순손익도 양수인 탐색적 매수 제안입니다.",
            '다음 거래일 시가 진입을 제안합니다. 실제 시가로 ATR 손절·목표를 조정하고 제안 비중을 적용하세요. 최대 10거래일 계획입니다.', weight)



def proposal_window(report):
    """Validate an optional sealed-calendar projection; legacy reports retain24h.

    The API creates this field from the separate monitor registry. Invalid or
    unverified optional windows never fall back to a later rescan timestamp.
    """
    decision = _timestamp(report.get('decision_at'))
    try:
        legacy_until = decision + timedelta(hours=24) if decision else None
    except OverflowError:
        legacy_until = None
    if 'proposal_window' not in report:
        return decision, legacy_until
    window = _mapping(report.get('proposal_window'))
    fingerprint, audit = window.get('input_fingerprint'), window.get('opportunity_audit_hash')
    origin = _timestamp(window.get('origin_at'))
    session = _session(window.get('entry_session'))
    until = _timestamp(window.get('valid_until'))
    capture = _timestamp(_mapping(report.get('provenance')).get('captured_at'))
    if (window.get('policy_version') != 'next-session-proposal-v1'
            or window.get('calendar_source') != 'KIS:CTCA0903R'
            or not isinstance(fingerprint, str) or re.fullmatch(r'[0-9a-f]{64}', fingerprint) is None
            or not isinstance(audit, str) or re.fullmatch(r'[0-9a-f]{64}', audit) is None
            or fingerprint != report.get('input_fingerprint')
            or audit != _mapping(report.get('opportunity_scan')).get('audit_hash')
            or origin is None or decision is None or capture is None or capture > origin
            or origin > decision or session is None or until is None):
        return None, None
    origin_day = origin.astimezone(KST).date()
    from datetime import date
    entry_day = date.fromisoformat(session)
    expected = datetime.combine(entry_day, time(15, 30), tzinfo=KST)
    if (not origin_day < entry_day <= origin_day + timedelta(days=7)
            or until != expected or _session(report.get('latest_session')) is None
            or date.fromisoformat(report['latest_session']) > origin_day):
        return None, None
    return origin, until

def present_opportunities(result, now):
    """Project onto an already copied API view; perform no IO or research."""
    report = _mapping(result.get('report'))
    rows = report.get('buy_candidates')
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return result
    decision, valid_until = proposal_window(report)
    counts = dict(buy=0, wait=0, avoid=0)
    for row in rows:
        action, reason, next_step, weight = _decision(result, report, row, now, decision, valid_until)
        row['proposal'] = dict(action=action, label=LABELS[action], reason=reason[:300], next_step=next_step[:300],
                              proposed_weight=weight, input_session=_session(row.get('quote_session')),
                              derived_at=_stamp(now), valid_until=_stamp(valid_until) if valid_until else None,
                              plan_basis='last_closed_price_next_open_reference', order_allowed=False)
        counts[action] += 1
    action = 'buy' if counts['buy'] else 'wait'
    report['opportunity_summary'] = dict(action=action,
        headline=f"매수 제안 {counts['buy']}종목" if counts['buy'] else '새 매수 후보 검출 대기',
        reason='시총 상위 재무 우량주에서 종목별 진입 조건과 과거 순손익을 검사했습니다. 새로 탐색한 연구 제안이며 미래 수익률이나 통계적 우위 확정이 아닙니다.',
        buy_count=counts['buy'], wait_count=counts['wait'], avoid_count=counts['avoid'], policy_version=POLICY)
    return result
