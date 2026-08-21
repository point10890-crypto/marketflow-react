"""메시지 빌더 — 템플릿만 사용. HALT 중에는 종목 방향성 문구를 만들지 않는다."""
from __future__ import annotations

from datetime import datetime
from typing import Any

GRADE_MARK = {'S': '🟡S', 'A': '🟢A', 'B': '⚪B'}
TYPE_LABEL = {
    'LEADER_NEW': 'NEW', 'LEADER_UPGRADE': 'UP', 'LEADER_DROP': 'DROP',
    'VOLUME_SURGE': 'VOL', 'NEW_HIGH_BREAK': 'HIGH',
}


def _pct(v: float | None) -> str:
    return f"{v:+.1f}%" if v is not None else '-'


def _day_label(ts: str | None = None) -> str:
    d = datetime.fromisoformat(ts) if ts else datetime.now()
    return d.strftime('%m-%d(%a)')


def _regime_line(reg: dict[str, Any]) -> str:
    parts = [f"레짐 <b>{reg.get('regime')}</b>"]
    if reg.get('gate_score') is not None:
        parts.append(f"gate {reg.get('gate_status')} {reg.get('gate_score')}점")
    if reg.get('breadth_pct') is not None:
        parts.append(f"breadth 상승 {reg['breadth_pct']}%")
    if reg.get('kospi_close'):
        parts.append(f"KOSPI {reg['kospi_close']:,.0f}")
    return ' · '.join(parts)


def halt_message(reg: dict[str, Any], ts: str | None = None) -> str:
    reasons = '\n'.join(f" - {r}" for r in reg.get('reasons') or []) or ' - (사유 없음)'
    return (f"⏸ <b>검출 보류 (HALT)</b> {datetime.now().strftime('%H:%M')}\n"
            f"사유:\n{reasons}\n"
            f"보류 중 동작: 이벤트 발행 중단 · 방향성 문구 없음")


def event_message(events: list[dict[str, Any]], reg: dict[str, Any]) -> str:
    if reg.get('halt'):
        return halt_message(reg)
    lines = [f"⚡ <b>주도주 이벤트</b> {datetime.now().strftime('%H:%M')} · {_regime_line(reg)}", '']
    for e in events[:5]:
        lab = TYPE_LABEL.get(e['type'], e['type'])
        g = GRADE_MARK.get(e.get('grade_to') or e.get('grade') or '', '')
        trans = ''
        if e['type'] in ('LEADER_UPGRADE', 'LEADER_DROP'):
            trans = f" {e.get('grade_from') or '–'}→{e.get('grade_to') or '–'}"
        lines.append(f"[{lab}]{trans} {g} {e['name']} {e['code']} · {e.get('score', 0)}점")
        lines.append(f"  {_pct(e.get('chg'))} · 거래대금 {e.get('trval_eok', 0):,.0f}억")
    if len(events) > 5:
        lines.append(f"… 외 {len(events) - 5}건 (다음 틱으로 이월)")
    return '\n'.join(lines)


def morning_message(snap: dict[str, Any], reg: dict[str, Any], prev_events: list[dict[str, Any]]) -> str:
    if reg.get('halt'):
        return halt_message(reg)
    lines = [f"🦀 <b>Claw 조간 브리핑</b> · {_day_label()}", _regime_line(reg), '']
    lines.append(f"<b>전 세션 이벤트</b> {len(prev_events)}건")
    by_type: dict[str, int] = {}
    for e in prev_events:
        by_type[e['type']] = by_type.get(e['type'], 0) + 1
    if by_type:
        lines.append(' ' + ' · '.join(f"{TYPE_LABEL.get(k, k)} {v}" for k, v in by_type.items()))
    leaders = [r for r in snap.get('rows') or [] if r.get('grade') in ('S', 'A')][:6]
    lines.append('')
    lines.append(f"<b>감시 목록</b> (마지막 스냅샷 {snap.get('ts', '')[11:16]}, {snap.get('source')})")
    for r in leaders:
        lines.append(f" {GRADE_MARK.get(r['grade'], '')} {r['name']} {r['code']} · {r['score']}점 · {_pct(r['chg'])}")
    return '\n'.join(lines)


def close_message(snap: dict[str, Any], reg: dict[str, Any], events: list[dict[str, Any]], stats: dict[str, Any]) -> str:
    if reg.get('halt'):
        return halt_message(reg)
    lines = [f"🏁 <b>마감 요약</b> {_day_label()}", _regime_line(reg),
             f"이벤트 {len(events)}건 · 스냅샷 {stats.get('snapshots', 0)}개 저장", '']
    leaders = [r for r in snap.get('rows') or [] if r.get('grade') in ('S', 'A')]
    lines.append('<b>마감 기준 주도주</b>')
    for r in leaders[:8]:
        lines.append(f" {GRADE_MARK.get(r['grade'], '')} {r['name']} {r['code']} {_pct(r['chg'])} · {r['score']}점 · {r['trval_eok']:,.0f}억")
    drops = [e for e in events if e['type'] == 'LEADER_DROP']
    if drops:
        lines.append('<b>이탈</b> ' + ' · '.join(f"{e['name']} {_pct(e.get('chg'))}" for e in drops[:5]))
    lines.append('')
    lines.append('다음 세션 조간 브리핑에서 이벤트 성과(D1)를 보고합니다.')
    return '\n'.join(lines)
