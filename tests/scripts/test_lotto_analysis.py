"""lotto_analysis 단위 테스트."""
import logging
from unittest.mock import MagicMock


def test_logger_used_for_errors(caplog, clean_env, monkeypatch):
    """run_lotto_analysis_post 에서 예외 발생 시 traceback 이 logger 로 기록되어야 함.

    회귀 보호: 과거 print() 만 사용해서 traceback 이 사라졌던 결함 ①.
    """
    # load_history 가 raise 하도록 강제
    import lotto_analysis
    # Task 3 의 idempotency guard 가 추가된 후에도 정상 흐름 진입하도록 mock
    # (raising=False — Task 1 시점에는 함수 미정의일 수 있음)
    monkeypatch.setattr(lotto_analysis, '_has_today_lotto_post', lambda: False, raising=False)
    monkeypatch.setattr(lotto_analysis, 'load_history',
                        MagicMock(side_effect=RuntimeError("forced test failure")))

    with caplog.at_level(logging.ERROR, logger='lotto_analysis'):
        result = lotto_analysis.run_lotto_analysis_post(dry_run=False)

    assert result is False, "예외 시 False 반환 유지"

    # traceback 이 logger 로 기록되었는지 검증
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1, "ERROR 레벨 로그가 최소 1건 있어야 함"

    has_traceback = any(
        r.exc_info is not None or 'forced test failure' in r.getMessage()
        for r in error_records
    )
    assert has_traceback, "logger.exception 또는 logger.error(exc_info=True) 사용 필요"
