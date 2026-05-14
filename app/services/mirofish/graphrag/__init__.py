"""MiroFish GraphRAG analysis services.

청사진 docs/mirofish_graphrag_analysis_endpoint_implementation_blueprint_2026_05_14.md
의 Phase A–F 를 단계적으로 구현하는 패키지.

운영 경계:
- 모든 신규 GraphRAG 기능은 admin 전용 (`/api/admin/mirofish/graphrag/*`).
- 기존 `app/services/mirofish/graphrag_extractor.py` (텍스트 → 그래프 추출, EKG 병합)
  와는 다른 모듈이다. 그쪽은 `extract_graph`, `merge_into_ekg` 등 "쓰기" 중심.
  이 패키지는 "조회/검색/리서치" 중심.
- Alpha first: 범용 GraphRAG 가 아니라 수익 후보 검출 (Top 3) 의 근거 엔진.
"""

from app.services.mirofish.graphrag.storage import (
    get_storage_paths,
    get_feature_flags,
    get_subsystem_status,
)
from app.services.mirofish.graphrag.resolver import (
    resolve as resolve_entity,
    get_entity,
    populate_from_sources,
    yahoo_to_entity_id,
    entity_id_to_kr_ticker,
)
from app.services.mirofish.graphrag.eval import (
    run_jongga_v2_replay,
    get_eval_history,
)

__all__ = [
    'get_storage_paths',
    'get_feature_flags',
    'get_subsystem_status',
    'resolve_entity',
    'get_entity',
    'populate_from_sources',
    'yahoo_to_entity_id',
    'entity_id_to_kr_ticker',
    'run_jongga_v2_replay',
    'get_eval_history',
]
