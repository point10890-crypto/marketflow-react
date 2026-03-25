"""
안전한 타입 변환 유틸리티 — NaN, None, Inf 처리
"""
import json
import math
import logging

logger = logging.getLogger(__name__)


def safe_float(val, default=0.0):
    """None, NaN, Inf, 문자열을 안전하게 float으로 변환"""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """None, NaN, 문자열을 안전하게 int로 변환"""
    if val is None:
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_str(val, default=''):
    """None, NaN을 안전하게 문자열로 변환"""
    if val is None:
        return default
    try:
        s = str(val)
        if s.lower() == 'nan':
            return default
        return s
    except Exception:
        return default


def load_json_file(path):
    """JSON 파일 안전 로드 — 실패 시 None 반환"""
    import os
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.debug("JSON 로드 실패 %s: %s", path, e)
        return None
