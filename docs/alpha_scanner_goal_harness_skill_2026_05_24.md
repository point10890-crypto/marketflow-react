# Alpha Scanner Goal Harness Skill

작성일: 2026-05-24  
적용 범위: MarketFlow / MiroFish Alpha Scanner

## 1. 목표

알파스캐너의 목적은 MCP 자동화가 아니라, 정확한 데이터에 기반해 수익 가능성이 높은 종목을 검출하는 것이다.

모든 분석 자동화와 MCP 도구는 다음 질문에 답해야 한다.

1. 이 종목이 실제로 수익 후보로 볼 만한가?
2. 데이터 근거가 충분한가?
3. 리스크가 먼저 걸러졌는가?
4. 수급, 공시, 가격, 거래량, 기술, 성과검증 중 어떤 근거가 부족한가?
5. Top3 분석으로 넘겨도 되는가, 아니면 추가 데이터 확인이 먼저인가?

## 2. 하네스 원칙

### 필수 원칙

- MCP는 목적이 아니라 보조 인터페이스다.
- LLM은 숫자를 생성하지 않고, 근거를 요약하고 충돌을 설명한다.
- scanner ranking 변경 전에는 반드시 shadow score와 사후성과 검증을 거친다.
- 후보의 최종 판단은 특정 종목명, 종목코드, 시장에 귀속되어야 한다.
- 데이터 출처와 신선도가 불명확하면 확신도를 제한한다.

### 금지

- 단일 가격 모멘텀만으로 좋은 종목이라고 판단하지 않는다.
- 뉴스/SNS/검색 관심도만으로 BUY 후보를 만들지 않는다.
- MCP 자동화 성공을 알파 검출 성공으로 착각하지 않는다.
- 사후성과 검증 없이 live score weight를 크게 바꾸지 않는다.

## 3. Goal Scorecard

각 scanner run은 다음 gate를 통과해야 한다.

| Gate | 목적 | 실패 시 조치 |
|---|---|---|
| 후보 존재 | 분석 가능한 종목 후보가 있는지 확인 | Top3 실행 보류 |
| 가격 데이터 신선도 | 실제 가격/거래량 기반인지 확인 | confidence cap |
| 근거 깊이 | 최소 3개 이상의 독립 근거 클러스터 확인 | 추가 데이터 MCP 호출 |
| 리스크 통제 | 과열/변동성/저유동성 후보 필터링 | risk review 우선 |
| 수급 확인 | 외국인/기관/프로그램/거래대금 확인 | conviction 제한 |
| 공시 이벤트 확인 | DART 리스크와 촉매 확인 | event risk tag 부여 |
| 사후성과 검증 | 과거 추천이 실제 수익으로 이어졌는지 확인 | advisory-only 유지 |

## 4. 구현 기준

1차 구현은 read-only `profit_detection_scorecard`로 한다.

산출:

- run-level readiness
- gate별 pass/partial/fail
- hard blockers
- candidate별 `goal_fit_score`
- candidate별 `goal_verdict`
- 다음에 호출해야 할 데이터 도구

이 scorecard는 live ranking을 변경하지 않는다. 다만 Top3 자동화가 어떤 데이터 근거를 더 확인해야 하는지 명확히 알려준다.

## 5. 구현된 1차 산출물

- 후보별 `analysis_profile.profitability_scorecard`
  - `goal_fit_score`
  - `goal_verdict`
  - `hard_blockers`
  - `missing_confirmations`
  - gate별 pass/partial/fail
- run-level `goal_harness`
  - 평균 goal fit
  - verdict count
  - hard blocker count
  - missing confirmation count
- feature vector 반영
  - `goal_fit_score`
  - `goal_verdict`
  - `profitability_scorecard`
- outcome tracker 반영
  - 추천 당시 goal score와 blocker를 사후성과와 함께 저장

이 1차 구현은 live ranking에 직접 개입하지 않는다. 목적은 좋은 종목 검출 판단을 더 엄격하게 만들고, 이후 수급/DART/성과검증을 어디에 붙여야 하는지 데이터로 드러내는 것이다.

## 6. 검증 기준

테스트는 다음을 보장해야 한다.

- scorecard가 scanner run 없이도 안전하게 실패 응답을 반환한다.
- strong 후보는 weak 후보보다 높은 `goal_fit_score`를 받는다.
- 수급/DART 근거가 없으면 MCP 추천 호출이 생성된다.
- scorecard는 `mutates_scanner_scores: false`를 유지한다.
- 라우트와 MCP read-only tool은 인증/가드 구조를 변경하지 않는다.
