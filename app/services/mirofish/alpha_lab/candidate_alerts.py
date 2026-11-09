"""New desk events use the existing opt-in private transport, in their own ledger."""
from __future__ import annotations

from copy import deepcopy
import html

from . import candidate_store, store, telegram_alerts
from .desk_selection import directory as desk_directory


def _prepare(root, current):
    desk = candidate_store.read_public(root, now=store.timestamp(current.isoformat()))
    if desk is None or desk.get('state') != 'ready':
        return telegram_alerts._result('no_candidates'), None
    info = dict(decision_id=desk['decision_id'], candidate_count=len(desk['candidates']),
                source_session=desk['latest_session'], sendable=False)
    if not desk['candidates']:
        return telegram_alerts._result('no_candidates', info), None
    records = candidate_store.read_decisions(root)['records']
    frozen = next(r['desk'] for r in records if r['desk']['decision_id'] == desk['decision_id'])
    basis = ('KIS 정규장 OHLC 대조' if frozen.get('source', {}).get('regular_session_verified')
             else 'KIS KRX 일봉')
    lines = ['<b>AlphaLab 실험적 조건부 매수 제안</b>',
             f'가격 기준: {frozen["latest_session"]} · {basis}',
             f'진입 계획: {frozen["entry_session"]} · 최대 10거래일',
             '전향 검증 중 · 사람이 판단하는 참고 계획 · 자동 주문 없음', '']
    for row in frozen['candidates']:
        p = row['plan']; name = html.escape(row['name'][:80], quote=False)
        lines += [f'<b>{row["rank"]}. {name} ({row["symbol"]})</b>',
            f'기준 진입 {p["entry_price"]:,.0f}원 · 추격 상한 {p["entry_upper"]:,.0f}원',
            f'참고 손절 {p["stop_price"]:,.0f}원 · 목표 {p["target_price"]:,.0f}원',
            f'연구 참고 비중 {row["risk"]["reference_weight"]:.1%}', '']
    lines += ['시가가 상한 초과 또는 손절선 이하이면 건너뜁니다. 실제 시가로 손절·목표와 비중을 다시 확인하세요.',
              '<a href="https://bit-man.net/dashboard/ai-bain/chart-predict">검출 근거와 상세 계획</a>']
    message = '\n'.join(lines)
    if len(message.encode('utf-16-le'))//2 >= telegram_alerts.MAX_MESSAGE_UNITS:
        return telegram_alerts._result('invalid_saved_decision', info), None
    info.update(digest=store._hash(message), sendable=True)
    return telegram_alerts._result('preview', info), message


def preview_latest(root, now=None):
    directory = desk_directory(root)
    if not any((directory/name).exists() for name in ('current.json', 'attempt.json', 'decisions.json')):
        return telegram_alerts.preview_latest(root, now=now)
    try:
        return _prepare(directory, candidate_store._clock(now))[0]
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return telegram_alerts._result('invalid_saved_decision')


def deliver_latest(root, now=None, enabled=None, request_get=None, request_post=None):
    directory = desk_directory(root)
    if not any((directory/name).exists() for name in ('current.json', 'attempt.json', 'decisions.json')):
        return telegram_alerts.deliver_latest(root, now=now, enabled=enabled,
                                             request_get=request_get, request_post=request_post)
    return telegram_alerts.deliver_latest(directory, now=now, enabled=enabled,
        request_get=request_get, request_post=request_post, prepare=_prepare)
