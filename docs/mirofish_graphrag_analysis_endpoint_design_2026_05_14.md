# MarketFlow GraphRAG 엔드포인트 설계 보고서

**문서 버전:** 1.0
**작성일:** 2026-05-14
**기반 자료:** `deep-research-report.md` (AI 에이전트 GraphRAG Analysis)
**대상 시스템:** MarketFlow (KR/US/Crypto 종합 분석 플랫폼)
**작성 목적:** 보고서가 제시한 GraphRAG 권장 구조를 MarketFlow 의 기존 자산 위에 안전하게 얹기 위한 단계별 엔드포인트 명세

---

## 0. Executive Summary

MarketFlow 의 다음 단계 차별화 포인트는 "그래프를 도입했다"가 아니라 **"시간·관계·숫자·근거를 한 시스템에서 감사 가능하게 연결한다"** 이다. 이 보고서는 deep-research-report 가 결론으로 제시한 하이브리드 GraphRAG (벡터 + 그래프 + 코드 툴) 패턴을 MarketFlow 의 기존 자산 (DART 수집기, Multi-AI Consensus, jongga_v2 archive, MiroFish MCP, ticker map) 위에 6 Phase / 11개 엔드포인트로 분해해 점진 도입하는 계획을 제시한다.

핵심 결정:
- Blueprint 신규 모듈 `app/routes/graphrag.py` (URL prefix `/api/graphrag/`)
- Phase 0–1 (ID resolver + hybrid search) 부터 2주 내 PoC
- DART 공시는 신규 "EVENT 노드 + impacts 엣지" 로 그래프화
- 모든 응답에 `asof`, `evidence[]`, `audit` 필드 표준화
- 운영 도입은 `GRAPHRAG_SHADOW_MODE=1` 환경변수로 shadow mode 거쳐서 진행

---

## 1. 배경: deep-research-report 핵심 결론

### 1.1 한 줄 요약

> 주식분석 에이전트에서 GraphRAG 는 "그래프를 쓰느냐"의 문제가 아니라, "시간·관계·숫자·근거를 한 시스템에서 얼마나 감사 가능하게 연결하느냐"의 문제다.

### 1.2 핵심 주장 5가지

1. **GraphRAG = 단일 기술이 아닌 설계군** — Microsoft 계열 (코퍼스 → 엔터티 그래프 + 커뮤니티 요약), KG-guided (RoG, KG²RAG), Graph-native QA (G-Retriever, GNN-RAG) 세 부류가 공존
2. **그래프가 이기는 영역 vs 지는 영역이 분명함** — 멀티홉/전사 요약/관계 구조 질의에서 유효, 짧고 단순한 사실 질의/작은 코퍼스에서는 vanilla RAG 가 더 나음
3. **금융 도메인 결정적 증거** — HybridRAG (벡터+KG) 가 earnings call 에서 VectorRAG·GraphRAG 단독을 모두 이김, FinAgent-RAG/TRACE 가 시간 규칙 + evidence grounding 결합으로 감사 가능한 예측 입증
4. **LLM 4-레이어 분리 권고** — 라우팅 / retrieval orchestration / 숫자·표·시계열 툴 / 답변 생성을 분리
5. **파인튜닝은 1순위 아님** — 도메인 임베딩 + 프롬프트 튜닝 + ID 정규화 + 시간축 스키마 + 평가 체계 먼저

### 1.3 보고서가 강조한 6대 함정

| 함정 | MarketFlow 노출도 | 대응 |
|---|---|---|
| 엔터티 정규화 실패 → 모든 후속 단계 오염 | 중간 (현재 ticker_to_yahoo_map.csv 와 DART corp_code 가 분리됨) | Phase 0 ID resolver 로 1차 흡수 |
| GraphRAG 효용은 조건부 (작은 코퍼스에서 vanilla RAG 우위) | 낮음 (KR + US + Crypto 데이터 다수) | Phase 5 평가에서 vanilla RAG vs Hybrid A/B |
| 비용·지연 | 높음 (이미 LLM 비용 부담 호소) | path pruning + community summary 캐싱 + asof 기반 사전 필터 |
| 시간성·인과성 | 매우 높음 (시장 데이터는 시점 민감) | `valid_from/to`, `asof` 모든 응답 표준 필드 |
| 다국어·한국어 금융 | 매우 높음 (KR 시장 비중 큼) | 한국어 추출 프롬프트 + 용어 사전 분리 모듈 |
| 평가의 미완성 | 중간 (jongga_v2 outcome 추적은 있음) | jongga_v2 archive 를 Phase 5 평가셋으로 전환 |

---

## 2. MarketFlow 현재 상태 진단

### 2.1 보고서 권고 ↔ MarketFlow 자산 매핑

| 보고서 권고 | MarketFlow 현재 자산 | 갭 | 우선순위 |
|---|---|---|---|
| Hybrid retrieval (vector + graph + tool) | jongga_v2 + alpha_scanner + LLM analyzer | 벡터 인덱스 명시적 없음 | 매우 높음 |
| 식별자 정규화 (ticker–FIGI–CIK–corp_code) | `ticker_to_yahoo_map.csv` + DART corp_code | 통합 매핑 레이어 부재 | 매우 높음 |
| 한국 공시 (OpenDART) | `engine/dart_collector.py` 존재 | 그래프화 안 됨, 텍스트로만 사용 | 매우 높음 |
| 미국 SEC EDGAR | 미연동 | 신규 작업 | 낮음 (Phase 4+) |
| 뉴스 이벤트 (GDELT) | Perplexity/Gemini 뉴스 분석만 | 이벤트 그래프 부재 | 중간 |
| Temporal property graph | 없음 | 신규 | 매우 높음 |
| LLM 4-레이어 분리 | MiroFish AdminEndpointsPage 5단계 UI 존재 | UI 는 있는데 그래프 백엔드 미완 | 높음 |
| 평가 자동화 (FinanceBench/FinQA) | jongga_v2 결과 archive 만 있음 | 정량 평가 인프라 없음 | 중간 |
| 규제 (audit, citation, as-of) | telegram 로그 + workflow archive | 본격 audit chain 없음 | 높음 |

### 2.2 결정적 발견

MarketFlow `AdminEndpointsPage` 의 5단계 (`TARGET → BRAIN → GRAPHRAG → DEBATE → VERDICT`) UI 가 **이미 보고서가 권하는 구조와 같다.** 즉 비전은 맞춰져 있고, **백엔드 그래프 인덱싱·시간 그래프·하이브리드 검색이 실제로는 구현되어 있지 않다**는 게 갭이다. 본 설계는 이 갭을 메우는 백엔드를 설계한다.

---

## 3. 설계 원칙

| # | 원칙 | 근거 (보고서 챕터) |
|---|---|---|
| 1 | **Hybrid first** — 모든 retrieval 응답은 vector + graph + (옵션) tool 3채널 통합 | §HybridRAG, §주식분석 에이전트 설계 권장안 |
| 2 | **As-of 필수** — 모든 시계열 응답에 `asof` 파라미터 + `valid_from/to` 메타 | §한계 (시간성·인과성) |
| 3 | **Evidence chain 표준화** — `evidence[]: {doc_id, source_type, url, ts, confidence}` 통일 | §그래프 스키마, §TRACE |
| 4 | **Pro-gated** — 기존 `_enforce_pro_access` 적용. URL prefix `/api/graphrag/` | MarketFlow §_GATED_PREFIXES |
| 5 | **MCP 통합** — 각 엔드포인트는 `mcp__mirofish__graphrag_*` 도구로도 노출 | MarketFlow §MiroFish MCP |
| 6 | **Shadow mode** — `GRAPHRAG_SHADOW_MODE=1` 환경변수 | §운영·통제 |
| 7 | **한국어 1급 시민** — 한글 종목명, 약어, 자회사 표기 다양성 흡수 모듈 분리 | §한계 (다국어) |

---

## 4. 엔드포인트 명세

총 11개 엔드포인트, 6 Phase 로 나눈다. 각 Phase 는 독립 배포 가능.

### 4.1 Phase 0 — 기반 인프라 (1주차 PoC)

#### 4.1.1 `GET /api/graphrag/entity/resolve`

엔터티 ID 정규화. 한글 종목명·티커·corp_code·FIGI 어떤 입력이든 표준 entity_id 반환.

**Request:**
```
GET /api/graphrag/entity/resolve?q=삼성전자&hint_market=KR&limit=5
```

**Response:**
```json
{
  "query": "삼성전자",
  "matches": [{
    "entity_id": "kr:005930",
    "type": "company",
    "names": {"ko": "삼성전자", "en": "Samsung Electronics"},
    "ids": {
      "ticker_kr": "005930",
      "corp_code": "00126380",
      "figi": "BBG000BCY2S8",
      "isin": "KR7005930003"
    },
    "sector": {"id": "sec:kr:semi", "name_ko": "반도체"},
    "exchange": "KOSPI",
    "country": "KR",
    "confidence": 0.97
  }],
  "asof": "2026-05-14T00:00:00+09:00"
}
```

**소스 통합:**
- 1차: `data/ticker_to_yahoo_map.csv` (기존)
- 2차: `data/dart_corp_codes.json` (기존, DART 호재공시 수집기에서 사용)
- 3차 (선택): OpenFIGI API (cross-listing 처리, MarketFlow 미연동)

**MarketFlow 컨벤션:**
- `data/graphrag/entities.db` (SQLite) 에 entity_id PK + alias index
- 캐시 TTL 30일 (corp_code 변경 드뭄)

#### 4.1.2 `GET /api/graphrag/entity/<entity_id>`

엔터티 메타 + 그래프 연결 통계.

**Response (핵심 필드):**
```json
{
  "entity_id": "kr:005930",
  "meta": { /* resolve 응답과 동일 */ },
  "degree": {"in": 142, "out": 67},
  "edges_by_type": {
    "belongs_to_sector": 1,
    "competes_with": 8,
    "supplies_to": 23,
    "mentioned_in_doc": 89,
    "impacted_by_event": 21
  },
  "recent_events": [
    {"event_id": "evt:dart:00126380:20260413:1", "ts": "2026-04-13", "type": "disclosure"}
  ],
  "asof": "2026-05-14T00:00:00+09:00"
}
```

### 4.2 Phase 1 — 그래프 검색 (1-2주차)

#### 4.2.1 `POST /api/graphrag/query/route`

질문 분류기. 보고서 §local/global/event/numeric 4분류를 1차 라우터로 구현.

**Request:**
```json
{"query": "HBM 수혜로 어느 장비주가 영향 받나?"}
```

**Response:**
```json
{
  "route": "event_propagation",
  "subroutes": ["graph_traversal", "vector_supplement"],
  "hints": {
    "primary_entities": ["sec:kr:semi"],
    "horizon_days": 30,
    "requires_numeric": false
  },
  "confidence": 0.81
}
```

라우터 구현은 가벼운 규칙 기반 (LLM 호출 없이 키워드 + 패턴) 으로 시작, Phase 5 에서 학습 모델로 업그레이드 가능.

#### 4.2.2 `POST /api/graphrag/search`

하이브리드 검색 메인. vector + graph traversal + (옵션) tool 결과 통합.

**Request:**
```json
{
  "query": "HBM 수혜로 어느 장비주가 영향 받나?",
  "asof": "2026-05-14",
  "hints": {"ticker": null, "sector": "sec:kr:semi"},
  "limit": 12,
  "include": ["vector", "graph"]
}
```

**Response:**
```json
{
  "route": "event_propagation",
  "evidence": [
    {
      "type": "vector",
      "doc_id": "dart:00126380:20260413:abc",
      "snippet": "당사는 HBM3E 양산을 위해 …",
      "ts": "2026-04-13",
      "score": 0.84
    },
    {
      "type": "graph_path",
      "path": [
        {"entity_id": "kr:005930", "name": "삼성전자"},
        {"edge": "supplies_to", "valid_from": "2024-01-01"},
        {"entity_id": "kr:012450", "name": "한화에어로스페이스"}
      ],
      "confidence": 0.82
    }
  ],
  "answer_draft": null,
  "asof": "2026-05-14T00:00:00+09:00",
  "audit": {
    "router_route": "event_propagation",
    "retrieval_ms": 124,
    "tool_calls": []
  }
}
```

`answer_draft` 는 의도적으로 null. 생성은 별도 `/research` 엔드포인트에서.

#### 4.2.3 `GET /api/graphrag/subgraph/<entity_id>`

k-hop 서브그래프 (시간 필터).

**Request:**
```
GET /api/graphrag/subgraph/kr:005930?hops=2&asof=2026-05-14&edge_types=supplies_to,competes_with&max_nodes=50
```

**Response:**
```json
{
  "root": "kr:005930",
  "asof": "2026-05-14",
  "nodes": [{"entity_id": "kr:005930", "type": "company", ...}],
  "edges": [{"src": "kr:005930", "dst": "kr:012450", "type": "supplies_to", "valid_from": "2024-01-01"}],
  "truncated": false
}
```

### 4.3 Phase 2 — 시간 그래프 이벤트 (2-3주차)

#### 4.3.1 `GET /api/graphrag/events`

종목별 이벤트 timeline.

**Request:**
```
GET /api/graphrag/events?ticker=005935&from=2026-04-01&to=2026-05-14&types=disclosure,earnings,news
```

**Response:**
```json
{
  "ticker": "005935",
  "asof": "2026-05-14",
  "events": [{
    "event_id": "evt:dart:00126380:20260413:1",
    "type": "disclosure",
    "subtype": "자기주식취득",
    "ts": "2026-04-13T15:30:00+09:00",
    "horizon_days": 7,
    "confidence": 0.95,
    "evidence_doc_ids": ["dart:00126380:20260413:abc"],
    "impact_edges": [
      {"target": "kr:005935", "weight": 0.6, "valid_from": "2026-04-13", "valid_to": "2026-04-20"}
    ]
  }]
}
```

#### 4.3.2 `POST /api/graphrag/event/ingest`

신규 이벤트 등록 (운영용, admin 권한). DART collector, news collector 가 호출.

**Request:**
```json
{
  "type": "disclosure",
  "subtype": "자기주식취득",
  "ts": "2026-04-13T15:30:00+09:00",
  "source_doc_id": "dart:00126380:20260413:abc",
  "impact_targets": [{"entity_id": "kr:005930", "weight": 0.6, "horizon_days": 7}],
  "extracted_text": "...",
  "confidence": 0.95
}
```

**Response:**
```json
{"event_id": "evt:dart:00126380:20260413:1", "stored_at": "2026-05-14T03:14:15+09:00"}
```

### 4.4 Phase 3 — 전역 요약 (3-4주차)

보고서 §Microsoft GraphRAG global search 패턴 적용. 야간 배치로 community detection + LLM 요약 생성.

#### 4.4.1 `GET /api/graphrag/community/sectors`

섹터 커뮤니티 리스트 + 최신 narrative 요약.

**Response:**
```json
{
  "asof": "2026-05-14",
  "communities": [{
    "id": "comm:semi:hbm",
    "name": "HBM 공급망",
    "node_count": 23,
    "narrative_summary": "엔비디아 GTC 2026 발표 이후 …",
    "narrative_generated_at": "2026-05-14T04:00:00+09:00",
    "top_entities": ["kr:005930", "kr:000660", "kr:012450"]
  }]
}
```

#### 4.4.2 `GET /api/graphrag/community/<id>/summary`

특정 커뮤니티의 시점별 narrative 메모.

**Request:**
```
GET /api/graphrag/community/comm:semi:hbm/summary?asof=2026-05-14&horizon_days=30
```

**Response:**
```json
{
  "community_id": "comm:semi:hbm",
  "asof": "2026-05-14",
  "horizon_days": 30,
  "summary": {
    "headline": "HBM4 채택 가속화로 장비주 CAPEX 확대 신호",
    "key_events": ["evt:news:gtc2026:keynote", "evt:dart:00126380:20260413:1"],
    "key_metrics": [{"name": "장비주_CAPEX_YoY", "value": 0.18, "trend": "increasing"}],
    "rationale_chain": [
      "GTC 2026 HBM4 채택 발표",
      "삼성/SK 가 1차 공급사 확정",
      "장비주 CAPEX +18% YoY",
      "수혜 후보 → 한미반도체, 원익IPS …"
    ],
    "generated_by": {"model": "multi-ai-consensus", "consensus_count": 2}
  }
}
```

**구현 노트:**
- 야간 배치 작업: scheduler.py 에 `_run_graphrag_community_summary()` 추가
- LLM 호출: 기존 `engine/llm_analyzer.MultiAIConsensusScreener` 재활용 (Gemini + GPT-4o 합의)
- 결과 캐시: `data/graphrag/communities/{community_id}/{asof}.json`

### 4.5 Phase 4 — Agentic Research (TRACE 스타일) (4-6주차)

보고서가 강조한 **LLM 4-레이어 분리** 를 백엔드로 구현.

#### 4.5.1 `POST /api/graphrag/research`

자연어 질문 → 라우터 → retrieval → 툴 → 생성 4-레이어 파이프라인 → 리서치 메모 + evidence chain.

**Request:**
```json
{
  "question": "엔비디아 GTC 2026 발표가 한국 반도체 장비주에 미칠 영향은?",
  "asof": "2026-05-14",
  "horizon_days": 30,
  "require_citations": true,
  "shadow_mode": false
}
```

**Response (요약):**
```json
{
  "run_id": "rsh_2026051401",
  "status": "completed",
  "verdict": {
    "label": "BUY_BIAS",
    "confidence": 0.62,
    "rationale_chain": [
      {"step": 1, "type": "event", "summary": "GTC 2026 HBM4 채택 발표", "evidence_ids": ["news:gtc:..."]},
      {"step": 2, "type": "supply_chain", "summary": "삼성/SK 가 HBM4 1차 공급", "evidence_ids": ["dart:..."]},
      {"step": 3, "type": "metric", "summary": "장비주 CAPEX +18% YoY", "evidence_ids": ["xbrl:..."]},
      {"step": 4, "type": "conclusion", "candidates": [
        {"entity_id": "kr:042700", "rationale": "한미반도체 — HBM 검사 장비 …"},
        {"entity_id": "kr:240810", "rationale": "원익IPS — 차세대 증착 장비 …"}
      ]}
    ]
  },
  "audit": {
    "asof": "2026-05-14T00:00:00+09:00",
    "model_versions": {
      "router": "rule-based-v1",
      "retrieval": "hybrid-v1",
      "generator": "gpt-4o-2024-11"
    },
    "tool_calls": [{"name": "metric_lookup", "params": {...}, "duration_ms": 87}],
    "shadow_mode": false,
    "disclaimer": "본 응답은 투자 자문이 아닙니다. 정보 제공 목적에 한합니다."
  }
}
```

#### 4.5.2 `GET /api/graphrag/research/<run_id>`

저장된 리서치 결과 조회 + audit trail.

### 4.6 Phase 5 — 평가 / 관측 (운영 단계)

#### 4.6.1 `POST /api/graphrag/eval/run`

평가 harness. jongga_v2 archive + FinanceBench/FinQA 스타일 셋.

**Request:**
```json
{
  "benchmark": "jongga_v2_replay",
  "from": "2026-04-01",
  "to": "2026-05-01",
  "configs": [
    {"name": "vector_only", "include": ["vector"]},
    {"name": "hybrid", "include": ["vector", "graph"]},
    {"name": "hybrid_with_tools", "include": ["vector", "graph", "tools"]}
  ]
}
```

**Response (요약):**
```json
{
  "run_id": "eval_2026051401",
  "metrics": {
    "vector_only": {"hit_rate": 0.42, "ic": 0.07, "citation_precision": 0.81},
    "hybrid": {"hit_rate": 0.51, "ic": 0.12, "citation_precision": 0.88},
    "hybrid_with_tools": {"hit_rate": 0.54, "ic": 0.14, "citation_precision": 0.91}
  }
}
```

#### 4.6.2 `GET /api/graphrag/metrics/graph`

그래프 품질 메트릭.

**Response:**
```json
{
  "asof": "2026-05-14",
  "entity_count": 12450,
  "edge_count": 89732,
  "stale_edge_ratio": 0.08,
  "entity_dedup_accuracy": 0.96,
  "edges_by_type": {"belongs_to_sector": 12450, "supplies_to": 3210, ...},
  "community_count": 187,
  "last_full_index": "2026-05-14T04:00:00+09:00"
}
```

---

## 5. 데이터 모델

### 5.1 노드 타입

| 타입 | 식별 | 핵심 속성 |
|---|---|---|
| COMPANY | `entity_id = "kr:005930"` 형식 | ticker_kr, corp_code, figi, isin, sector_id, country, exchange |
| SECTOR | `sec:kr:semi` | name_ko, name_en, mics_code, gics_code |
| EVENT | `evt:dart:00126380:20260413:1` | type, subtype, ts, horizon_days, confidence, source_count |
| PERSON | `per:hong_gildong_005930` | name, role, company_id, valid_from/to |
| DOCUMENT | `dart:00126380:20260413:abc` | source_type, ts, url, content_hash, language |
| METRIC_SNAPSHOT | `met:kr:005930:2026Q1:revenue` | entity_id, period_end, metric, value, unit, restated_flag |
| PRICE_BAR | `bar:kr:005930:2026-05-14` | ohlcv |

### 5.2 엣지 타입 (모두 `valid_from`, `valid_to`, `observed_at`, `evidence_doc_ids`, `confidence` 보유)

| 엣지 | 방향 | 비고 |
|---|---|---|
| `belongs_to_sector` | COMPANY → SECTOR | 1-many |
| `supplies_to` | COMPANY → COMPANY | 시간 변동 큼 |
| `competes_with` | COMPANY ↔ COMPANY | 대칭, valid_to 가급적 NULL (장기) |
| `impacts` | EVENT → COMPANY/SECTOR | weight (0-1), horizon_days |
| `mentioned_in` | DOCUMENT → COMPANY/PERSON/EVENT | sentiment 포함 |
| `exec_of` | PERSON → COMPANY | role 포함 |
| `has_metric` | COMPANY → METRIC_SNAPSHOT | period_end 가 PK |
| `observed_for` | PRICE_BAR → COMPANY | 1-many |

### 5.3 저장소 (3단계 점진 도입)

| 단계 | 저장소 | 규모 한도 | 비고 |
|---|---|---|---|
| Phase 0–1 | SQLite + JSONL | < 50k 노드 | `data/graphrag/entities.db`, `data/graphrag/edges/*.jsonl` |
| Phase 2–3 | NetworkX in-memory + SQLite 영속화 | < 100k 노드 | 매 호출마다 load, lazy hydrate |
| Phase 4+ | Neo4j 또는 KuzuDB | > 100k | Bolt protocol, Cypher query |

전환 시점은 Phase 3 community summary 가 안정화되고 `metrics/graph` 의 `entity_count` 가 50k 를 넘는 시점.

---

## 6. 기존 MarketFlow 자산과의 통합

| 기존 자산 | GraphRAG 활용 | Phase |
|---|---|---|
| `engine/dart_collector.py` | DART 신규 공시 → `POST /event/ingest` → EVENT 노드 + impacts 엣지 자동 생성 | 2 |
| `engine/llm_analyzer.MultiAIConsensusScreener` | community summary 생성기 (Gemini + GPT-4o 합의로 narrative 신뢰도 강화) | 3 |
| `data/jongga_v2_results_*.json` archive | `/eval/run` 의 evaluation 셋 — 과거 시그널 → forward return → IC/hit-rate 계산 | 5 |
| `ticker_to_yahoo_map.csv` + `data/dart_corp_codes.json` | `/entity/resolve` 1차 매핑 소스 | 0 |
| `app/services/mirofish/` MCP 도구 | `mcp__mirofish__graphrag_resolve`, `graphrag_search`, `graphrag_research` 신규 노출 | 1, 4 |
| `app/routes/wave.py` 의 W 패턴 시그널 | EVENT 노드 타입 중 `subtype="pattern_signal"` 로 흡수 | 2 |
| AdminEndpointsPage 5단계 UI (`TARGET → BRAIN → GRAPHRAG → DEBATE → VERDICT`) | `/research` 응답을 그대로 채우는 백엔드가 됨 | 4 |
| `engine/scorer.py` 17점 만점 | `/research` 의 `rationale_chain` step 중 numeric step 에서 호출 | 4 |
| `engine/jubjub_analyzer.py` | `/events?types=jubjub` 로 줍줍 시그널을 EVENT 화 | 2 |
| 텔레그램 알림 시스템 | `/research` 응답을 채널 전송용 포맷으로 변환 (disclaimer 자동 삽입) | 4 |

---

## 7. Blueprint 디렉토리 구조

```
app/
  routes/
    graphrag.py                   # Blueprint, URL prefix /api/graphrag

  services/
    graphrag/
      __init__.py
      resolver.py                 # Phase 0: entity ID 정규화
      retriever.py                # Phase 1: hybrid 검색
      router.py                   # Phase 1: query 분류기 (rule-based v1)
      temporal.py                 # Phase 2: event timeline + ingest
      community.py                # Phase 3: community detection + summary
      research.py                 # Phase 4: agentic pipeline (4-layer)
      eval.py                     # Phase 5: benchmark harness
      schema.py                   # 노드/엣지 dataclass
      storage.py                  # SQLite/JSONL/Neo4j 추상화 계층
      korean.py                   # 한국어 종목명/약어 정규화

data/
  graphrag/
    entities.db                   # SQLite (Phase 0+)
    edges/                        # JSONL 파일 by type (Phase 1+)
    events/                       # JSONL by yyyy-mm-dd (Phase 2+)
    communities/                  # community summary 캐시 (Phase 3+)
    research_runs/                # /research 결과 archive (Phase 4+)
    audit/                        # YYYYMMDD.jsonl audit log (Phase 4+)
    eval/                         # 평가 결과 (Phase 5+)
```

---

## 8. 보안·규제·감사 (FSC 2025 가이드라인안 대응)

### 8.1 모든 응답 표준 필드

- `asof` — 응답 기준 시점 (ISO 8601 KST)
- `evidence[]` — 출처 배열 (보고서 §evidence chain 표준)
- `audit` — `model_versions`, `tool_calls`, `shadow_mode`, `disclaimer`

### 8.2 `/research` 엔드포인트 추가 요구사항

- **disclaimer 자동 삽입** (응답 + 텔레그램 전송 본문 양쪽): "본 응답은 투자 자문이 아닙니다. 정보 제공 목적에 한합니다."
- **citation 누락 시 응답 거부** — `require_citations=true` 이고 evidence_ids 가 비면 422 반환
- **as-of stale 검사** — `asof` 가 오늘보다 7일 이상 과거면 경고 플래그

### 8.3 Audit log

- 위치: `data/graphrag/audit/YYYYMMDD.jsonl`
- 항목: request_id, user_id, endpoint, query, route, model_versions, evidence_ids, response_hash, duration_ms
- 보존: 1년 (FSC 가이드라인 권고)

### 8.4 Shadow mode

- 환경변수 `GRAPHRAG_SHADOW_MODE=1` 시:
  - `/research` 응답은 기존 시스템 답변을 그대로 반환
  - GraphRAG 파이프라인은 백그라운드 실행 후 audit log 에만 비교 결과 기록
- 1-2주 shadow mode 후 정상 모드 전환

---

## 9. 권장 시작 순서 (Roadmap)

| 주차 | 마일스톤 | 검증 지표 |
|---|---|---|
| 1주차 | `/entity/resolve` 단일 엔드포인트 + SQLite | 한글 종목명 입력 시 정확 entity_id 반환률 ≥ 95% (jongga_v2 최근 100종목 대상) |
| 2주차 | `/search` Phase 1 (vector + 1-hop graph) | jongga_v2 최근 1개월 시그널 100개에 대한 "왜 선정?" 자동 질문 답변 quality 측정 |
| 3주차 | DART 공시 → `/event/ingest` ETL + `/events` | 최근 1주일 DART 공시 100% 적재 + 종목별 timeline 조회 가능 |
| 4주차 | `/subgraph` 시간 필터 + 1-hop 확장 시각화 (AdminEndpointsPage) | UI 에서 종목 클릭 시 1-hop 서브그래프 표시 |
| 5–6주차 | `/community/sectors` 야간 배치 + Multi-AI 합의 narrative | 7개 주요 섹터 community summary 자동 갱신 (매일 04:00 KST) |
| 7–8주차 | `/research` 4-레이어 파이프라인 + shadow mode | shadow mode 1주일 운영 후 기존 시스템 답변과 evidence chain 일치율 측정 |
| 9–10주차 | `/eval/run` benchmark + `/metrics/graph` | vector_only vs hybrid 비교 — IC/hit_rate 상승 확인 |
| 11주차+ | shadow mode 해제, MiroFish MCP 도구 노출, AdminEndpointsPage 정식 통합 | 사용자 수동 검증 |

---

## 10. 비용·성능 추정

보고서 §비용·지연시간 한계를 반영한 추정.

| 항목 | Phase 0–1 | Phase 3 (community) | Phase 4 (research) |
|---|---|---|---|
| LLM 호출 | 미사용 (rule-based router) | 야간 배치 1회 / 섹터 / 일 ≈ 7 호출 | 사용자 요청당 평균 3 호출 |
| 응답 시간 (p95) | < 200ms | < 50ms (캐시 hit) | 5-15s |
| 저장소 | < 500MB | < 2GB | < 10GB |
| 메모리 RSS 추가 | < 200MB | < 500MB | < 1GB |
| 월 추정 비용 (LLM API) | $0 | ~$5 | ~$20-50 (호출량 의존) |

`/research` 는 가장 비싸기 때문에:
- 캐시 TTL 1시간 (동일 질문 + 동일 asof)
- Pro 등급별 호출 한도 (예: Pro 50/일, Ultra Pro 200/일)
- Telegram 자동 호출은 비활성 (수동 트리거만)

---

## 11. 알려진 한계와 향후 과제

| # | 한계 | 완화 방안 | 향후 |
|---|---|---|---|
| 1 | 엔터티 정규화 한국어 약어 (예: "삼전" → "삼성전자") | `korean.py` 모듈에 alias dict + fuzzy match | LLM 기반 NER 도입 검토 |
| 2 | DART corp_code 만으로는 SPAC, 자회사 합병 시점 변경 추적 어려움 | `valid_from/to` 모든 엣지 강제 | 보조 데이터 소스 (FinanceData Reader) 검토 |
| 3 | 시간 그래프의 "현재 유효한 supplies_to" 판단 | `valid_to IS NULL OR valid_to >= asof` 조건 표준 | event-driven 관계 갱신 |
| 4 | community detection 의 sector 경계 (예: 반도체 ↔ 디스플레이 중첩) | overlapping community 허용 (한 노드가 여러 community 소속) | hierarchical community |
| 5 | `/research` rationale_chain 의 hallucination | 각 step 의 `evidence_ids` 가 비면 step 자동 폐기 | self-consistency check |
| 6 | 평가셋의 정답 라벨 부재 | jongga_v2 forward return 을 proxy label 로 사용 | 수동 라벨 일부 보완 |

---

## 12. 결정 필요 사항

다음 결정이 진행 전 필요하다.

1. **저장소 1차 선택** — SQLite + JSONL 로 시작 (권장) vs 초기부터 Neo4j 도입
2. **벡터 검색 엔진** — Chroma (로컬, 무료) vs Qdrant (운영 강화) vs 단순 embedding + numpy (PoC)
3. **임베딩 모델** — 한국어 금융 도메인 적응 모델 선택 (BAAI/bge-m3, jhgan/ko-sroberta-multitask, OpenAI text-embedding-3-large)
4. **OpenFIGI 연동 우선순위** — Phase 0 포함 vs Phase 4 미국 자산 추가 시점에 연동
5. **Cloudflare Pages 의 GraphRAG 페이지** — 신규 페이지 `/dashboard/graphrag` 신설 vs AdminEndpointsPage 확장

---

## 13. 참고

- `deep-research-report.md` (AI 에이전트 GraphRAG Analysis, 2026-05-14)
- `CLAUDE.md` §1 환경 설정, §2 프로젝트 아키텍처, §4 데이터 흐름
- `INFRASTRUCTURE.md` §2.1 8080 포트 정책 (Spring Boot 미사용)
- `app/routes/admin_mirofish.py` (MiroFish endpoint 패턴)
- `engine/llm_analyzer.py` (Multi-AI Consensus 재활용 대상)
- `engine/dart_collector.py` (DART 공시 수집기, EVENT 노드 ETL 소스)

---

## 부록 A. 응답 표준 스키마 (모든 엔드포인트 공통)

```typescript
interface GraphRAGResponse<T> {
  data: T;                               // 엔드포인트별 페이로드
  asof: string;                          // ISO 8601 KST
  evidence?: Evidence[];                  // 출처 배열 (검색/리서치 응답)
  audit?: AuditMeta;                     // /research 응답 필수
  warnings?: Warning[];                   // stale data, low confidence 등
}

interface Evidence {
  type: 'vector' | 'graph_path' | 'tool' | 'document';
  doc_id?: string;
  path?: GraphPathStep[];
  snippet?: string;
  ts?: string;
  url?: string;
  confidence: number;     // 0-1
  source_type?: 'dart' | 'sec' | 'news' | 'price' | 'xbrl';
}

interface AuditMeta {
  request_id: string;
  asof: string;
  model_versions: Record<string, string>;
  tool_calls: ToolCall[];
  shadow_mode: boolean;
  disclaimer: string;
}
```

## 부록 B. MCP 도구 노출 (MiroFish 통합)

각 엔드포인트는 `app/services/mirofish/mcp_server.py` 에 다음 도구로 등록.

| 엔드포인트 | MCP 도구명 |
|---|---|
| `/entity/resolve` | `mcp__mirofish__graphrag_resolve_entity` |
| `/entity/<id>` | `mcp__mirofish__graphrag_get_entity` |
| `/search` | `mcp__mirofish__graphrag_search` |
| `/subgraph/<id>` | `mcp__mirofish__graphrag_get_subgraph` |
| `/events` | `mcp__mirofish__graphrag_list_events` |
| `/community/sectors` | `mcp__mirofish__graphrag_list_communities` |
| `/community/<id>/summary` | `mcp__mirofish__graphrag_community_summary` |
| `/research` | `mcp__mirofish__graphrag_research` |
| `/research/<run_id>` | `mcp__mirofish__graphrag_get_research` |

Claude Code 에서 자연어로 호출 가능:
> "삼성전자 HBM 관련 1-hop 서브그래프 보여줘" → `graphrag_resolve_entity("삼성전자")` → `graphrag_get_subgraph("kr:005930", hops=1)`

---

**문서 끝.**
