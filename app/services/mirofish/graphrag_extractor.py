"""GraphRAG: 비정형 텍스트 → 엔티티/관계 JSON.

Gemini structured output 으로 entity + relation 추출.
실패 시 rule-based fallback (한국어 키워드 매칭).
EKG 병합은 file-based (`data/admin_mirofish/ekg.json`).
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any

from app.utils.atomic_json import write_json_atomic

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
EKG_DIR = os.path.join(REPO_ROOT, 'data', 'admin_mirofish')
EKG_PATH = os.path.join(EKG_DIR, 'ekg.json')

_ekg_lock = threading.Lock()

# 비용 통제: 단일 호출당 토큰 cap, run 당 호출 횟수 cap
MAX_TEXT_LEN = 8000  # 8k chars per call
MAX_CALLS_PER_RUN = int(os.getenv('MIROFISH_GRAPHRAG_MAX_CALLS', '3'))


# ─── Public API ────────────────────────────────────────────

def extract_graph(text: str, *, use_llm: bool = True) -> dict[str, Any]:
    """텍스트에서 entities + relations 추출.

    Returns:
        {
            'entities': [{'id', 'type', 'name', 'description?'}],
            'relations': [{'source_id', 'target_id', 'relation_type',
                          'strength', 'evidence', 'inferred': bool}],
            'method': 'llm' | 'rule' | 'mixed',
            'extracted_at': iso8601,
        }
    """
    text = (text or '').strip()
    if not text:
        return _empty_graph('empty input')

    text = text[:MAX_TEXT_LEN]
    method = 'rule'
    entities: list[dict] = []
    relations: list[dict] = []

    if use_llm:
        try:
            llm_result = _extract_with_gemini(text)
            if llm_result and llm_result.get('entities'):
                entities = llm_result.get('entities', [])
                relations = llm_result.get('relations', [])
                method = 'llm'
        except Exception:
            method = 'rule'

    if not entities:
        # Rule-based fallback — 한국어/영어 키워드 사전
        entities, relations = _extract_with_rules(text)
        method = 'rule' if method != 'llm' else 'mixed'

    return {
        'entities': entities,
        'relations': relations,
        'method': method,
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'text_length': len(text),
    }


def merge_into_ekg(graph: dict[str, Any]) -> dict[str, Any]:
    """추출 그래프를 기존 EKG 와 병합. 중복 entity 는 type/name 기준 dedup.

    Returns merge stats: {'new_entities': n, 'new_relations': m, 'total_entities': ...}
    """
    os.makedirs(EKG_DIR, exist_ok=True)
    with _ekg_lock:
        ekg = _load_ekg()
        existing_keys = {(e.get('type'), e.get('name', '').lower())
                         for e in ekg.get('entities', [])}
        existing_relations = {_relation_key(r) for r in ekg.get('relations', [])}

        new_entities = 0
        for ent in graph.get('entities', []):
            key = (ent.get('type'), (ent.get('name') or '').lower())
            if key not in existing_keys and ent.get('name'):
                ekg.setdefault('entities', []).append(ent)
                existing_keys.add(key)
                new_entities += 1

        new_relations = 0
        for rel in graph.get('relations', []):
            rkey = _relation_key(rel)
            if rkey and rkey not in existing_relations:
                ekg.setdefault('relations', []).append(rel)
                existing_relations.add(rkey)
                new_relations += 1

        ekg['updated_at'] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(EKG_PATH, ekg, sort_keys=False)

    return {
        'new_entities': new_entities,
        'new_relations': new_relations,
        'total_entities': len(ekg.get('entities', [])),
        'total_relations': len(ekg.get('relations', [])),
    }


def search_causal_chain(start_entity_id: str, *, max_depth: int = 3) -> list[list[dict]]:
    """BFS — 시작 엔티티에서 max_depth 까지 causal 인과 chain 탐색.

    Returns chains as list of paths: [[edge1, edge2, ...], ...]
    """
    with _ekg_lock:
        ekg = _load_ekg()

    relations_by_source: dict[str, list[dict]] = {}
    for rel in ekg.get('relations', []):
        relations_by_source.setdefault(rel.get('source_id', ''), []).append(rel)

    paths: list[list[dict]] = []
    queue: list[tuple[str, list[dict]]] = [(start_entity_id, [])]
    visited: set[str] = {start_entity_id}

    while queue and len(paths) < 50:
        node, path = queue.pop(0)
        if len(path) >= max_depth:
            paths.append(path)
            continue
        edges = relations_by_source.get(node, [])
        if not edges:
            if path:
                paths.append(path)
            continue
        for edge in edges:
            tgt = edge.get('target_id')
            if not tgt or tgt in visited:
                continue
            visited.add(tgt)
            queue.append((tgt, path + [edge]))

    return paths


def get_ekg_stats() -> dict[str, Any]:
    with _ekg_lock:
        ekg = _load_ekg()
    return {
        'total_entities': len(ekg.get('entities', [])),
        'total_relations': len(ekg.get('relations', [])),
        'updated_at': ekg.get('updated_at'),
        'entity_types': sorted({e.get('type', 'unknown')
                                for e in ekg.get('entities', [])}),
    }


# ─── Gemini extraction ─────────────────────────────────────

_GEMINI_PROMPT = """당신은 금융 뉴스/문서에서 지식 그래프를 추출하는 전문가입니다.
입력 텍스트에서 다음을 JSON 으로 출력하세요:

{
  "entities": [
    {"id": "snake_case_id", "type": "company|sector|policy|event|person|asset|risk|metric", "name": "한글/영문 이름", "description": "1줄 설명"}
  ],
  "relations": [
    {"source_id": "...", "target_id": "...", "relation_type": "causes|impacts|owns|related_to|opposes|mentions",
     "strength": 0.0~1.0, "evidence": "근거 문구"}
  ]
}

규칙:
- entity id 는 lowercase + underscore (예: "samsung_electronics", "fed_rate")
- 같은 엔티티는 한 번만
- relation 은 추정이 아닌 텍스트 근거 있을 때만
- 최대 entities 20개, relations 30개

입력 텍스트:
"""


def _extract_with_gemini(text: str) -> dict[str, Any] | None:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return None
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError:
        return None
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=os.getenv('MIROFISH_GRAPHRAG_MODEL', 'gemini-2.5-flash'),
            contents=_GEMINI_PROMPT + text,
            config=genai_types.GenerateContentConfig(
                response_mime_type='application/json',
                temperature=0.2,
                max_output_tokens=8192,  # 4k → 8k (large entity/relation lists 처리)
            ),
        )
        raw = (response.text or '').strip()
        if not raw:
            import logging
            logging.getLogger(__name__).warning('[GraphRAG] Gemini returned empty text')
            return None

        # truncated JSON 복구 시도: 마지막 완전한 [ 또는 ] 까지만 사용
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            import logging
            logging.getLogger(__name__).warning(
                f'[GraphRAG] JSON decode failed (truncated?): {e}; attempting partial recovery'
            )
            data = _try_partial_json_recovery(raw)
            if not data:
                return None

        if not isinstance(data, dict):
            return None
        return {
            'entities': _validate_entities(data.get('entities', [])),
            'relations': _validate_relations(data.get('relations', [])),
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f'[GraphRAG] Gemini call failed: {type(e).__name__}: {e}')
        return None


def _try_partial_json_recovery(raw: str) -> dict | None:
    """truncated JSON 에서 entities 배열만이라도 살린다."""
    # entities 배열 추출 시도
    ent_match = re.search(r'"entities"\s*:\s*\[(.*?)\](?:\s*,|\s*\})', raw, re.DOTALL)
    rel_match = re.search(r'"relations"\s*:\s*\[(.*?)\](?:\s*,|\s*\})', raw, re.DOTALL)
    out: dict[str, list] = {'entities': [], 'relations': []}

    for kind, m in (('entities', ent_match), ('relations', rel_match)):
        if not m:
            continue
        body = m.group(1)
        # 가능한 JSON 객체 단위로 분리 (단순 휴리스틱)
        depth = 0
        buf = ''
        for ch in body:
            if ch == '{':
                if depth == 0:
                    buf = '{'
                else:
                    buf += ch
                depth += 1
            elif ch == '}':
                depth -= 1
                buf += ch
                if depth == 0 and buf.strip():
                    try:
                        out[kind].append(json.loads(buf))
                    except json.JSONDecodeError:
                        pass
                    buf = ''
            elif depth > 0:
                buf += ch
    if not out['entities'] and not out['relations']:
        return None
    return out


# ─── Rule-based fallback ───────────────────────────────────

# 도메인 사전 — 자주 등장하는 금융 엔티티
_DOMAIN_DICT = [
    # (regex, type, canonical_name)
    (r'삼성전자|Samsung Electronics?', 'company', '삼성전자'),
    (r'SK\s?하이닉스|SK Hynix', 'company', 'SK하이닉스'),
    (r'네이버|NAVER', 'company', '네이버'),
    (r'카카오|Kakao', 'company', '카카오'),
    (r'현대차|Hyundai Motor', 'company', '현대자동차'),
    (r'테슬라|Tesla', 'company', '테슬라'),
    (r'엔비디아|NVIDIA|Nvidia', 'company', '엔비디아'),
    (r'애플|Apple', 'company', '애플'),
    (r'마이크로소프트|Microsoft', 'company', '마이크로소프트'),
    (r'구글|Google|Alphabet', 'company', '구글'),
    (r'\bFed\b|연준|연방준비제도', 'policy', '연준'),
    (r'금리|interest rate', 'metric', '기준금리'),
    (r'환율|exchange rate', 'metric', '환율'),
    (r'KOSPI|코스피', 'asset', 'KOSPI'),
    (r'KOSDAQ|코스닥', 'asset', 'KOSDAQ'),
    (r'\bS&P\s?500\b|SPX', 'asset', 'S&P 500'),
    (r'NASDAQ|나스닥', 'asset', 'NASDAQ'),
    (r'반도체|semiconductor', 'sector', '반도체'),
    (r'AI|인공지능', 'sector', 'AI'),
    (r'배터리|battery|2차전지', 'sector', '배터리'),
    (r'바이오|biotech|제약', 'sector', '바이오'),
    (r'유가|oil price|crude', 'metric', '유가'),
    (r'인플레이션|inflation|CPI', 'metric', '인플레이션'),
    (r'금융위기|financial crisis|recession', 'risk', '경기침체'),
    (r'전쟁|war|conflict', 'risk', '지정학적 위험'),
]

# 인과 관계 키워드 — (pattern, relation_type, strength)
_CAUSAL_PATTERNS = [
    (r'(.{1,40})(?:때문에|로 인해|영향으로|결과)', 'causes', 0.7),
    (r'(.{1,40})(?:상승|증가|호조|개선).{0,30}(?:기대|전망)', 'impacts', 0.6),
    (r'(.{1,40})(?:하락|감소|악재|부진).{0,30}(?:우려|전망)', 'impacts', 0.6),
    (r'(.{1,40})(?:관련|연관)', 'related_to', 0.5),
]


def _extract_with_rules(text: str) -> tuple[list[dict], list[dict]]:
    """간단 사전 매칭 — entity 발견. relation 은 인접 entity 에 'related_to' 만 부여."""
    found: list[tuple[str, str, str]] = []  # (id, type, name)
    seen_ids: set[str] = set()
    for pattern, etype, canonical in _DOMAIN_DICT:
        if re.search(pattern, text, re.IGNORECASE):
            ent_id = canonical.lower().replace(' ', '_').replace('&', 'n')
            ent_id = re.sub(r'[^a-z0-9가-힣_]', '', ent_id)
            if ent_id in seen_ids:
                continue
            seen_ids.add(ent_id)
            found.append((ent_id, etype, canonical))

    entities = [
        {'id': eid, 'type': etype, 'name': name,
         'description': f'Extracted via rule-based pattern match'}
        for eid, etype, name in found
    ]

    # 텍스트 내 동시 출현하는 entity 쌍 → 약한 'related_to' relation
    relations: list[dict] = []
    for i in range(len(found)):
        for j in range(i + 1, min(i + 4, len(found))):
            relations.append({
                'source_id': found[i][0],
                'target_id': found[j][0],
                'relation_type': 'related_to',
                'strength': 0.4,
                'evidence': '동일 텍스트 내 동시 언급',
                'inferred': False,
            })
    return entities, relations


# ─── Helpers ──────────────────────────────────────────────

def _empty_graph(reason: str) -> dict[str, Any]:
    return {
        'entities': [],
        'relations': [],
        'method': 'none',
        'extracted_at': datetime.now(timezone.utc).isoformat(),
        'reason': reason,
    }


def _validate_entities(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:30]:
        if not isinstance(item, dict):
            continue
        eid = item.get('id') or ''
        if not eid:
            continue
        out.append({
            'id': str(eid),
            'type': str(item.get('type', 'unknown')),
            'name': str(item.get('name', eid)),
            'description': str(item.get('description', ''))[:200],
        })
    return out


def _validate_relations(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    valid_types = {'causes', 'impacts', 'owns', 'related_to', 'opposes', 'mentions'}
    out = []
    for item in raw[:50]:
        if not isinstance(item, dict):
            continue
        src = item.get('source_id')
        tgt = item.get('target_id')
        if not src or not tgt or src == tgt:
            continue
        rtype = item.get('relation_type', 'related_to')
        if rtype not in valid_types:
            rtype = 'related_to'
        try:
            strength = float(item.get('strength', 0.5))
            strength = max(0.0, min(1.0, strength))
        except (TypeError, ValueError):
            strength = 0.5
        out.append({
            'source_id': str(src),
            'target_id': str(tgt),
            'relation_type': rtype,
            'strength': strength,
            'evidence': str(item.get('evidence', ''))[:200],
            'inferred': True,
        })
    return out


def _relation_key(rel: dict) -> tuple | None:
    src = rel.get('source_id')
    tgt = rel.get('target_id')
    rtype = rel.get('relation_type')
    if not src or not tgt:
        return None
    return (src, tgt, rtype)


def _load_ekg() -> dict[str, Any]:
    if not os.path.isfile(EKG_PATH):
        return {'entities': [], 'relations': [], 'created_at': datetime.now(timezone.utc).isoformat()}
    try:
        with open(EKG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {'entities': [], 'relations': []}
        return data
    except (OSError, json.JSONDecodeError):
        return {'entities': [], 'relations': []}
