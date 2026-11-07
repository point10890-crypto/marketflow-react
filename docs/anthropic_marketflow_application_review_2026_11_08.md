# MarketFlow Anthropic API 활용 검토

검토일: 2026-11-08 KST. 코드 기준: dc46e5402283559bd9fced76825ce5fdff1cf8cd.
범위: 현재 코드와 공식 문서·공개 참고 소스 조사. 유료 API 호출, 계정·키 변경, 운영 기능 활성화는 수행하지 않았다.

## 판단

우선 적용 대상은 **뉴스·공시에서 새로운 투자 재료를 구조화하고, 정량 후보의 순위를 보완하며, 최초 매수 근거의 변화를 추적하는 기능**이다. 수익 개선 여부는 별도 전향 비교로 평가해야 한다. API를 추가했다는 사실이나 모델의 자신감 점수는 투자 성과 증거가 아니다.

기존 Flask·작업 스케줄러·저장 원장 안에 Anthropic Messages API 어댑터를 추가하는 방법이 적합하다. 현재 운영 구조를 유지하면서 필요한 작업에만 모델을 선택할 수 있다. 별도 Managed Agents 운영 체제로 옮기는 것은 이번 단계의 필요조건이 아니다.

## 현재 코드에서 확인한 사실

| 위치 | 확인 내용 | 적용 시 조치 |
|---|---|---|
| `engine/llm_analyzer.py:898`, `:1429` | 뉴스 분석·종목 선별 Claude 클래스가 남아 있고 Haiku 4.5를 지정 | 기존 출력 계약과 활용할 코드만 선별 |
| `engine/llm_analyzer.py:2071` | 현재 MultiAIConsensusScreener의 Claude 반론 검토기는 None | 과거 설계 문서만 보고 현재 활성화됐다고 판단하면 안 됨 |
| `app/services/mirofish/llm_client.py:8` | 공용 텍스트 경로는 DeepSeek→OpenAI, 이미지 경로는 Gemini→OpenAI | 전체 제공자 순서를 바꾸지 않고 작업별 Anthropic 경로를 제안 |
| `engine/llm_analyzer.py:2630`, `:2662` | 구형 반론 검토에서 JSON 오류·시간 초과를 PASS로 반환 | 활성화 전에 UNVERIFIED/FAILED로 분리, 성공으로 기록하지 않음 |
| `engine/llm_analyzer.py:2501` | 구형 Haiku 비용 상수와 공용 가격표가 다름 | 실제 모델·usage 기준 공용 비용 원장 사용 |
| `app/services/mirofish/alpha_lab/catalyst_context.py:288` | 해당 AlphaLab 재료 문맥 계약은 used_in_selection=False, association_status=unproven | 기존 결정을 덮어쓰지 않고 새로운 후보 생성·순위 실험 경로로 검증 |

이 검토는 위 경로의 코드 상태를 확인한 것이다. Anthropic 키의 현재 유효성·잔액·모델 접근 가능 여부나 다른 모든 분석 경로의 활성 상태를 확인한 것은 아니다.

## 권장 기능과 투자자 화면

1. **재료 기반 후보 발견**: 새 기사·DART 원문에서 기업 식별, 사건 종류, 신규성, 확정/계획/추측, 실적 영향 경로, 핵심 날짜를 추출한다. 동일 사건의 반복 보도는 하나로 묶는다. 직접 언급 기업과 검증된 공급망 관련 기업을 구분하며, 관련 기업이라는 이유만으로 매수 후보에 올리지 않는다. 시총 상위·유동성·재무 기준을 통과한 유니버스 안에서 새 후보를 제안한다.
2. **상위 후보 비교**: 기존 정량 엔진 후보 약 20개와 새 재료 후보를 비교한다. 최근 가격 반응, 거래대금, 수급, 공시, 이미 알려진 내용인지 여부를 대조해 현재 관심을 둘 이유와 약점을 정리한다. 가격 반영 여부는 가설과 관측 근거로 표현하며 확정 사실로 만들지 않는다.
3. **매수 근거 추적**: 최초 판단과 당시 원문을 고정한다. 새 기사·실적·공시가 들어오면 근거가 강화·유지·훼손됐는지 비교하고 중요한 변화만 기록한다. 늦게 수집한 과거 기사는 최초 판단의 근거로 소급하지 않는다.
4. **독립 반대 근거 검토**: 중요한 후보 또는 자료 충돌에만 추가 모델을 사용한다. 다른 모델과 의견이 일치한다는 사실보다 원문이 주장에 실제로 부합하는지를 검사한다.

사용자 카드의 필수 내용은 종목명, 현재 판단, 지금 주목할 이유 2개, 확인할 진입 조건, 참고 진입·손절·목표, 무효화 조건, 원본 링크와 확인 시각이다. ATR·켈리·비중·손익비는 검증된 수치로 Python에서 계산한다. Claude는 누락 시세나 승률을 생성하지 않는다.

## 처리 흐름

```text
기사·공시·시세 수집 → 거래일/취득시각 검증 → 사건 중복 제거
  → Claude 재료 구조화 → 기존 우량주·가격·수급 필터
  → 상위 후보 근거 비교 → 결정론적 진입·손절·비중 계산
  → 제안 카드 저장 → 새 증거에 따른 근거 변화 감시
```

제안하는 신규 작업 종류는 NEWS_EVENT_EXTRACT, CANDIDATE_REVIEW, THESIS_UPDATE다. 모두 현재 구현된 기능명이 아니라 추가 설계안이다. 공용 ai_routing의 예산·오류 분류·중복 방지·호출 원장을 재사용한다. 페이지 조회에서는 유료 추론을 실행하지 않고 저장 결과만 반환한다.

## 공식 API 기능의 적용

- [Tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview): MarketFlow가 허용한 읽기 전용 가격·공시·원문 도구를 연결한다. 필요한 도구 선택은 모델이 제안하고 실제 실행·권한·횟수 제한은 서버가 결정한다.
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs): 사건 유형·기업 코드·근거 ID 등 고정 JSON 필드를 받는다. 스키마 적합과 내용의 사실 여부는 별도로 검사한다.
- [Citations](https://platform.claude.com/docs/en/build-with-claude/citations): 제공한 원문의 정확한 구간과 설명을 연결한다. 원문 자체가 사실인지까지 보장하는 기능은 아니다.
- **호환성 주의**: 공식 문서상 citations와 output_config.format의 엄격 JSON 출력은 한 요청에서 호환되지 않는다. 구조화 경로는 서버가 부여한 evidence_id와 원문 구간을 검증하고, 필요할 때 별도 인용형 설명을 생성한다.
- [Batch](https://platform.claude.com/docs/en/build-with-claude/batch-processing): 장 종료 후 평가·과거 문서 구조화에 적용할 수 있고 토큰 비용은 50% 할인된다. 완료까지 최대 24시간을 고려해야 하므로 장중 긴급 판단에는 일반 Messages를 사용한다.
- [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching): 반복되는 규칙·공통 문서를 재사용한다. 모델별 최소 길이·만료·쓰기 비용을 고려하며 모든 입력이 할인된다고 가정하지 않는다.

## 가져올 가치가 있는 공식 참고 소스

Anthropic의 [financial-services](https://github.com/anthropics/financial-services) 저장소에서 아래 설계를 선별할 가치가 있다.

- [catalyst-calendar](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/equity-research/skills/catalyst-calendar/SKILL.md): 실적·기업·업종 이벤트 일정과 결과 보관 방식.
- [thesis-tracker](https://github.com/anthropics/financial-services/blob/main/plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md): 최초 투자 근거, 이를 깨는 증거, 변화 이력의 구조.

위 두 파일은 읽고 검토했다. 자동 매매 엔진이나 검증된 초과수익 모델이 아니라 업무 절차와 프롬프트의 참고 소스다. 저장소의 Apache-2.0 라이선스를 확인했으며 실제 재사용 시 라이선스·저작권 고지를 보존해야 한다. 연결된 금융 데이터 제공사의 이용권은 별도이며 API 사용만으로 포함되지 않는다.

## 모델과 비용 가정

[공식 모델 목록](https://platform.claude.com/docs/en/models/overview)과 [가격표](https://platform.claude.com/docs/en/about-claude/pricing)를 조사 시점에 확인했다. 아래는 API 계정의 모델 접근 권한이나 실제 호출 품질을 검증하기 전의 비교용 계산이다.

| 용도 | 후보 모델 | 하루 호출 | 호출당 입력/출력 토큰 | 하루 계산액 |
|---|---|---:|---:|---:|
| 기사 사건 분류 | Haiku 5.5 | 1,000 | 2,000 / 250 | $0.325 |
| 상위 후보 근거 비교 | Sonnet 5.5 | 20 | 8,000 / 1,000 | $0.520 |
| 중요 후보·충돌 검토 | Opus 5.5 | 3 | 12,000 / 1,500 | $0.234 |

입력/출력 100만 토큰 단가는 각각 Haiku $0.10/$0.50(입력 10만 토큰 이하), Sonnet $2/$10, Opus $4/$20을 적용했다. 30일 매일 같은 사용량이면 **$32.37**이다. 출력량 가정은 과금되는 추론 토큰을 포함한 전체 출력 예산이며, 긴 원문·추론량 증가·재시도·추가 인용 요청·검색·데이터 이용료·세금·환율은 이 계산에 포함하지 않았다. 실제 비용은 usage로 확인한다. Batch·캐시 할인은 예시에 반영하지 않았다.

## 도입·평가 순서

1. 고정 원문 표본으로 기업 연결 정확도, 신규/중복 분리, 근거 연결, 오류 시 상태 처리를 평가한다. 현재 기본 제공자와 같은 입력을 비교한다.
2. 기존 추천과 별개로 후보를 저장하는 비교 운영을 한다. 시작 전에 대상 유니버스, 입력 시각 기준, 전략·모델 버전, 거래비용, 진입 규칙, 5/10/20거래일 평가 구간을 고정한다.
3. 두 실험을 분리한다: 기존 후보의 순위를 개선하는 효과 / 뉴스에서 새로운 후보를 찾아 추가하는 효과. 선택 종목과 탈락 종목을 모두 보관한다.
4. 최소 40거래일을 초기 관측 창으로 두되, 성숙 표본·시장 국면이 부족하면 결론을 유보한다. 순수익, 벤치마크 대비 수익, 큰 손실, 최대낙폭, 기회 누락, 판단당 비용을 함께 본다. 해당 구간에서 유리하게 보이도록 기준을 다시 맞추지 않는다.
5. 사전 고정한 성과·품질·비용 기준을 통과한 기능만 실제 후보 순위에 반영한다. 실패하거나 응답이 불명확하면 검증 완료로 표시하지 않고 기존 검증 결과를 보존한다.

우선순위는 **재료 구조화 → 상위 후보 비교 → 최초 근거 추적**이다. 공식 플러그인을 통째로 설치하거나 모든 종목에 고가 모델을 반복 호출하는 작업은 선행할 필요가 없다.
