# -*- coding: utf-8 -*-
"""종목 판단 결과 일간 캐시 — 같은 종목을 하루에 여러 번 눌러도 재계산하지 않는다.

브리프는 7개 소스를 팬아웃해 모으고(실측 ~15초), 심층 분석은 LLM 토론까지 돌린다
(~2분, 유료). 같은 날 같은 종목을 다시 볼 때마다 이 비용을 다시 치를 이유가 없다.

다만 두 결과의 성격이 다르므로 만료 규칙을 나눈다.
    - deep  : 에이전트 토론 결과. 장중에 흔들릴 성질이 아니므로 그날 하루 통째로 재사용.
    - brief : 주도주 전이 같은 장중 실시간 근거를 포함한다. 장중에는 짧은 TTL 로만
              재사용하고, 장 마감 뒤에는 그날 하루 유지한다.

캐시는 절대 요청을 막지 않는다 — 어떤 실패도 '미스'로 흘러 정상 계산으로 이어진다.
"""
import sqlite3
from datetime import datetime

import pytest

from app.services.mirofish import decision_cache as dc


@pytest.fixture()
def cache_db(tmp_path, monkeypatch):
    monkeypatch.setattr(dc, 'DB_PATH', str(tmp_path / 'decision_cache.db'))
    return str(tmp_path / 'decision_cache.db')


def _at(text: str) -> datetime:
    """KST 기준 시각 헬퍼."""
    return datetime.fromisoformat(text)


CLOSED = _at('2026-08-28T18:30:00')      # 금요일 장 마감 후
OPEN = _at('2026-08-28T10:00:00')        # 금요일 장중
PAYLOAD = {'symbol': '005930', 'status': 'neutral', 'signals': []}


# ─── 기본 왕복 ──────────────────────────────────────────────

def test_miss_on_empty_cache(cache_db):
    assert dc.cache_get('brief', '005930', now=CLOSED) is None


def test_roundtrip_returns_the_stored_payload(cache_db):
    dc.cache_put('brief', '005930', PAYLOAD, now=CLOSED)
    hit = dc.cache_get('brief', '005930', now=CLOSED)
    assert hit['status'] == 'neutral'


def test_hit_is_marked_as_cached_with_a_timestamp(cache_db):
    """사용자가 캐시본을 보고 있다는 사실을 숨기지 않는다."""
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    hit = dc.cache_get('deep', '005930', now=CLOSED)
    assert hit['cached'] is True
    assert hit['cached_at']


def test_stored_payload_is_not_polluted_by_cache_marks(cache_db):
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    assert 'cached' not in PAYLOAD


def test_kinds_do_not_collide(cache_db):
    dc.cache_put('brief', '005930', {'k': 'brief'}, now=CLOSED)
    dc.cache_put('deep', '005930', {'k': 'deep'}, now=CLOSED)
    assert dc.cache_get('brief', '005930', now=CLOSED)['k'] == 'brief'
    assert dc.cache_get('deep', '005930', now=CLOSED)['k'] == 'deep'


def test_symbols_do_not_collide(cache_db):
    dc.cache_put('deep', '005930', {'k': 'a'}, now=CLOSED)
    dc.cache_put('deep', '000660', {'k': 'b'}, now=CLOSED)
    assert dc.cache_get('deep', '000660', now=CLOSED)['k'] == 'b'


def test_put_replaces_the_previous_entry(cache_db):
    dc.cache_put('deep', '005930', {'k': 'old'}, now=CLOSED)
    dc.cache_put('deep', '005930', {'k': 'new'}, now=CLOSED)
    assert dc.cache_get('deep', '005930', now=CLOSED)['k'] == 'new'


# ─── 하루 경계 ──────────────────────────────────────────────

def test_entry_from_a_previous_day_is_a_miss(cache_db):
    dc.cache_put('deep', '005930', PAYLOAD, now=_at('2026-08-27T18:00:00'))
    assert dc.cache_get('deep', '005930', now=CLOSED) is None


def test_deep_result_is_reused_all_day_including_market_hours(cache_db):
    """LLM 토론 결과는 장중이라고 다시 돌릴 이유가 없다."""
    dc.cache_put('deep', '005930', PAYLOAD, now=_at('2026-08-28T09:05:00'))
    assert dc.cache_get('deep', '005930', now=_at('2026-08-28T14:50:00')) is not None


# ─── 브리프의 장중 신선도 ───────────────────────────────────

def test_brief_expires_quickly_during_market_hours(cache_db):
    """장중 브리프에는 주도주 전이 같은 실시간 근거가 들어 있다."""
    dc.cache_put('brief', '005930', PAYLOAD, now=OPEN)
    later = _at('2026-08-28T10:20:00')  # MARKET_TTL 초과
    assert dc.cache_get('brief', '005930', now=later) is None


def test_brief_is_reused_within_the_market_ttl(cache_db):
    dc.cache_put('brief', '005930', PAYLOAD, now=OPEN)
    soon = _at('2026-08-28T10:01:00')
    assert dc.cache_get('brief', '005930', now=soon) is not None


def test_brief_is_kept_for_the_rest_of_the_day_after_close(cache_db):
    dc.cache_put('brief', '005930', PAYLOAD, now=_at('2026-08-28T16:00:00'))
    assert dc.cache_get('brief', '005930', now=_at('2026-08-28T23:00:00')) is not None


def test_weekend_is_never_treated_as_market_hours(cache_db):
    saturday = _at('2026-08-29T10:00:00')  # 2026-08-29 는 토요일
    dc.cache_put('brief', '005930', PAYLOAD, now=saturday)
    assert dc.cache_get('brief', '005930', now=_at('2026-08-29T14:00:00')) is not None


# ─── 무효화 ─────────────────────────────────────────────────

def test_clear_removes_one_symbol(cache_db):
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    dc.cache_put('deep', '000660', PAYLOAD, now=CLOSED)
    dc.cache_clear(symbol='005930')
    assert dc.cache_get('deep', '005930', now=CLOSED) is None
    assert dc.cache_get('deep', '000660', now=CLOSED) is not None


def test_clear_all_empties_the_cache(cache_db):
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    dc.cache_clear()
    assert dc.cache_get('deep', '005930', now=CLOSED) is None


# ─── 캐시는 요청을 막지 않는다 ──────────────────────────────

def test_corrupt_payload_is_a_miss_not_a_crash(cache_db):
    import sqlite3
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    con = sqlite3.connect(cache_db)
    con.execute("UPDATE decision_cache SET payload='{not json'")
    con.commit()
    con.close()
    assert dc.cache_get('deep', '005930', now=CLOSED) is None


def _break_connection(monkeypatch):
    """저장소 자체가 죽은 상황. 경로 트릭은 OS 마다 결과가 달라 쓰지 않는다."""
    def boom():
        raise sqlite3.OperationalError('disk gone')

    monkeypatch.setattr(dc, '_connect', boom)


def test_read_failure_returns_a_miss(cache_db, monkeypatch):
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    _break_connection(monkeypatch)
    assert dc.cache_get('deep', '005930', now=CLOSED) is None


def test_write_failure_never_raises(cache_db, monkeypatch):
    _break_connection(monkeypatch)
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)  # 예외 없이 통과해야 한다


def test_clear_failure_never_raises(cache_db, monkeypatch):
    _break_connection(monkeypatch)
    assert dc.cache_clear() == 0


def test_non_dict_payload_is_ignored(cache_db):
    dc.cache_put('deep', '005930', ['not', 'a', 'dict'], now=CLOSED)
    assert dc.cache_get('deep', '005930', now=CLOSED) is None


# ─── 킬스위치 ───────────────────────────────────────────────

def test_killswitch_disables_reads_and_writes(cache_db, monkeypatch):
    monkeypatch.setenv('DECISION_CACHE_DISABLED', '1')
    dc.cache_put('deep', '005930', PAYLOAD, now=CLOSED)
    assert dc.cache_get('deep', '005930', now=CLOSED) is None
