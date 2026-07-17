# TradingAgents 딥 검증 레이어 설계 (AI Brain 매수 유력 종목 검출 업그레이드)

- 날짜: 2026-07-17
- 상태: 사용자 승인 대기 → 승인 후 구현 계획(writing-plans) 진행
- 참조: [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (Apache-2.0, arXiv:2412.20138)

## 1. 목표

**매수 유력 종목을 검출해 내는 것.** 알파 스캐너가 검출하고 CIO가 BUY 판정한 후보들에 대해
TradingAgents 방법론(다중 에이전트 구조화 토론)으로 딥 검증을 수행하여,
확신도 높은 매수 유력 종목만 TOP3로 올라오도록 검출 품질을 끌어올린다.

- 검증 결과는 **자문이 아니라 적극 개입**: SELL 판정 종목은 TOP3에서 제외·대체하고,
  STRONG_BUY/BUY는 가점, HOLD는 감점하여 순위를 재조정한다.
- 사용자 확인 사항: 복잡도보다 **분석 정확도와 매수 유력 검출력이 최우선**.

## 2. 통합 방식 결정: 패턴 네이티브 이식 (pip 원본 탑재 아님)

pip 원본(`tradingagents` 패키지)은 데이터 어댑터가 미국 중심(Alpha Vantage, Reddit,
StockTwits)이라 한국 주식에서 센티먼트/뉴스 레이어가 공백이 되고, 영어 프롬프트로
한국 종목 재료를 분석하게 되어 **정확도가 오히려 하락**한다. LangChain/LangGraph
대형 의존성도 miniPC 운영에 부담.

따라서 TradingAgents의 **파이프라인 구조 전체를 축약 없이** mirofish 내부에 이식한다:

```
분석가 4인 (독립 리포트)
  ├─ Fundamentals Analyst  ── yfinance .KS/.KQ (ticker_to_yahoo_map) + 네이버 lite
  ├─ News Analyst          ── live_data 뉴스 코퍼스 + source_hub
  ├─ Sentiment Analyst     ── 뉴스 감성 + 커뮤니티/검색 신호
  └─ Technical Analyst     ── technical_analysis + sector_rs + RS 등급(1~99)
        ↓
Bull Researcher vs Bear Researcher — N라운드 구조화 토론 (기본 2, env 조절)
        ↓
Research Manager — 토론 심판, 투자 논지 확정
        ↓
Trader — 진입/청산/사이징 관점 트레이딩 플랜
        ↓
Risk Team 토론 — 공격(Risky)/보수(Safe)/중립(Neutral) 3인
        ↓
Portfolio Manager — 최종판정: STRONG_BUY | BUY | HOLD | SELL + confidence(0~100)
```

- LLM: 기존 `llm_client.generate_text()` 폴백 체인(Gemini→DeepSeek→OpenAI) 재사용.
- LLM 전면 실패 시 **결정론적 rule fallback** (기존 agent_debate/cio_react 패턴 동일).
  결과에 `method: llm|rule|mixed` 명기.
- Apache-2.0 출처를 `engine.py` docstring에 명기.

### 판정 등급 의미 (매수 유력 정렬)

| 판정 | 조건 | TOP3 효과 |
|------|------|----------|
| STRONG_BUY | Bull 논거 우세 + 리스크팀 통과 + confidence ≥ 75 | 가점 大 + **"매수 유력" 배지** |
| BUY | 매수 우세 | 가점 (confidence 비례) |
| HOLD | 논거 균형/불충분 | 감점 (제외는 안 함) |
| SELL | Bear 논거 우세 또는 리스크팀 거부 | **TOP3 제외, 다음 후보로 대체** |

## 3. 컴포넌트 (신규 패키지 `app/services/mirofish/tradingagents/`)

| 파일 | 책임 | 의존 |
|------|------|------|
| `data_hub.py` | 종목별 4개 관점 데이터 번들 수집 (KR 네이티브). 각 소스 실패 격리 | live_data, technical_analysis, sector_rs, yfinance |
| `analysts.py` | 분석가 4인 — 각자 독립 구조화 리포트 (JSON) | data_hub, llm_client |
| `research_debate.py` | Bull/Bear N라운드 토론 + Research Manager 판정 | analysts 리포트, llm_client |
| `trader_risk.py` | 트레이더 플랜 → 리스크 3인 토론 → PM 최종 결정 | research_debate 결과, llm_client |
| `engine.py` | `run_deep_analysis(symbol, name, context) -> dict` 오케스트레이션, 런 영속화 | 전체 |

- 영속화: `data/admin_mirofish/tradingagents_runs/<run_id>.json` + `latest.json`
  (`write_json_atomic`, 기존 scanner_runs 패턴).
- 각 단계 결과(리포트 전문, 토론 라운드별 발언, 판정 근거)를 트레이스로 전부 보존.

## 4. 워크플로우 개입 지점 (`workflow.py _complete_workflow`)

기존: `ranked` 산출 → `_select_top3(require_buy)` → outcomes → 텔레그램.

변경: `ranked` 산출 후 TOP3 확정 **전에** 딥 검증 단계 삽입:

1. CIO BUY 후보 상위 N개(기본 5, `MIROFISH_TA_MAX_CANDIDATES`)에 `run_deep_analysis` 실행
2. 개입 규칙 적용 → `ta_adjusted_score` 산출:
   - STRONG_BUY: `final_score + TA_BOOST_STRONG (기본 +8)`
   - BUY: `final_score + TA_BOOST_BUY × (confidence/100) (기본 최대 +5)`
   - HOLD: `final_score + TA_PENALTY_HOLD (기본 -3)`
   - SELL: 후보 풀에서 제외 (다음 순위 후보가 자동 승계)
   - 분석 실패/미실행 종목: `final_score` 그대로 (무보정)
3. `ta_adjusted_score` 순으로 TOP3 재선정
4. 각 결과 항목에 `tradingagents` 필드 첨부:
   `{verdict, confidence, strong_buy(bool), bull_case, bear_case, risk_summary, run_id, method}`
5. 텔레그램 TOP3 메시지에 판정·"매수 유력" 배지·핵심 논거 1줄 추가
   (`build_workflow_top3_telegram_message` 확장)

### 안전장치 (기존 운영 원칙 준수)

- 킬스위치: `MIROFISH_TRADINGAGENTS_DISABLED=true` → 단계 전체 스킵, 기존 로직 그대로
- 딥 검증 단계 자체가 예외를 던지면 **기존 선정 결과로 무손상 폴백** (try/except 격리)
- 종목 단위 실패 격리: 1종목 분석 실패가 워크플로우를 죽이지 않음
- `analysis_runs`/`final_score` 원본 보존 (`ta_adjusted_score` 별도 필드) —
  기존 outcome_tracker/top3_metrics/학습루프 무변경으로 TA 개입 효과가 자동 측정됨

### env 설정 요약

| 변수 | 기본 | 의미 |
|------|------|------|
| `MIROFISH_TRADINGAGENTS_DISABLED` | false | 킬스위치 |
| `MIROFISH_TA_MAX_CANDIDATES` | 5 | 딥 검증 대상 후보 수 |
| `MIROFISH_TA_DEBATE_ROUNDS` | 2 | Bull/Bear 토론 라운드 (1~4) |
| `MIROFISH_TA_BOOST_STRONG` | 8.0 | STRONG_BUY 가점 |
| `MIROFISH_TA_BOOST_BUY` | 5.0 | BUY 최대 가점 (confidence 비례) |
| `MIROFISH_TA_PENALTY_HOLD` | 3.0 | HOLD 감점 |

## 5. 엔드포인트 (신규 blueprint 함수 — admin_mirofish_analysis.py 패턴, 전부 `@admin_required`)

| Method | Path | 용도 |
|--------|------|------|
| POST | `/api/admin/mirofish/tradingagents/analyze` | 단일 종목 온디맨드 딥 분석 `{symbol, name?, rounds?}` |
| GET | `/api/admin/mirofish/tradingagents/runs` | 최근 런 목록 (요약) |
| GET | `/api/admin/mirofish/tradingagents/runs/<run_id>` | 풀 트레이스 (토론 전문 포함) |
| GET | `/api/admin/mirofish/tradingagents/status` | 설정·킬스위치·최근 실행 상태 |

- 단일 분석은 동기 실행 (종목당 수십 초 예상, 기존 analysis run 패턴과 동일 수준).
- 워크플로우 내 자동 실행 결과도 동일 runs 저장소를 공유 → 같은 GET 으로 조회 가능.

## 6. 비용/시간 추정

- 종목당 LLM 호출 ≈ 12회 (분석가 4 + 토론 2라운드×2 + 매니저 1 + 트레이더 1 + 리스크 3 + PM 1)
- 사이클당 후보 5개 ≈ 60회 — Gemini Flash 기준 저비용. 라운드/후보 수 env 로 조절.
- 워크플로우 지연 증가: 후보당 병렬 실행(기존 ThreadPool 재사용) 시 수 분 이내 목표.

## 7. 에러 처리

- 데이터 소스별 실패 격리: 분석가는 확보된 데이터만으로 리포트 작성, 누락 소스는 리포트에 명기
- LLM 타임아웃/실패 → 해당 에이전트 rule fallback → `method: mixed`
- 전 단계 rule fallback 시에도 결정론적 판정 산출 (Brain/기술지표 직접 reading)

## 8. 테스트

1. rule fallback 경로 단위 테스트 — LLM 없이 전체 파이프라인 결정론 검증 (판정 산출 확인)
2. 개입 규칙 테스트 — SELL 제외·대체 / STRONG_BUY 가점 / 실패 종목 무보정 / 순위 재조정
3. 킬스위치 테스트 — `MIROFISH_TRADINGAGENTS_DISABLED=true` 시 기존 TOP3 결과와 동일
4. 폴백 테스트 — 딥 검증 단계 예외 시 기존 선정 결과 반환
5. 기존 테스트 회귀 0 확인

## 9. 범위 제외 (YAGNI)

- 프론트엔드 대시보드 UI (백엔드 필드 첨부까지만; UI는 후속 작업)
- TradingAgents 원본의 시뮬레이션 매매/포트폴리오 실행 기능 (검출이 목적, 매매 아님)
- 미국 주식 적용 (KR 검출 파이프라인 한정; 구조상 확장 가능하게만 설계)
