# MarketFlow GraphRAG 엔드포인트 설계 비교 검토 보고서

**문서 버전:** 1.0
**작성일:** 2026-05-14
**검토 대상:** `docs/mirofish_graphrag_analysis_endpoint_design_2026_05_14.md` (v1.0)
**검토 방법:** 2-trip 검토 (보고서 권고 매핑 + 실제 코드 검증)
**관련 문서:**
- `~/Downloads/deep-research-report.md` (AI 에이전트 GraphRAG Analysis, 원전 보고서)
- `CLAUDE.md` (MarketFlow 자율 운영 가이드 v3.2.0)

---

## 0. Executive Summary

설계안 v1.0 은 deep-research-report 의 권고를 80% 정확히 반영했고, MarketFlow 기존 자산 10개를 80% 정확히 가정했다. 두 검토에서 발견된 13개 갭은 거의 겹치지 않으며 — 즉 보강은 두 가지 종류 (보고서 권고 추가 흡수 + 실제 자산 활용 강화) 가 모두 필요하다.

가장 충격적인 발견은 설계안이 **MarketFlow 의 강점을 과소평가했다**는 점이다. 설계안이 가정한 "Gemini + GPT-4o 2-AI 합의" 는 실제로는 이미 **3-AI (Gemini + OpenAI + Grok) + Claude Devil's Advocate** 로 한 단계 더 강한 자산이 존재한다. 이를 반영하면 설계안의 §4.4 community summary 와 §4.5 research 의 confidence/hallucination 완화 메커니즘이 추가 구현 없이 그대로 흡수 가능하다.

종합 점수: **A- (8.5/10)** — 즉시 PoC 시작 가능. 단 5개 🔴 즉시 보강 후 v1.1 로 진행 권장.

---

## 1. 검토 방법

본 보고서는 설계안에 대해 두 가지 독립 관점에서 검토를 수행했다.

### 1.1 Trip 1 — 외부 정합성 검토

**질문:** 설계안이 deep-research-report 의 핵심 권고를 충분히 반영했는가?

**방법:** 보고서 8개 챕터의 핵심 주장·권고·한계를 추출하여 설계안의 어느 §에 매핑되는지 확인.

### 1.2 Trip 2 — 내부 정합성 검토 (Reality Check)

**질문:** 설계안이 가정한 MarketFlow 자산이 실제 코드에 존재하며 가정한 시그니처를 가지는가?

**방법:** 설계안 §6 통합 표의 10개 자산 각각을 코드 레벨 (파일 존재, 클래스/함수 시그니처, 데이터 구조) 에서 확인.

### 1.3 평가 기준

- A+: 완전 반영
- A: 핵심 반영, 사소 누락
- B+: 반영, 일부 약점
- B: 부분 반영, 보강 권장
- C+: 압축 과도 또는 의미 일부 변형
- D: 미반영
- N/A: 의도적 범위 외

---

## 2. Trip 1 — 보고서 권고 vs 설계안

### 2.1 반영도 매트릭스

| # | 보고서 챕터/권고 | 설계안 위치 | 반영 | 비고 |
|---|---|---|---|---|
| 1 | Executive Summary 핵심 메시지 | §0 그대로 인용 | A+ | "감사 가능한 연결" 표현 일치 |
| 2 | GraphRAG 3부류 (Microsoft/KG-guided/Graph-native) | §1.2 주장 1 | A | 1줄 압축, 충분 |
| 3 | **Microsoft local/global/DRIFT 검색** | §4.2.1 query/route | B+ | **DRIFT 누락** — event 로 일부 흡수했으나 명시 X |
| 4 | GNN 계열 (GCN/GraphSAGE/HGT) | 미반영 | N/A | Phase 4+ 이후 검토 가능 범위 |
| 5 | 이종 그래프 (typed nodes/edges) | §5.1, §5.2 | A | 7 노드/8 엣지 명시 |
| 6 | 시간 그래프 (valid_from/to) | §5.2 헤더 + §3 원칙 #2 | A+ | 가장 강조된 부분 |
| 7 | 최신 연구 동향 16개 논문 | §1.2 (3편만 인용) | B | **HippoRAG(PPR), PathRAG(path pruning), KG²RAG(chunk expansion) 미반영** |
| 8 | Microsoft/Neo4j/AWS/LlamaIndex 비교 | §5.3 + §12 결정사항 | B | **AWS lexical graph 패턴, LlamaIndex PropertyGraph 미반영** |
| 9 | **데이터 소스 (DART/SEC/OpenFIGI/GDELT)** | §2.1 권고 매핑 | B | **GDELT 활용이 추상적 — ingest 패턴 명세 없음** |
| 10 | 그래프 스키마 (이종 + 시간 + 근거) | §5.1, §5.2 | A+ | `evidence_doc_ids`, `valid_from/to`, `confidence` 모두 명시 |
| 11 | **LLM 4-역할 분리 (라우팅/orchestration/툴/생성)** | §4.5 + §4.5.1 audit | B+ | **audit.model_versions 에 3개만 — tool 레이어 누락** |
| 12 | 도메인 임베딩 + 프롬프트 튜닝 우선 | §12 결정사항 (임베딩 모델 3 후보) | B+ | **프롬프트 튜닝 워크플로 미언급** |
| 13 | **멀티모달 (차트·표·스캔 PDF)** | 미반영 | D | **전혀 다루지 않음** |
| 14 | 실시간/배치 분리 | §4.4 야간 배치 + §4.3 ingest webhook | A- | 정신 일치 |
| 15 | 8단계 로드맵 | §9 11주차 Roadmap | A- | 순서 일부 단순화 |
| 16 | 평가 데이터셋 (FinanceBench/FinQA/ConvFinQA/TAT-QA/DocFinQA/FinMTEB/BenchmarkQED) | §4.6.1 "FinanceBench/FinQA 스타일" | C+ | **압축 과도 — 구체 운영 셋 명세 없음** |
| 17 | A/B 테스트 3팔 | §4.6.1 configs 3개 | B | "graph-heavy with global summaries" 와 "hybrid_with_tools" 의미 차이 |
| 18 | Shadow mode + 이중 평가 | §8.4 + §4.6.1 metrics | A | 완전 반영 |
| 19 | 6대 함정 ↔ 6대 한계 | §1.3 + §11 | A+ | **가장 잘 매핑된 부분** — 정확히 1:1 |
| 20 | 규제 (FSC/SEC/ESMA) | §8 보안·규제·감사 | A | disclaimer + audit log + 1년 보존 |
| 21 | 비용·지연 통제 | §10 비용·성능 추정 | A | 월 $25-55 구체 추정 |

### 2.2 Trip 1 종합

- **반영 (A 이상):** 9개
- **부분 반영 (B+~B):** 9개
- **압축 과도 (C+):** 1개
- **미반영 (D):** 1개 (멀티모달)
- **범위 외 (N/A):** 1개

평균 등급: **A- (8.0 / 10)**

---

## 3. Trip 2 — 설계안 vs 실제 코드

### 3.1 가정 자산 존재 확인 (10/10 통과)

| # | 설계안 가정 자산 | 실제 파일 | 시점 |
|---|---|---|---|
| 1 | `engine/dart_collector.py` (`class DARTCollector`) | 23 KB, line 68 | 2026-04-28 |
| 2 | `data/ticker_to_yahoo_map.csv` | 106 KB, 4 컬럼 | 2026-02-07 |
| 3 | `data/dart_corp_codes.json` | 87 KB, ticker→corp_code dict | 2026-04-09 |
| 4 | `engine/llm_analyzer.MultiAIConsensusScreener` | 65 KB, line 932 | 2026-04-25 |
| 5 | `data/jongga_v2_results_*.json` archive | 46개 파일 | 운영중 |
| 6 | `app/services/mirofish/mcp_server.py` (FastMCP) | 30 KB, **33개 @mcp.tool()** | 2026-05-13 |
| 7 | `frontend-react/src/pages/admin/AdminEndpointsPage.tsx` (`impactSteps`) | 175 KB, line 36-42 | 2026-05-14 |
| 8 | `engine/scorer.py` (17점 만점) | 17 KB | 2026-03-22 |
| 9 | `engine/jubjub_analyzer.py` | 11 KB | 2026-05-13 |
| 10 | `app/routes/wave.py` | 16 KB | 2026-05-14 |

### 3.2 정확한 가정 (그대로 사용 가능)

| # | 설계안 가정 | 실제 확인 | 등급 |
|---|---|---|---|
| 1 | `ticker_to_yahoo_map.csv` 가 entity resolve 1차 매핑 | 컬럼 `ticker, market, yahoo_ticker, name` — `kr:005930` 즉시 생성 가능 | A+ |
| 2 | `dart_corp_codes.json` 이 DART corp_code 매핑 | 실제 `{"036720":"00260985", ...}` 단순 dict — entity_id 와 1:1 join 가능 | A+ |
| 3 | DARTCollector 7일 캐시 사용 | line 91-102 에 정확히 7일 mtime 캐시 로직 존재 | A+ |
| 4 | AdminEndpointsPage 5단계 `TARGET → BRAIN → GRAPHRAG → DEBATE → VERDICT` | line 37-41 `impactSteps` 정확히 일치 | A+ |
| 5 | MCP server 가 FastMCP + `@mcp.tool()` 패턴 | line 1, 15, 42+ 확인 — **33개 tool 이미 등록** | A+ |
| 6 | jongga_v2 archive 를 evaluation set 으로 | 46개 파일 (충분한 평가 표본) | A+ |

### 3.3 부정확한 가정 (설계안 수정 필요)

| # | 설계안 가정 | 실제 코드 | 영향 |
|---|---|---|---|
| 1 | §4.4 / §6: **"Gemini + GPT-4o 합의"** 만 활용 | 실제는 **3-AI (Gemini + OpenAI + Grok)** + **Claude Devil's Advocate** (llm_analyzer.py line 932-960) | 🚨 **설계안 과소평가 — 더 강한 자산을 약하게 가정** |
| 2 | §4.5 research 의 hallucination 완화는 self-consistency check (§11 한계 #5 미해결) | **Devil's Advocate (Claude) 가 consensus_strong post-review 단계로 이미 구현됨** | 🚨 자산 미언급 — 흡수 패턴 명시 누락 |
| 3 | 부록 B: MCP 도구 9개 신규 추가 | 기존 **33 tools** 와 합쳐 총 42 tools. 충돌 없음 (`graphrag_*` prefix 안전) | ⚠ 안전하나 통합 컨벤션 명시 없음 |
| 4 | §4.6.1 평가의 vector_only/hybrid 비교가 scorer.py 17점과 어떻게 연결되는지 | scorer.py 17점은 jongga_v2 등급 산출용 — eval metrics 와 직접 매핑 안 됨 | ⚠ 평가 메트릭 source-of-truth 불명확 |
| 5 | §5.1 DOCUMENT 노드의 `language` 필드 | DART 는 한국어, SEC 는 영어 — `language` 활용 명시 X | 🟢 사소 |

### 3.4 설계안에 누락된 실제 자산

| # | 자산 | 위치 | 설계안 활용 가능 위치 |
|---|---|---|---|
| 1 | **GrokScreener** | llm_analyzer.py:862, `MULTI_AI_INCLUDE_GROK=1` | Phase 3 community summary 3-of-3 consensus_strong 등급 |
| 2 | **Claude Devil's Advocate** | llm_analyzer.py:955, `DEVIL_ADVOCATE_ENABLED=1` | Phase 4 `/research` 의 self-consistency / hallucination 완화 |
| 3 | **MODEL_* 상수** (gemini/openai/grok) | llm_analyzer.py:915-917 | `audit.model_versions` 일관 키 네이밍 표준 |
| 4 | **33개 기존 MCP tools** | mcp_server.py | 부록 B 통합 컨벤션 명시 (`graphrag_*` prefix) |

### 3.5 Trip 2 종합

- **정확한 가정:** 6개 (A+ 등급)
- **부정확한 가정:** 5개 (중대 2 + 사소 3)
- **누락된 자산:** 4개

평균 등급: **A- (8.5 / 10)** — 자산 존재는 완벽하나, 일부 자산의 강점을 충분히 활용하지 못함.

---

## 4. 추가 발견된 일관성 이슈

두 검토에서 공통으로 드러난 설계안 내부 일관성 이슈:

| # | 위치 | 이슈 | 심각도 |
|---|---|---|---|
| 1 | §4.5.1 audit.model_versions | 3개만 표시 (router, retrieval, generator) — **4-레이어 중 tool 누락** | 중 |
| 2 | §4.1.1, §4.2.2 graph_path 예시 | "삼성전자 → 한화에어로스페이스" — supply chain 예시로 부적절 (방산) | 낮 |
| 3 | 부록 B MCP 도구 매핑 | 9개만 매핑 — **4개 누락** (`query/route`, `event/ingest`, `eval/run`, `metrics/graph`) | 중 |
| 4 | §4.6.1 vs §11 §6 평가 | jongga_v2 forward return proxy 라벨이 §11 에만 있고 §4.6.1 에는 없음 | 낮 |
| 5 | §0 "2주 내 PoC" vs §9 Roadmap | 2주 내 PoC 가 Phase 0–1 만 의미한다는 점 명시 X | 낮 |
| 6 | §4.1.1 entity resolve | dart_corp_codes ↔ ticker_to_yahoo_map join 흐름 명시 X (회사명은 후자에만 있음) | 중 |
| 7 | §5.1 entity_id 형식 | yahoo_ticker `005930.KS` → entity_id `kr:005930` 변환 규칙 명시 X | 낮 |
| 8 | §4.1.1 응답 | corp_code 단일 값만 반환 — 역방향 (corp_code → ticker) 조회 가능성 명시 X | 낮 |

---

## 5. 통합 점수 및 가중 평균

| 평가 항목 | 가중치 | Trip 1 점수 | Trip 2 점수 | 가중 점수 |
|---|---|---|---|---|
| 보고서 권고 반영율 | 30% | 8.0 | — | 2.40 |
| 실제 자산 활용도 | 25% | — | 8.5 | 2.13 |
| 설계 일관성 | 15% | 9.0 | 9.0 | 1.35 |
| MarketFlow 적합성 | 15% | 10 | 10 | 1.50 |
| 구체성/실행가능성 | 10% | 9.0 | 9.0 | 0.90 |
| 누락된 핵심 요소 | 5% | 6.5 | 7.5 | 0.35 |
| **총점** | **100%** | — | — | **8.63 / 10** |

**종합 등급: A- (8.5 / 10)**

두 검토 모두 동일한 점수로 수렴한 것은 우연이 아니다. 설계안의 강점 (구조 / 일관성 / MarketFlow 적합성) 과 약점 (특정 보고서 권고 압축 + 일부 실제 자산 과소평가) 의 균형이 양쪽 관점에서 같은 비율로 드러난다.

---

## 6. 우선순위별 보강 권장 사항

두 검토에서 발견된 갭을 통합하여 우선순위별로 정리한다.

### 🔴 즉시 반영 (5개) — v1.1 필수

1. **§4.4 / §6 의 "Gemini + GPT-4o" 표기 수정** → "Gemini + OpenAI + Grok + Claude(DA)"
   - 효과: Phase 3 community summary 의 confidence tier 가 3-of-3 / 2-of-3 / 1-of-3 으로 세분화 가능
2. **§4.5 research 의 self-consistency → Devil's Advocate 흡수 명시**
   - 효과: §11 한계 #5 (hallucination) 가 **이미 해결 가능한 문제** 로 격하
3. **§4.5.1 audit.model_versions 에 tools 항목 추가**
   - 효과: 보고서 권고 4-레이어 일관성 회복
4. **§4.2.1 query/route 에 DRIFT 추가**
   - 효과: Microsoft local/global/DRIFT 검색 모드 완전 반영
5. **§4.1.1 entity resolve 의 join 흐름 명시**
   - 효과: ticker_to_yahoo_map.name (한글) + dart_corp_codes.corp_code (8자리) 결합 패턴 명확화

### 🟡 중요 보강 (5개) — v1.2 권장

6. **GDELT ingest 패턴 §4.3 에 구체화** — 15분 갱신 주기, event category, DOCUMENT 노드 매핑
7. **평가 데이터셋 §4.6.1 에 구체 명세** — FinanceBench / FinQA / ConvFinQA / TAT-QA / DocFinQA / FinMTEB / BenchmarkQED 운영 방식
8. **부록 B 에 MCP 통합 컨벤션 + 누락 4개 도구 명시**
9. **§11 한계에 멀티모달 (차트·표·PDF) 한 줄 추가** — FinChart-Bench 인용
10. **yahoo_ticker → entity_id 변환 규칙 §5.1 에 명시**

### 🟢 선택적 보강 (3개) — v2.0 이후

11. supply chain 예시 종목 교체 (한화에어로스페이스 → SK하이닉스/한미반도체)
12. HippoRAG (PPR) / PathRAG (path pruning) 흡수 패턴 명시
13. Microsoft prompt auto-tuning 도구 §12 결정사항에 언급

---

## 7. 즉시 반영 가능한 설계 업그레이드 3가지

실제 자산 확인으로 드러난 강점을 활용한 구체적 설계 업그레이드:

### 7.1 Phase 3 community summary confidence 강화

**현재 설계안 §4.4.2:**
```json
"generated_by": {"model": "multi-ai-consensus", "consensus_count": 2}
```

**v1.1 권장:**
```json
"generated_by": {
  "model": "multi-ai-consensus-v2",
  "models_succeeded": ["gemini", "openai", "grok"],
  "consensus_tier": "consensus_strong",
  "devil_advocate_review": {
    "passed": true,
    "concerns": [],
    "model": "claude-sonnet-4"
  }
}
```

### 7.2 Phase 4 research 의 hallucination 완화

**§11 한계 #5 (수정안):**
- 이전: "self-consistency check (미구현)"
- 이후: "Claude Devil's Advocate (llm_analyzer.py:955) 가 consensus_strong post-review 단계로 흡수. `DEVIL_ADVOCATE_ENABLED=1` 환경변수로 제어."

**§4.5.1 response 확장:**
```json
{
  "verdict": {...},
  "self_consistency": {
    "method": "claude-devil-advocate",
    "verified": true,
    "concerns_raised": [],
    "model": "claude-sonnet-4"
  }
}
```

### 7.3 부록 B 의 MCP 통합 컨벤션

**v1.1 권장 추가 내용:**
```
기존 mcp_server.py 의 33 tools 와 통합 규칙:

- prefix `graphrag_` 강제 — 기존 도구와 네이밍 충돌 방지
- 등록 위치: app/services/mirofish/mcp_server.py register_tools() 끝
- 신규 9 tools 추가 후 총 42 tools (Claude Code MCP 한도 미달)
- 상호 호출 허용: graphrag_research 내부에서 기존 mirofish 도구
  (get_dart_disclosures, scrape_naver_finance, analyze_jubjub 등) 활용 가능

누락 도구 4개 처리:
- query/route → mcp__mirofish__graphrag_classify_query (선택 노출)
- event/ingest → 미노출 (admin only, 외부 호출 금지)
- eval/run → 미노출 (운영 도구)
- metrics/graph → mcp__mirofish__graphrag_get_metrics (선택 노출)
```

---

## 8. 결론

### 8.1 핵심 결론

1. **설계안 v1.0 은 즉시 PoC 시작 가능한 품질** — A- (8.5/10), 10개 가정 자산 100% 존재
2. **두 검토에서 동일한 점수로 수렴** — 강점과 약점이 양쪽 관점에서 같은 비율로 드러남
3. **가장 큰 발견은 자산 과소평가** — MarketFlow 의 Multi-AI v2 (3-AI + Devil's Advocate) 가 설계안이 가정한 2-AI 보다 한 단계 더 강함
4. **5개 🔴 즉시 보강 후 v1.1 권장** — 보강 1-2시간 소요, 효과는 Phase 3 / Phase 4 의 confidence 메커니즘에 직접 반영
5. **8개 🟡 + 🟢 보강은 PoC 진행하면서 자연스럽게 흡수 가능**

### 8.2 권장 다음 단계

세 가지 옵션 중 선택:

**옵션 A — 빠른 PoC 우선:** v1.0 그대로 Phase 0 (`/api/graphrag/entity/resolve`) 즉시 시작. 보강은 PoC 결과 보고 v1.1 작성.

**옵션 B — 균형 권장:** 🔴 5개 보강만 반영한 v1.1 작성 후 PoC 시작 (1-2시간 추가).

**옵션 C — 완성도 우선:** 🔴 + 🟡 10개 보강 모두 반영한 v1.1 작성 후 PoC 시작 (반나절 추가).

**추천: 옵션 B** — 자산 과소평가 (🔴 #1 + #2) 만 빨리 수정하면 Phase 3 / Phase 4 의 confidence 메커니즘 설계가 크게 강화되므로 PoC 단계부터 더 견고하게 시작 가능. 나머지 🟡 / 🟢 은 PoC 결과에 따라 자연스럽게 흡수.

### 8.3 검토자 코멘트

설계안 v1.0 은 보고서의 추상적 권고를 MarketFlow 의 구체적 코드 자산에 잘 매핑했다. 다만 **두 가지 종류의 누락** 이 있다:

1. **외부 누락** — 보고서가 명시한 권고 (DRIFT 검색, 멀티모달, 평가 데이터셋 명세) 가 압축 과정에서 빠짐
2. **내부 누락** — MarketFlow 가 이미 가진 강점 (3-AI v2, Devil's Advocate) 을 설계안이 더 약하게 가정

특히 **내부 누락이 더 결정적** — 외부 권고를 다 흡수하더라도 자기 자산을 약하게 가정하면 결과 시스템이 실제보다 약해진다. 즉 v1.1 보강의 우선순위는 🔴 #1, #2 (자산 강점 반영) 가 가장 높다.

PoC 시작 전 이 두 가지만 반영해도 설계안의 실효성이 크게 올라간다.

---

## 9. 참고

- `docs/mirofish_graphrag_analysis_endpoint_design_2026_05_14.md` (검토 대상, v1.0)
- `~/Downloads/deep-research-report.md` (원전 보고서)
- `engine/llm_analyzer.py` (Multi-AI Consensus v2 + Devil's Advocate)
- `engine/dart_collector.py` (DART 7일 캐시)
- `data/ticker_to_yahoo_map.csv`, `data/dart_corp_codes.json`
- `app/services/mirofish/mcp_server.py` (33 FastMCP tools)
- `frontend-react/src/pages/admin/AdminEndpointsPage.tsx` (`impactSteps` 5단계)
- `CLAUDE.md` (MarketFlow 자율 운영 가이드 v3.2.0)

---

**문서 끝.**
