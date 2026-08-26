"""이벤트 검출 — 연속 스냅샷 diff → 상태 전이.

순수 함수. 입력은 normalize_snapshot 형식의 두 스냅샷과 '당일 이미 발행된
(type, code) 집합'. SECTOR_CLUSTER 는 스크리너 결과에 섹터 필드가 없어
Phase 1 에서는 제외한다(설계 문서 3.3 참고).

LEADER_DROP 은 KIS 부분 실패(타임아웃→수급 점수 0)로 가짜가 나올 수 있어
`confirmed_drops()` 로 연속 N틱 지속을 확인한 뒤에만 발행한다(스파이크 §6-1).
"""
from __future__ import annotations

from typing import Any, Iterable

GRADE_RANK = {'S': 3, 'A': 2, 'B': 1, '': 0}
LEADER_GRADES = {'S', 'A'}
VOLUME_SURGE_PCT = 300.0   # kis_screener.volume_ratio 는 평균 대비 % (raw 거래량이 섞인 행은 상한으로 배제)
VOLUME_RATIO_SANE_MAX = 100000.0


def _score_complete(row: dict[str, Any] | None) -> bool:
    """Legacy rows are trusted; an explicit incomplete marker is not."""
    return bool(row) and not row.get('detection_unknown') and row.get('score_complete') is not False


def _input_available(row: dict[str, Any] | None, input_name: str, reason: str) -> bool:
    """Check one signal input without distrusting unrelated incomplete fields."""
    if not row:
        return False
    if row.get('detection_unknown'):
        return False
    quality = row.get('data_quality')
    inputs = quality.get('inputs') if isinstance(quality, dict) else None
    if isinstance(inputs, dict) and input_name in inputs:
        return inputs.get(input_name) == 'available'
    reasons = row.get('incomplete_reasons')
    if isinstance(reasons, (list, tuple, set)) and reason in reasons:
        return False
    if row.get('score_complete') is False:
        # An older partial row without input-level metadata cannot prove this
        # particular input was reliable.
        return False
    # Historical snapshots predate input-level quality metadata.
    return True


def _index(snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r['code']: r for r in (snap or {}).get('rows', []) if r.get('code')}


def _leaders(snap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c: r for c, r in _index(snap).items()
            if _score_complete(r) and r.get('grade', '') in LEADER_GRADES}


def _event(etype: str, row: dict[str, Any], ts: Any, **extra: Any) -> dict[str, Any]:
    return {
        'type': etype, 'code': row['code'], 'name': row['name'],
        'grade': row.get('grade', ''), 'score': row.get('score', 0),
        'chg': row.get('chg', 0.0), 'trval_eok': row.get('trval_eok', 0.0),
        'volx': row.get('volx', 0.0), 'ts': ts, **extra,
    }


def diff(prev: dict[str, Any] | None, cur: dict[str, Any], *,
         already: Iterable[tuple[str, str]] = (), include_drops: bool = True,
         include_new: bool = True) -> list[dict[str, Any]]:
    """prev→cur 전이 이벤트 목록. prev 가 None 이면 baseline (이벤트 없음).

    include_drops=False 면 LEADER_DROP 은 내지 않는다(게이트웨이가 confirmed_drops 로 대체).
    include_new=False 면 장 마감 직전 새 진입만 억제하고 UP/VOL/HIGH/DROP 은 유지한다.
    """
    if prev is None or prev.get('error') or cur.get('error'):
        return []
    seen = set(already)
    p, c = _index(prev), _index(cur)
    out: list[dict[str, Any]] = []

    def emit(etype: str, row: dict[str, Any], **extra: Any) -> None:
        key = (etype, row['code'])
        if key in seen:
            return
        seen.add(key)
        out.append(_event(etype, row, cur.get('ts'), **extra))

    for code, row in c.items():
        g_now = row.get('grade', '')
        before = p.get(code)
        g_prev = before.get('grade', '') if before else ''
        grades_reliable = _score_complete(row) and (before is None or _score_complete(before))
        if grades_reliable and g_now in LEADER_GRADES and g_prev not in LEADER_GRADES:
            if before is None:
                if include_new:
                    emit('LEADER_NEW', row, grade_from='', grade_to=g_now)
            else:
                emit('LEADER_UPGRADE', row, grade_from=g_prev, grade_to=g_now)
        elif grades_reliable and g_now in LEADER_GRADES and GRADE_RANK[g_now] > GRADE_RANK[g_prev]:
            emit('LEADER_UPGRADE', row, grade_from=g_prev, grade_to=g_now)
        vx, vp = (row.get('volx') or 0), ((before or {}).get('volx') or 0)
        volume_inputs_ready = (
            before is not None
            and _input_available(before, 'prdy_vol', 'prdy_vol')
            and _input_available(row, 'prdy_vol', 'prdy_vol')
        )
        if volume_inputs_ready and VOLUME_SURGE_PCT <= vx < VOLUME_RATIO_SANE_MAX and vp < VOLUME_SURGE_PCT:
            emit('VOLUME_SURGE', row)
        price, hi = row.get('price'), row.get('high_52w')
        high_inputs_ready = (
            before is not None
            and _input_available(before, 'price_detail', 'price_detail_52w_high')
            and _input_available(row, 'price_detail', 'price_detail_52w_high')
        )
        if (high_inputs_ready and price and hi and price >= hi
                and before.get('price') and before.get('high_52w')
                and before['price'] < before['high_52w']):
            emit('NEW_HIGH_BREAK', row)

    if include_drops:
        for code, before in p.items():
            if _score_complete(before) and before.get('grade', '') in LEADER_GRADES:
                now = c.get(code)
                if now is None or (_score_complete(now) and now.get('grade', '') not in LEADER_GRADES):
                    emit('LEADER_DROP', now or before, grade_from=before.get('grade', ''),
                         grade_to=(now or {}).get('grade', ''))
    return out


def confirmed_drops(window: list[dict[str, Any]], n: int, *,
                    already: Iterable[tuple[str, str]] = ()) -> list[dict[str, Any]]:
    """연속 N틱 확정 이탈.

    window 는 오래된 것→최신 순의 스냅샷 목록(최신이 현재 틱). 길이가 n+1 미만이면 판단하지 않는다.
    코드가 window[-(n+1)] 에서 S/A 였고 window[-n:] 의 모든 틱에서 S/A 가 아니면(목록 밖 포함) DROP.
    오류 스냅샷이 창 안에 있으면 그 창으로는 확정하지 않는다(부분 실패 보호).
    """
    n = max(1, int(n))
    if len(window) < n + 1:
        return []
    recent = window[-n:]
    if any(s.get('error') for s in recent) or window[-(n + 1)].get('error'):
        return []
    base = _leaders(window[-(n + 1)])
    cur = window[-1]
    cur_idx = _index(cur)
    seen = set(already)
    out: list[dict[str, Any]] = []
    for code, before in base.items():
        def reliable_nonleader(snap: dict[str, Any]) -> bool:
            row = _index(snap).get(code)
            return row is None or (_score_complete(row) and row.get('grade', '') not in LEADER_GRADES)

        if all(reliable_nonleader(s) for s in recent):
            key = ('LEADER_DROP', code)
            if key in seen:
                continue
            seen.add(key)
            now = cur_idx.get(code)
            out.append(_event('LEADER_DROP', now or before, cur.get('ts'),
                              grade_from=before.get('grade', ''), grade_to=(now or {}).get('grade', ''),
                              confirmed_ticks=n))
    return out
