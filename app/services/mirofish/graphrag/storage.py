"""GraphRAG storage path 정의 + subsystem status 조회.

청사진 §11 Artifact 설계, §12 Phase A 완료 조건 반영.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

from app.utils.paths import BASE_DIR, DATA_DIR


# ── Storage paths (청사진 §11.3) ─────────────────────────────────────

GRAPHRAG_ROOT = os.path.join(DATA_DIR, 'admin_mirofish', 'graphrag')
ENTITIES_DB = os.path.join(GRAPHRAG_ROOT, 'entities.db')
ALIASES_JSON = os.path.join(GRAPHRAG_ROOT, 'aliases.json')
CHOSUNG_INDEX = os.path.join(GRAPHRAG_ROOT, 'chosung_index.json')
EDGES_DIR = os.path.join(GRAPHRAG_ROOT, 'edges')
EVENTS_DIR = os.path.join(GRAPHRAG_ROOT, 'events')
COMMUNITIES_DIR = os.path.join(GRAPHRAG_ROOT, 'communities')
RESEARCH_RUNS_DIR = os.path.join(GRAPHRAG_ROOT, 'research_runs')
EVAL_DIR = os.path.join(GRAPHRAG_ROOT, 'eval')
AUDIT_DIR = os.path.join(GRAPHRAG_ROOT, 'audit')


def ensure_dirs() -> None:
    """Storage 디렉토리 부재 시 생성. status 조회 / Phase B 적재 전 호출."""
    for path in (
        GRAPHRAG_ROOT,
        EDGES_DIR,
        EVENTS_DIR,
        COMMUNITIES_DIR,
        RESEARCH_RUNS_DIR,
        EVAL_DIR,
        AUDIT_DIR,
    ):
        os.makedirs(path, exist_ok=True)


def get_storage_paths() -> dict[str, Any]:
    """현재 저장소 경로와 존재 여부 + 크기를 반환."""
    paths = {
        'root': GRAPHRAG_ROOT,
        'entities_db': ENTITIES_DB,
        'aliases_json': ALIASES_JSON,
        'chosung_index': CHOSUNG_INDEX,
        'edges_dir': EDGES_DIR,
        'events_dir': EVENTS_DIR,
        'communities_dir': COMMUNITIES_DIR,
        'research_runs_dir': RESEARCH_RUNS_DIR,
        'eval_dir': EVAL_DIR,
        'audit_dir': AUDIT_DIR,
    }
    inventory: dict[str, dict[str, Any]] = {}
    for key, path in paths.items():
        exists = os.path.exists(path)
        is_dir = os.path.isdir(path) if exists else False
        size_bytes = 0
        if exists and not is_dir:
            try:
                size_bytes = os.path.getsize(path)
            except OSError:
                size_bytes = 0
        inventory[key] = {
            'path': path,
            'exists': exists,
            'is_dir': is_dir,
            'size_bytes': size_bytes,
        }
    return inventory


# ── Feature flags (청사진 §12 Phase A 완료 조건) ──────────────────────

def _env_bool(name: str, default: str = '0') -> bool:
    val = os.getenv(name, default).strip().lower()
    return val in ('1', 'true', 'yes', 'on')


def get_feature_flags() -> dict[str, Any]:
    """GraphRAG 운영 토글 + 의존 자산 환경변수 상태."""
    return {
        'shadow_mode': _env_bool('GRAPHRAG_SHADOW_MODE', '1'),
        'devil_advocate_enabled': _env_bool('DEVIL_ADVOCATE_ENABLED', '1'),
        'multi_ai_include_grok': _env_bool('MULTI_AI_INCLUDE_GROK', '1'),
        'gdelt_enabled': _env_bool('GDELT_ENABLED', '0'),
        'cache_ttl_sec': int(os.getenv('GRAPHRAG_CACHE_TTL', '3600') or 3600),
        'vector_backend': os.getenv('GRAPHRAG_VECTOR_BACKEND', 'chroma'),
        'embedding_model': os.getenv('GRAPHRAG_EMBEDDING_MODEL', 'BAAI/bge-m3'),
        # 필수 API 키 존재 여부만 노출 (실제 값 노출 X)
        'keys_present': {
            'dart': bool(os.getenv('DART_API_KEY')),
            'gemini': bool(os.getenv('GEMINI_API_KEY')),
            'openai': bool(os.getenv('OPENAI_API_KEY')),
            'grok': bool(os.getenv('XAI_API_KEY')),
            'anthropic': bool(os.getenv('ANTHROPIC_API_KEY')),
        },
    }


# ── Subsystem status (Phase A 핵심) ─────────────────────────────────

def _entities_db_stats() -> dict[str, Any]:
    """entities.db 의 노드 카운트. DB 가 아직 없으면 0."""
    if not os.path.exists(ENTITIES_DB):
        return {'present': False, 'entity_count': 0, 'alias_count': 0, 'external_id_count': 0}
    try:
        conn = sqlite3.connect(f"file:{ENTITIES_DB}?mode=ro", uri=True, timeout=2.0)
        try:
            stats: dict[str, Any] = {'present': True}
            for table, key in (
                ('entities', 'entity_count'),
                ('entity_aliases', 'alias_count'),
                ('entity_external_ids', 'external_id_count'),
            ):
                try:
                    cur = conn.execute(f"SELECT COUNT(*) FROM {table}")
                    row = cur.fetchone()
                    stats[key] = int(row[0]) if row else 0
                except sqlite3.Error:
                    stats[key] = 0
            return stats
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return {'present': True, 'error': str(exc), 'entity_count': 0}


def _overall_state(inventory: dict[str, Any], db_stats: dict[str, Any]) -> str:
    """ready / degraded / not_initialized 판정.

    - root 디렉토리 없음 → not_initialized
    - root 있으나 entities.db 없음 → degraded (Phase A 완료, Phase B 미시작)
    - entities.db 있고 entity_count > 0 → ready
    - entities.db 있으나 entity_count == 0 → degraded (DB 만 만들고 데이터 미적재)
    """
    root_info = inventory.get('root', {})
    if not root_info.get('exists'):
        return 'not_initialized'
    if not db_stats.get('present'):
        return 'degraded'
    if int(db_stats.get('entity_count') or 0) <= 0:
        return 'degraded'
    return 'ready'


def get_subsystem_status() -> dict[str, Any]:
    """GraphRAG subsystem 의 통합 상태.

    엔드포인트 ``GET /api/admin/mirofish/graphrag/status`` 가 직접 반환.
    """
    ensure_dirs()  # 첫 호출 시 디렉토리 보장 (idempotent)
    inventory = get_storage_paths()
    db_stats = _entities_db_stats()
    flags = get_feature_flags()
    state = _overall_state(inventory, db_stats)

    b_resolver_done = bool(db_stats.get('entity_count', 0))
    return {
        'service': 'mirofish-graphrag',
        'state': state,
        'ready': state == 'ready',
        'phase': {
            'A_skeleton': True,
            'B_resolver': b_resolver_done,
            'C_workflow_enrichment': False,
            'D_ui': False,
            'E_mcp': False,
            'F_eval': False,
        },
        'endpoints_live': {
            'status': True,
            'entities_resolve': b_resolver_done,
            'entities_get': b_resolver_done,
        },
        'storage': inventory,
        'entities': db_stats,
        'flags': flags,
        'base_dir': BASE_DIR,
        'data_dir': DATA_DIR,
        'asof': time.strftime('%Y-%m-%dT%H:%M:%S+09:00', time.localtime()),
    }
