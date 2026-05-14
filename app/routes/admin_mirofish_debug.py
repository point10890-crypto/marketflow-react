"""Admin-only Flask process introspection (메모리 누수 진단 전용).

URL prefix: ``/api/admin/mirofish/_debug``

이 라우트는 운영 진단용. 누수 원인 특정 후 제거하거나 GRAPHRAG_DEBUG_ENABLED 환경변수
뒤로 숨길 수 있음. 모든 응답은 admin only.
"""
from __future__ import annotations

import gc
import os
import sys
import time
from typing import Any

from flask import Blueprint, jsonify, request

from app.auth.decorators import admin_required


admin_mirofish_debug_bp = Blueprint('admin_mirofish_debug', __name__)


def _process_info() -> dict[str, Any]:
    """psutil 기반 process 정보. psutil 없으면 stdlib 폴백."""
    out: dict[str, Any] = {'pid': os.getpid()}
    try:
        import psutil
        p = psutil.Process(os.getpid())
        mem = p.memory_info()
        out.update({
            'rss_mb': round(mem.rss / 1024 / 1024, 1),
            'vms_mb': round(mem.vms / 1024 / 1024, 1),
            'cpu_total_sec': round(p.cpu_times().user + p.cpu_times().system, 1),
            'threads': p.num_threads(),
            'create_time': p.create_time(),
            'uptime_sec': round(time.time() - p.create_time(), 1),
            'open_files_count': len(p.open_files()),
            'connections_count': len(p.connections(kind='inet')),
        })
    except ImportError:
        # psutil 없는 환경 폴백 — resource (POSIX) 또는 ctypes(Windows)
        try:
            import resource
            ru = resource.getrusage(resource.RUSAGE_SELF)
            out['rss_kb_max'] = ru.ru_maxrss
        except ImportError:
            try:
                # Windows: GetProcessMemoryInfo via ctypes
                import ctypes
                from ctypes.wintypes import DWORD, HANDLE
                class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                    _fields_ = [('cb', DWORD), ('PageFaultCount', DWORD),
                                ('PeakWorkingSetSize', ctypes.c_size_t),
                                ('WorkingSetSize', ctypes.c_size_t),
                                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                                ('PagefileUsage', ctypes.c_size_t),
                                ('PeakPagefileUsage', ctypes.c_size_t)]
                counters = PROCESS_MEMORY_COUNTERS()
                counters.cb = ctypes.sizeof(counters)
                ctypes.windll.psapi.GetProcessMemoryInfo(
                    ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
                )
                out['rss_mb'] = round(counters.WorkingSetSize / 1024 / 1024, 1)
                out['peak_rss_mb'] = round(counters.PeakWorkingSetSize / 1024 / 1024, 1)
            except Exception:
                out['rss_unavailable'] = True
    except Exception as exc:
        out['process_error'] = str(exc)
    return out


def _cache_inventory() -> dict[str, Any]:
    """주요 메모리 캐시들의 크기 + 메타데이터 조회.

    누수 의심 후보의 dict 길이 / 적재 시각 / mtime 을 노출한다.
    """
    inv: dict[str, Any] = {}

    # 1) price_history (alpha_scanner._load_price_history_cached) — 가장 큰 후보
    try:
        from app.services.mirofish.alpha_scanner import (
            _PRICE_HISTORY_CACHE,
            _PRICE_HISTORY_CACHE_TTL,
        )
        data = _PRICE_HISTORY_CACHE.get('data')
        if data is not None:
            total_rows = sum(len(v) for v in data.values()) if isinstance(data, dict) else 0
            inv['price_history'] = {
                'present': True,
                'symbol_count': len(data) if isinstance(data, dict) else 0,
                'total_rows': total_rows,
                'cached_at_iso': time.strftime(
                    '%Y-%m-%dT%H:%M:%S+09:00',
                    time.localtime(_PRICE_HISTORY_CACHE.get('ts', 0)),
                ) if _PRICE_HISTORY_CACHE.get('ts') else None,
                'age_sec': round(time.time() - _PRICE_HISTORY_CACHE.get('ts', 0), 1) if _PRICE_HISTORY_CACHE.get('ts') else None,
                'mtime': _PRICE_HISTORY_CACHE.get('mtime'),
                'ttl_sec': _PRICE_HISTORY_CACHE_TTL,
            }
        else:
            inv['price_history'] = {'present': False}
    except Exception as exc:
        inv['price_history'] = {'error': str(exc)}

    # 2) wave screener cache
    try:
        from app.routes.wave import _screener_cache, _CACHE_TTL as WAVE_TTL
        inv['wave_screener'] = {
            'has_data': 'data' in _screener_cache,
            'ts': _screener_cache.get('ts'),
            'ttl_sec': WAVE_TTL,
        }
    except Exception as exc:
        inv['wave_screener'] = {'error': str(exc)}

    # 3) halted cache (jubjub)
    try:
        from engine.jubjub_analyzer import _HALTED_CACHE, _HALTED_CACHE_TTL_SEC
        inv['halted'] = {
            'entries': len(_HALTED_CACHE),
            'ttl_sec': _HALTED_CACHE_TTL_SEC,
        }
    except Exception as exc:
        inv['halted'] = {'error': str(exc)}

    # 4) preview cache (us market)
    try:
        from app.routes.us_market import _preview_cache, _CACHE_TTL as US_TTL
        inv['us_preview'] = {
            'entries': len(_preview_cache),
            'ttl_sec': US_TTL,
        }
    except Exception as exc:
        inv['us_preview'] = {'error': str(exc)}

    return inv


def _gc_stats() -> dict[str, Any]:
    """Garbage collector 통계."""
    try:
        return {
            'collections': gc.get_count(),
            'thresholds': gc.get_threshold(),
            'objects_tracked': len(gc.get_objects()),
            'garbage': len(gc.garbage),
        }
    except Exception as exc:
        return {'error': str(exc)}


def _tracemalloc_top(n: int = 15) -> Any:
    """tracemalloc 활성화된 경우 top N allocation."""
    try:
        import tracemalloc
        if not tracemalloc.is_tracing():
            return {'enabled': False, 'hint': 'set GRAPHRAG_TRACEMALLOC=1 and restart'}
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics('lineno')[:n]
        out = []
        for s in stats:
            frame = s.traceback[0] if s.traceback else None
            out.append({
                'file': frame.filename if frame else '?',
                'line': frame.lineno if frame else 0,
                'size_mb': round(s.size / 1024 / 1024, 2),
                'count': s.count,
            })
        return {'enabled': True, 'top': out}
    except Exception as exc:
        return {'error': str(exc)}


@admin_mirofish_debug_bp.route('/memory-lite', methods=['GET'])
@admin_required
def debug_memory_lite():
    """경량 메모리 진단 — gc.get_objects() 미사용 (큰 메모리에서 timeout 회피).

    process info + cache inventory + tracemalloc top 만 반환.
    누수가 가속 중일 때 빠르게 호출 가능.
    """
    response: dict[str, Any] = {
        'process': _process_info(),
        'caches': _cache_inventory(),
        'tracemalloc': _tracemalloc_top(20),
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }
    return jsonify(response), 200


@admin_mirofish_debug_bp.route('/memory', methods=['GET'])
@admin_required
def debug_memory():
    """Flask 프로세스 메모리 + 캐시 + GC 통계.

    Query: ?tracemalloc=1 (적용된 경우 top allocations 포함)
    """
    include_tm = request.args.get('tracemalloc', '1') != '0'
    response: dict[str, Any] = {
        'process': _process_info(),
        'caches': _cache_inventory(),
        'gc': _gc_stats(),
        'python_version': sys.version.split()[0],
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }
    if include_tm:
        response['tracemalloc'] = _tracemalloc_top(15)
    return jsonify(response), 200


@admin_mirofish_debug_bp.route('/gc-collect', methods=['POST'])
@admin_required
def debug_gc_collect():
    """수동 GC 실행 (응급 메모리 회수).

    Returns: 회수 전후 RSS, 회수된 객체 수.
    """
    try:
        import psutil
        p = psutil.Process(os.getpid())
        rss_before = p.memory_info().rss
    except Exception:
        rss_before = 0
    collected = gc.collect()
    try:
        rss_after = psutil.Process(os.getpid()).memory_info().rss
    except Exception:
        rss_after = 0
    return jsonify({
        'collected_objects': collected,
        'rss_before_mb': round(rss_before / 1024 / 1024, 1) if rss_before else None,
        'rss_after_mb': round(rss_after / 1024 / 1024, 1) if rss_after else None,
        'freed_mb': round((rss_before - rss_after) / 1024 / 1024, 1) if rss_before and rss_after else None,
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }), 200
