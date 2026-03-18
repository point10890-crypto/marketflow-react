# app/utils/file_lock.py
"""파일 동시 접근 보호 유틸리티

scheduler.py와 signal_tracker.py가 동시에 CSV/JSON을 읽고 쓸 때
데이터 손상을 방지한다.

사용법:
    from app.utils.file_lock import safe_write, safe_read

    with safe_write('data/signals_log.csv') as path:
        df.to_csv(path, ...)

    with safe_read('data/signals_log.csv') as path:
        df = pd.read_csv(path)
"""
from filelock import FileLock, Timeout
from contextlib import contextmanager
import logging

logger = logging.getLogger(__name__)


@contextmanager
def safe_write(filepath: str, timeout: int = 30):
    """파일 쓰기 보호 (배타적 잠금)

    Args:
        filepath: 보호할 파일 경로
        timeout: 잠금 대기 최대 시간(초). 초과 시 Timeout 예외 발생
    """
    lock = FileLock(filepath + '.lock', timeout=timeout)
    try:
        with lock:
            yield filepath
    except Timeout:
        logger.error(f"파일 잠금 타임아웃 ({timeout}초): {filepath}")
        raise


@contextmanager
def safe_read(filepath: str, timeout: int = 10):
    """파일 읽기 보호 (배타적 잠금)

    Args:
        filepath: 보호할 파일 경로
        timeout: 잠금 대기 최대 시간(초). 초과 시 Timeout 예외 발생
    """
    lock = FileLock(filepath + '.lock', timeout=timeout)
    try:
        with lock:
            yield filepath
    except Timeout:
        logger.error(f"파일 잠금 타임아웃 ({timeout}초): {filepath}")
        raise
