"""종가베팅 V2 안전망 테스트.

2026-08-06 장애: 데몬은 살아 있고 하트비트도 갱신되는데 14:50 슬롯이 실행되지
않았다. 단일 스레드 루프가 작업을 동기 실행하므로 앞선 작업이 길어지면 슬롯이
밀리고, 밀린 것을 되찾을 '놓친 스케줄 점검' 도 같은 루프에 있어 함께 멈춘다
(점검 간격 5분 -> 36분 -> 52분 정지). 워치독은 하트비트만 보므로 이를 장애로
판정하지 않는다.
"""
import importlib.util
import json
import os
from datetime import date

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'ensure_jongga_v2',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'scripts', 'ensure_jongga_v2.py'),
)
ensure = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ensure)


def _write(tmp_path, target, signals):
    path = tmp_path / f'jongga_v2_results_{target:%Y%m%d}.json'
    path.write_text(json.dumps({'date': str(target), 'signals': signals},
                               ensure_ascii=False), encoding='utf-8')
    return path


def test_existing_result_is_recognised(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    target = date(2026, 8, 6)
    _write(tmp_path, target, [{'grade': 'S'}, {'grade': 'A'}])

    assert ensure.existing_result(target) is not None


def test_missing_file_reports_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))

    assert ensure.existing_result(date(2026, 8, 6)) is None


def test_empty_signal_list_does_not_count_as_a_result(tmp_path, monkeypatch):
    """빈 껍데기 파일을 '있음' 으로 세면 안전망이 영원히 침묵한다."""
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    target = date(2026, 8, 6)
    _write(tmp_path, target, [])

    assert ensure.existing_result(target) is None


def test_corrupt_json_does_not_count_as_a_result(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    target = date(2026, 8, 6)
    (tmp_path / f'jongga_v2_results_{target:%Y%m%d}.json').write_text('{broken', encoding='utf-8')

    assert ensure.existing_result(target) is None


@pytest.mark.parametrize('day, trading', [
    (date(2026, 8, 8), False),   # 토
    (date(2026, 8, 9), False),   # 일
])
def test_weekends_are_never_trading_days(day, trading):
    assert ensure.is_trading_day(day) is trading


def test_trading_day_falls_back_to_true_when_the_checker_is_unavailable(monkeypatch):
    """판정기를 못 부를 때 거래일이 아니라고 단정하면 그날 V2 가 통째로 누락된다."""
    import builtins
    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == 'scheduler':
            raise ImportError('no scheduler')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', _blocked)

    assert ensure.is_trading_day(date(2026, 8, 6)) is True   # 목요일


def test_check_mode_signals_a_gap_with_a_nonzero_exit(tmp_path, monkeypatch, capsys):
    """--check 는 감시용이다. 누락이면 종료코드로 알려야 알림을 걸 수 있다."""
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: True)
    monkeypatch.setattr('sys.argv', ['x', '--check', '--date', '2026-08-06'])

    assert ensure.main() == 1


def test_check_mode_is_quiet_when_the_result_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: True)
    _write(tmp_path, date(2026, 8, 6), [{'grade': 'A'}])
    monkeypatch.setattr('sys.argv', ['x', '--check', '--date', '2026-08-06'])

    assert ensure.main() == 0


def test_non_trading_day_exits_without_running(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: False)
    monkeypatch.setattr('sys.argv', ['x', '--date', '2026-08-08'])

    assert ensure.main() == 0


def test_existing_result_short_circuits_before_the_engine(tmp_path, monkeypatch):
    """정상 동작한 날에는 비용이 0 이어야 한다 — 엔진을 부르면 안 된다."""
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: True)
    _write(tmp_path, date(2026, 8, 6), [{'grade': 'S'}])

    called = []
    monkeypatch.setattr(ensure.asyncio, 'run', lambda *a, **k: called.append(1))
    monkeypatch.setattr('sys.argv', ['x', '--date', '2026-08-06'])

    assert ensure.main() == 0
    assert called == []


def test_force_runs_even_when_a_result_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: True)
    _write(tmp_path, date(2026, 8, 6), [{'grade': 'S'}])

    called = []
    monkeypatch.setattr(ensure.asyncio, 'run', lambda *a, **k: called.append(1))
    monkeypatch.setattr('sys.argv', ['x', '--force', '--date', '2026-08-06'])

    ensure.main()
    assert called == [1]


def test_engine_finishing_without_an_artifact_is_a_failure(tmp_path, monkeypatch):
    """엔진이 조용히 아무것도 안 쓰고 끝나는 경우를 성공으로 보고하면 안 된다."""
    monkeypatch.setattr(ensure, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ensure, 'is_trading_day', lambda d: True)
    monkeypatch.setattr(ensure.asyncio, 'run', lambda *a, **k: None)
    monkeypatch.setattr('sys.argv', ['x', '--date', '2026-08-06'])

    assert ensure.main() == 1
