"""V2 pre-flight 게이트 + 중복 실행 가드 테스트.

2026-08-05 장애: 유휴 7.7초짜리 임포트 검증이 중복 실행 부하에서 60초를 넘겨
4회 시도 전부 차단됐고, 하루치 종가베팅 결과가 생성되지 않았다. 수동 실행에서
엔진은 118초 만에 19개 시그널을 정상 생성했다 — 코드는 멀쩡했다.
"""
import threading

import pytest

scheduler = pytest.importorskip('scheduler')


def test_preflight_reports_ok_when_imports_succeed(monkeypatch):
    monkeypatch.setattr(scheduler, 'run_command', lambda *a, **k: True)

    assert scheduler._run_v2_preflight(timeout=30) == 'ok'


def test_quick_failure_is_an_import_error_not_a_timeout(monkeypatch):
    """임포트 오류는 예산을 다 쓰지 않고 몇 초 만에 끝난다."""
    monkeypatch.setattr(scheduler, 'run_command', lambda *a, **k: False)

    assert scheduler._run_v2_preflight(timeout=30) == 'import_error'


def test_exhausting_the_budget_is_reported_as_a_timeout(monkeypatch):
    """예산을 다 쓰고 실패했으면 부하 증상이지 코드 버그가 아니다."""
    def _slow(*args, **kwargs):
        # run_command 가 timeout 만큼 붙잡고 있다가 False 를 돌려준 상황
        base = scheduler.time.time()
        monkeypatch.setattr(scheduler.time, 'time', lambda: base + 30)
        return False

    monkeypatch.setattr(scheduler, 'run_command', _slow)

    assert scheduler._run_v2_preflight(timeout=30) == 'timeout'


def test_preflight_budget_is_larger_than_the_measured_import_cost():
    """실측 유휴 임포트 7.7초. 예산이 그보다 한 자릿수 배수면 부하에서 또 막힌다."""
    assert scheduler.PREFLIGHT_TIMEOUT_SEC >= 120


def test_timeout_does_not_block_the_engine(monkeypatch):
    """타임아웃으로 엔진을 막으면 일시적 부하가 하루치 결과를 날린다.

    진짜 임포트 오류라면 엔진 실행에서도 몇 초 만에 죽으므로 잃는 것이 없다.
    """
    calls = []
    monkeypatch.setattr(scheduler, '_kr_market_task_allowed', lambda *a, **k: True)
    monkeypatch.setattr(scheduler, '_run_v2_preflight', lambda *a, **k: 'timeout')
    monkeypatch.setattr(scheduler, 'send_telegram', lambda *a, **k: True)
    monkeypatch.setattr(scheduler, 'run_command',
                        lambda cmd, desc, **k: calls.append(desc) or False)

    scheduler.update_jongga_v2()

    assert any('엔진' in d for d in calls), f'엔진이 실행되지 않았다: {calls}'


def test_import_error_does_block_the_engine(monkeypatch):
    """반대로 진짜 코드 버그는 막아야 한다 — 이 검사의 존재 이유다."""
    calls = []
    monkeypatch.setattr(scheduler, '_kr_market_task_allowed', lambda *a, **k: True)
    monkeypatch.setattr(scheduler, '_run_v2_preflight', lambda *a, **k: 'import_error')
    monkeypatch.setattr(scheduler, 'send_telegram', lambda *a, **k: True)
    monkeypatch.setattr(scheduler, 'run_command',
                        lambda cmd, desc, **k: calls.append(desc) or False)

    assert scheduler.update_jongga_v2() is False
    assert calls == []


def test_concurrent_invocation_is_skipped_not_run_twice(monkeypatch):
    """복구 트리거와 정규 스케줄이 겹치면 전 종목 수집이 두 번 돈다."""
    monkeypatch.setattr(scheduler, '_kr_market_task_allowed', lambda *a, **k: True)

    entered = threading.Event()
    release = threading.Event()
    runs = []

    def _body():
        runs.append(1)
        entered.set()
        release.wait(timeout=5)
        return True

    monkeypatch.setattr(scheduler, '_update_jongga_v2_locked', _body)

    worker = threading.Thread(target=scheduler.update_jongga_v2, daemon=True)
    worker.start()
    assert entered.wait(timeout=5), '첫 실행이 시작되지 않았다'

    assert scheduler.update_jongga_v2() is True   # 두 번째는 건너뛴다
    release.set()
    worker.join(timeout=5)

    assert len(runs) == 1


def test_lock_is_released_even_when_the_body_raises(monkeypatch):
    """예외로 락이 남으면 그 다음 날부터 영원히 스킵된다."""
    monkeypatch.setattr(scheduler, '_kr_market_task_allowed', lambda *a, **k: True)

    def _boom():
        raise RuntimeError('boom')

    monkeypatch.setattr(scheduler, '_update_jongga_v2_locked', _boom)

    with pytest.raises(RuntimeError):
        scheduler.update_jongga_v2()

    assert scheduler._JONGGA_V2_LOCK.acquire(blocking=False)
    scheduler._JONGGA_V2_LOCK.release()
