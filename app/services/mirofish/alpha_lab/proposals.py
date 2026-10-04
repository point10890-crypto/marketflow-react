"""Cheap manual research opinions; no orders, artifact writes or gate changes."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math

KST = timezone(timedelta(hours=9))
POLICY_VERSION = 'alpha-proposal-v1'
LABELS = {'buy': '매수 제안', 'wait': '진입 대기', 'avoid': '매매 제외'}
CURRENT_SOURCE_BLOCKS = {
    'stale_prices', 'stale_scope', 'future_source_capture', 'missing_current_price',
    'price_capture_before_session_close', 'input_pointer_unavailable',
    'input_refresh_failed_previous_snapshot_retained', 'source_refresh_failed', 'refresh_failed',
}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _net_percent(value):
    percent = Decimal(str(value))*100
    if abs(percent) >= Decimal('1e12') or 0 < abs(percent) < Decimal('.05'):
        return f'{percent:.2E}%'
    return f'{percent:.1f}%'


def _timestamp(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _stamp(value):
    return value.isoformat().replace('+00:00', 'Z')


def _session(value):
    try:
        return value if isinstance(value, str) and date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _recent_session(value, now):
    day = _session(value)
    today = now.astimezone(KST).date()
    return day is not None and today-timedelta(days=7) <= date.fromisoformat(day) <= today


def _trades(phase):
    count = _mapping(phase).get('trades')
    return isinstance(count, int) and not isinstance(count, bool) and count >= 30


def _matched_strategy(report, candidate):
    identity = candidate.get('strategy_id')
    strategies = report.get('strategies')
    if not isinstance(identity, str) or not identity or not isinstance(strategies, list):
        return None
    matches = [row for row in strategies if isinstance(row, dict) and row.get('strategy_id') == identity]
    return matches[0] if len(matches) == 1 else None


def _blocked_source(report, candidate):
    groups = [report, _mapping(report.get('champion')), candidate, _mapping(candidate.get('risk'))]
    for group in groups:
        for field in ('reasons', 'warnings'):
            reasons = group.get(field)
            if isinstance(reasons, (list, tuple)):
                if any(isinstance(reason, str) and (reason in CURRENT_SOURCE_BLOCKS or 'refresh_failed' in reason)
                       for reason in reasons):
                    return True
    return False


def _plan_valid(candidate):
    plan = _mapping(candidate.get('plan'))
    values = [_number(plan.get(key)) for key in ('entry_price', 'stop_price', 'target_price', 'loss_fraction')]
    close = _number(candidate.get('last_close'))
    if any(value is None for value in values) or close is None:
        return False
    entry, stop, target, loss = values
    return (0 < stop < entry < target and close > 0 and 0 < loss <= .08+1e-10
            and math.isclose(entry, close, rel_tol=1e-9, abs_tol=1e-9)
            and math.isclose((entry-stop)/entry, loss, rel_tol=1e-7, abs_tol=1e-10))


def _decision(status, report, candidate, now, decision, valid_until):
    if status.get('state') not in {'ready', 'held'}:
        return ('wait', '스캔이 완료되지 않았거나 실패한 상태입니다. 이전 결과로 매수 의견을 내지 않습니다.',
                '새 스캔이 끝난 뒤 최신 근거를 다시 확인하세요.', 0.)
    strategy = _matched_strategy(report, candidate)
    if strategy is None:
        return ('wait', '이 종목과 연결된 전략의 평가 근거를 확인할 수 없습니다.',
                '종목별 전략과 평가 결과를 새 스캔으로 확인하세요.', 0.)
    test, stress = _mapping(strategy.get('test')), _mapping(strategy.get('stress'))
    returns = [_number(phase.get('net_total_return')) for phase in (test, stress)]
    if any(value is not None and value < 0 for value in returns):
        metrics = ', '.join(f'{label} {_net_percent(value)}' for label, value in zip(('전략 테스트', '비용 2배'), returns)
                            if value is not None)
        return ('avoid', f'{metrics}: 이 종목의 신규 매수를 제외합니다.',
                '다음 스캔에서 신규 매수 근거를 다시 확인하세요. 매도 지시는 아닙니다.', 0.)
    if any(value is None or value <= 0 for value in returns) or not all(_trades(phase) for phase in (test, stress)):
        return ('wait', '이후 평가와 비용 스트레스의 양수 수익 및 완료 거래 30건 이상을 함께 확인하지 못했습니다.',
                '충분한 거래 표본과 비용을 반영한 양수 수익 근거를 기다리세요.', 0.)
    champion = _mapping(report.get('champion'))
    validation = _mapping(strategy.get('validation'))
    validation_mean = _number(validation.get('mean_net_return'))
    if (champion.get('strategy_id') != candidate.get('strategy_id')
            or champion.get('selection_basis') != 'validation_only' or strategy.get('qualified') is not True
            or not _trades(validation) or validation_mean is None or validation_mean <= 0):
        return ('wait', '검증 기간만으로 선택된 전략과 이 종목의 충분한 양수 검증 근거가 일치하지 않습니다.',
                '선택된 전략과 검증 기간의 완료 거래·순수익을 다시 확인하세요.', 0.)
    if candidate.get('setup_active') is not True:
        return ('wait', '이 종목의 현재 진입 조건이 활성화되지 않았습니다.',
                '진입 조건이 충족되는 다음 관찰 시점을 기다리세요.', 0.)
    if _blocked_source(report, candidate):
        return ('wait', '현재 가격이나 재무 출처의 갱신 실패·오래된 근거가 표시되어 있습니다.',
                '출처 갱신에 성공한 뒤 새 스캔으로 다시 확인하세요.', 0.)
    capture = _timestamp(_mapping(report.get('provenance')).get('captured_at'))
    if (decision is None or decision > now or valid_until is None or now >= valid_until
            or capture is None or capture > now or capture > decision
            or not _recent_session(capture.astimezone(KST).date().isoformat(), now)
            or not _recent_session(report.get('latest_session'), now)
            or not _recent_session(_mapping(report.get('universe')).get('scope_date'), now)):
        return ('wait', '현재 출처의 날짜·수집 시각 또는 결정 시각이 누락되었거나 유효 기간을 벗어났습니다.',
                '최근 출처로 스캔을 갱신하세요. 매수 의견은 결정 시각부터 24시간만 유효합니다.', 0.)
    quote = candidate.get('quote_session')
    if not _recent_session(quote, now) or quote != report.get('latest_session'):
        return ('wait', '종목별 종가 날짜가 없거나 최신 기준 거래일과 일치하지 않습니다.',
                '이 종목의 최신 종가 날짜를 새 스캔으로 확인하세요.', 0.)
    weight = _number(_mapping(candidate.get('risk')).get('research_weight'))
    probability = _number(_mapping(candidate.get('risk')).get('p'))
    if (weight is None or not 0 < weight <= .2 or probability is None or not 0 < probability < 1
            or not _plan_valid(candidate)):
        return ('wait', '양수 연구 비중과 종가 기준의 유효한 진입·손절·목표 계획을 확인하지 못했습니다.',
                '비중과 손절·목표 계획을 다시 계산한 뒤 직접 판단하세요.', 0.)
    if weight*candidate['plan']['loss_fraction'] > .01+1e-10:
        return ('wait', '제안 비중과 손절 폭으로 다시 계산한 계좌 계획 손실이 1% 한도를 초과합니다.',
                '비중 또는 손절 계획을 다시 계산하고 갭 위험까지 직접 판단하세요.', 0.)
    return ('buy', '현재 진입 조건과 검증·이후 평가·비용 스트레스의 양수 근거가 맞아 수동 매수 검토를 제안합니다.',
            '다음 거래일 시가를 확인하고 손절·목표·비중을 다시 계산한 뒤 직접 판단하세요. 종가 기준 계획은 실제 체결가나 손실 한도를 보장하지 않습니다.', weight)


def present_status(status, *, now=None):
    """Return an additive API view, leaving stored reports/journals untouched."""
    result = deepcopy(status)
    report = _mapping(_mapping(result).get('report'))
    candidates = report.get('candidates')
    if (report.get('schema_version') != 1 or isinstance(report.get('schema_version'), bool)
            or report.get('mode') != 'research' or not isinstance(candidates, list)
            or not all(isinstance(row, dict) for row in candidates)):
        return result
    current = datetime.now(timezone.utc) if now is None else _timestamp(now)
    if current is None:
        raise ValueError('proposal_clock_timezone_required')
    decision = _timestamp(report.get('decision_at'))
    try:
        valid_until = decision+timedelta(hours=24) if decision else None
    except OverflowError:
        valid_until = None
    counts = dict(buy=0, wait=0, avoid=0)
    for candidate in candidates:
        action, reason, next_step, weight = _decision(result, report, candidate, current, decision, valid_until)
        candidate['proposal'] = dict(action=action, label=LABELS[action], reason=reason[:300], next_step=next_step[:300],
            proposed_weight=weight, input_session=_session(candidate.get('quote_session')), derived_at=_stamp(current),
            valid_until=_stamp(valid_until) if valid_until else None,
            plan_basis='last_closed_price_next_open_reference', order_allowed=False)
        counts[action] += 1
    action = 'buy' if counts['buy'] else 'wait' if counts['wait'] or not candidates else 'avoid'
    headline = {'buy': f"오늘 제안: {counts['buy']}종목 매수 검토", 'wait': '오늘 제안: 진입 대기',
                'avoid': '오늘 제안: 신규 매수하지 않음'}[action]
    reason = {'buy': '종가 기준 연구 의견입니다. 다음 거래일 시가와 위험을 다시 확인하고 직접 판단하세요.',
              'wait': '현재 진입이나 근거 조건을 충족하지 못해 새로운 확인을 기다립니다.',
              'avoid': '후보의 해당 전략이 이후 평가에서 손실을 보여 신규 매수를 제외합니다. 매도 지시는 아닙니다.'}[action]
    report['proposal_summary'] = dict(action=action, headline=headline[:160], reason=reason[:300],
        buy_count=counts['buy'], wait_count=counts['wait'], avoid_count=counts['avoid'], policy_version=POLICY_VERSION)
    return result
