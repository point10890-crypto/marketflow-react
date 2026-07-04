# MiroFish Crash Rebound Signal Architecture

작성일: 2026-07-04
목적: 폭락장 이후 반등 가능성을 자동 점검하여 알파 스캐너의 Top3 후보 검출력을 강화한다.

## 1. 핵심 목적

이 기능의 목적은 MCP 자동화 자체가 아니라, 수익 가능성이 높은 후보 종목을 더 정확히 걸러내는 것이다.

Crash Rebound Signal은 다음 질문에 답한다.

- 지금 시장이 정상장, 경계장, 폭락장, 기술적 반등장, 회복장 중 어디에 있는가?
- 반등 시그널이 충분히 확인되어 알파 스캐너 후보를 적극적으로 분석할 수 있는가?
- 반등이 단순 숏커버링인지, 수급과 변동성 완화가 동반된 유효 반등인지 구분할 수 있는가?
- 시장 리스크가 높아 Top3 후보의 점수/알림/진입 판단을 낮춰야 하는가?

원칙:

- LLM은 숫자를 만들지 않는다. 수치, 등락률, 지표값은 API/파일/계산 결과에서만 온다.
- 뉴스/소셜 신호는 단독 매수 근거가 아니다. 가격, 변동성, 환율, 수급, 신용/파생 지표와 결합한다.
- 이 기능은 자동매매가 아니라 정보성 시장 판단과 후보 필터링 보조 시스템이다.

## 2. 운영 위치

기존 MarketFlow 구조에 덧붙이는 위치:

```text
Market Data Adapters
  -> Crash Rebound Signal Engine
  -> Market Regime Gate
  -> Alpha Scanner Candidate Scoring
  -> Batch GraphRAG / Agent Debate / CIO Verdict
  -> Top3 Selection / Telegram / Dashboard
  -> Outcome Tracking / Learning Feedback
```

주요 파일 접점:

- Backend service 신규: `app/services/mirofish/crash_rebound.py`
- Data artifact 신규: `data/admin_mirofish/market/crash_rebound/latest.json`
- History artifact 신규: `data/admin_mirofish/market/crash_rebound/history/{YYYY-MM-DD}.json`
- Admin routes 확장: `app/routes/admin_mirofish.py`
- Scheduler 확장: `scheduler.py`
- Pipeline dashboard 확장: `app/services/mirofish/pipeline_overview.py`
- Scanner integration: `app/services/mirofish/alpha_scanner.py`
- Workflow integration: `app/services/mirofish/workflow.py`
- Frontend client: `frontend-react/src/lib/mirofishApi.ts`
- Admin UI: `frontend-react/src/components/admin/TodaysPipelineCard.tsx`

## 3. 데이터 소스 설계

### 3.1 기본 시장 체크 6개

| 지표 | 목적 | 1차 소스 | 대체 소스 | 저장 필드 |
|---|---|---|---|---|
| VIX | 글로벌 공포/변동성 | Yahoo `^VIX` | CBOE, Investing | `vix.value`, `vix.change_pct` |
| CNN Fear & Greed | 심리 상태 | CNN | MacroMicro | `fear_greed.score`, `fear_greed.label` |
| KOSPI | 한국 지수 상태 | Yahoo `^KS11` | Naver, Investing | `kospi.price`, `kospi.change_pct` |
| USD/KRW | 외국인 수급 압력 | Investing | Yahoo `KRW=X`, XE | `usdkrw.value`, `usdkrw.change_pct` |
| S&P 500 | 글로벌 위험 선호 | Yahoo `^GSPC` | Investing | `sp500.price`, `sp500.change_pct` |
| EWY | 한국 야간 선행 신호 | Yahoo `EWY` | Investing | `ewy.price`, `ewy.change_pct` |

### 3.2 폭락장 반등 시그널 14개

| 그룹 | 시그널 | 데이터 타입 | 자동화 난이도 | 판단 |
|---|---|---|---:|---|
| 공포 심리 | VIX 전일 대비 -10% 이상 | price/indicator | 낮음 | `yes/no/unknown` |
| 공포 심리 | CNN F&G 20 미만 | indicator | 중간 | extreme fear 여부 |
| 공포 심리 | Put/Call Ratio > 1.0 | indicator | 중간 | 과매도/헤지 과열 |
| 야간 선행 | EWY +1% 이상 | price | 낮음 | 한국 선행 반등 |
| 야간 선행 | S&P500 futures 양수 | futures | 중간 | 글로벌 위험 선호 |
| 야간 선행 | Insider cluster buy 10건 이상 | external/scrape | 높음 | 참고 신호 |
| 수급 | 외국인 순매도 완화/순매수 전환 | KRX/KIS | 중간 | 핵심 신호 |
| 수급 | 공매도 잔고 감소 전환 | KRX short | 중간 | 숏커버링 |
| 수급 | 신용융자 고점 대비 30% 급감 | KOFIA | 중간 | 반대매매 소진 |
| 신용 | HY OAS 축소 전환 | FRED | 낮음 | 글로벌 신용 리스크 완화 |
| 환율 | USD/KRW 하락 전환 | FX | 낮음 | 원화 안정 |
| 기술 | KOSPI RSI(14) < 30 또는 회복 | derived | 낮음 | 과매도/반등 |
| 정책 | 정부 안정화 대책 발표 | news/official | 높음 | 보조 신호 |
| 뉴스 | 공포 뉴스에서 안정/반등 뉴스로 전환 | news NLP | 높음 | 보조 신호 |

## 4. 데이터 모델

`latest.json` 예시:

```json
{
  "id": "mcr_20260704090000",
  "generated_at": "2026-07-04T09:00:00+09:00",
  "cutoff": "2026-07-04T09:00:00+09:00",
  "status": "rebound_watch",
  "regime": "crash_rebound_candidate",
  "score": 64,
  "risk_score": 42,
  "confidence": "medium",
  "yes_count": 6,
  "unknown_count": 2,
  "source_freshness": {
    "status": "partial",
    "stale_sources": ["put_call_ratio"],
    "missing_sources": []
  },
  "basic_indicators": {
    "vix": {"value": 31.2, "change_pct": -11.4, "state": "rebound_signal", "source": "yahoo", "fetched_at": "..."},
    "fear_greed": {"score": 18, "label": "Extreme Fear", "state": "capitulation", "source": "cnn", "fetched_at": "..."},
    "kospi": {"price": 2520.1, "change_pct": -2.8, "state": "stress", "source": "yahoo", "fetched_at": "..."},
    "usdkrw": {"value": 1392.5, "change_pct": -0.7, "state": "improving", "source": "investing", "fetched_at": "..."},
    "sp500": {"price": 5200.4, "change_pct": 1.1, "state": "risk_on", "source": "yahoo", "fetched_at": "..."},
    "ewy": {"price": 61.4, "change_pct": 1.6, "state": "lead_rebound", "source": "yahoo", "fetched_at": "..."}
  },
  "signals": [
    {
      "id": "vix_drop_10pct",
      "label": "VIX 전일 대비 -10% 이상",
      "result": "yes",
      "strength": 0.8,
      "evidence": "VIX -11.4%",
      "source_grade": "A",
      "source": "yahoo",
      "fetched_at": "..."
    }
  ],
  "scanner_policy": {
    "mode": "risk_adjusted",
    "alpha_multiplier": 1.05,
    "risk_multiplier": 0.95,
    "telegram_level": "normal",
    "top3_min_score_delta": -2
  },
  "interpretation": {
    "summary": "공포 완화와 환율 안정은 확인되지만 외국인 현물 수급 확인 전까지 신뢰도는 제한됩니다.",
    "conditions_to_upgrade": ["외국인 현물 순매수", "KOSPI RSI 30 회복", "EWY 2거래일 연속 강세"],
    "conditions_to_downgrade": ["USD/KRW 1400 재돌파", "VIX 재상승", "외국인 선물 매도 확대"]
  }
}
```

## 5. 점수 체계

### 5.1 상태 분류

| 상태 | 조건 | 스캐너 영향 |
|---|---|---|
| `normal` | 위험/반등 시그널 모두 약함 | 기존 스코어 유지 |
| `caution` | VIX, USD/KRW, KOSPI 중 2개 이상 경고 | 리스크 점수 상향 |
| `crash` | KOSPI 급락 + VIX 급등 + 환율 악화 | Top3 알림 보수화 |
| `capitulation` | 극단 공포 + 과매도 + 신용/수급 소진 일부 | 반등 감시 시작 |
| `rebound_watch` | 14개 중 3개 이상 YES | 후보 분석 허용, 점수 소폭 보정 |
| `rebound_confirmed` | 14개 중 5개 이상 YES + 수급/환율 중 1개 확인 | Top3 적극 분석 |
| `recovery` | 7개 이상 YES + 외국인/ETF/파생 확인 | 시장 레짐 우호 보정 |

### 5.2 가중치

가중치는 수익 후보 검출에 가까운 신호를 높게 둔다.

| 클러스터 | 가중치 | 이유 |
|---|---:|---|
| 외국인/기관/프로그램 수급 | 25 | 실제 돈의 방향 |
| 변동성/VIX/VKOSPI | 18 | 폭락/반등 전환 핵심 |
| 환율/USD-KRW | 15 | 외국인 수급 전송 경로 |
| EWY/S&P futures | 12 | 한국 야간 선행 |
| KOSPI 기술/RSI | 12 | 과매도 및 되돌림 |
| 신용/공매도/PutCall | 10 | 포지션 소진 |
| 정책/뉴스 | 8 | 보조 확인 |

### 5.3 스캐너 반영 방식

스코어를 직접 크게 흔들지 않고, 시장 레짐 필터로 제한적으로 반영한다.

```text
candidate.final_score =
  scanner_rank_score
  + GraphRAG/CIO adjustment
  + outcome memory adjustment
  + market_rebound_adjustment
  - market_risk_penalty
```

반영 규칙:

- `normal`: `market_rebound_adjustment = 0`
- `caution`: 고위험 후보 risk +3~8
- `crash`: `BUY`가 아닌 후보 Top3 제외 강화, Telegram summary만 발송
- `rebound_watch`: 낙폭 과대+수급 개선 후보 +1~3
- `rebound_confirmed`: 낙폭 과대+RS 개선+거래대금 회복 후보 +2~5
- `recovery`: 기존 alpha score를 우선하되 시장 리스크 페널티 완화

## 6. 백엔드 아키텍처

### 6.1 서비스 모듈

신규 모듈: `app/services/mirofish/crash_rebound.py`

핵심 함수:

```python
def collect_market_inputs(payload: dict | None = None) -> dict:
    """VIX, Fear & Greed, KOSPI, USD/KRW, S&P500, EWY 등 입력값 수집."""

def evaluate_crash_rebound(inputs: dict) -> dict:
    """6개 기본 지표 + 14개 반등 시그널을 yes/no/unknown으로 평가."""

def build_scanner_policy(result: dict) -> dict:
    """알파 스캐너에 반영할 mode, multipliers, alert policy 생성."""

def run_crash_rebound_check(payload: dict | None = None) -> dict:
    """수집 -> 평가 -> artifact 저장 -> latest 갱신."""

def read_latest_crash_rebound() -> dict | None:
    """Dashboard/API/MCP에서 읽을 최신 결과."""
```

### 6.2 Source Adapter

초기 구현은 이미 있는 데이터 소스를 우선 사용한다.

1. `pipeline_overview.py`와 dashboard market 데이터에서 KOSPI, KOSDAQ, VIX, Fear & Greed 재사용
2. `live_data.py` 또는 기존 price provider에서 Yahoo/TradingView fallback
3. KIS/KRX 수급은 있으면 사용, 없으면 `unknown`으로 둔다
4. 뉴스/정책은 초기에는 rule-based keyword count로 advisory만 생성한다

중요: source가 없으면 실패가 아니라 `unknown`이다. 다만 `unknown_count`가 많으면 confidence를 낮춘다.

### 6.3 Route/API

관리자:

- `GET /api/admin/mirofish/market/crash-rebound/latest`
- `POST /api/admin/mirofish/market/crash-rebound/run`
- `GET /api/admin/mirofish/market/crash-rebound/history?limit=30`
- `GET /api/admin/mirofish/market/crash-rebound/schema`

구독자/AI Brain:

- `GET /api/mirofish/market/crash-rebound/latest`

구독자용은 읽기 전용이며, source URL과 수치/신뢰도는 보여주되 관리자용 디버그 필드는 제거한다.

### 6.4 MCP Tool

MiroFish MCP 서버에 읽기 도구로 노출한다.

- `get_market_crash_rebound_status`
- `run_market_crash_rebound_check` 관리자/로컬 trusted 실행만 허용
- `explain_market_rebound_policy`

LLM 어시스턴트는 이 도구를 통해 시장 레짐을 읽고, 임의 검색 대신 저장된 artifact를 우선 사용한다.

## 7. 스케줄러 설계

권장 주기:

| 시점 | 작업 | 목적 |
|---|---|---|
| 08:50 KST | pre-open crash rebound check | 장 시작 전 시장 레짐 |
| 09:20 KST | open confirmation check | KOSPI/환율/수급 초기 확인 |
| 11:30 KST | mid-session check | 급락/반등 이벤트 업데이트 |
| 15:05 KST | closing candidate gate | 종가베팅/Top3에 반영 |
| 16:20 KST | outcome/evidence archive | 학습 루프 저장 |

Scheduler entrypoint:

```python
def run_crash_rebound_market_check() -> bool:
    from app.services.mirofish.crash_rebound import run_crash_rebound_check
    result = run_crash_rebound_check()
    return result.get("status") not in {"error", "blocked"}
```

Telegram:

- 일반 상태는 보내지 않는다.
- `crash`, `capitulation`, `rebound_confirmed` 전환 때만 보낸다.
- 같은 fingerprint는 6시간 쿨다운.
- 메시지는 "시장 상태"와 "스캐너 정책 변화"만 요약한다.

## 8. 프론트엔드 UX 설계

### 8.1 Admin Endpoints / AI Brain Dashboard

기존 `TodaysPipelineCard` 우측 패널 또는 Market Overview 아래에 추가:

```text
Market Rebound Gate
Status: rebound_watch
Score: 64 / Confidence: Medium
YES: 6/14 · Unknown: 2
Policy: risk_adjusted

Core:
VIX -11.4% YES
F&G 18 Extreme Fear
USD/KRW 1392 -0.7%
EWY +1.6%

Next confirmation:
외국인 현물 순매수
KOSPI RSI 30 회복
프로그램 매수 전환
```

### 8.2 Top3 후보 카드 반영

각 후보 카드에 market context badge:

- `Market: crash` -> "시장 리스크 높음"
- `Market: rebound_watch` -> "반등 감시"
- `Market: rebound_confirmed` -> "반등 확인 후보"

후보별 이유:

- "시장 반등 게이트가 열렸지만 외국인 수급 미확인"
- "VIX 완화 + EWY 반등 + 원화 안정으로 스코어 +2.1"
- "시장 리스크 때문에 위험점수 +5 적용"

## 9. GraphRAG / Agent Debate 연결

Crash Rebound artifact는 GraphRAG 분석의 `market_context`로 들어간다.

Agent Debate 입력:

```json
{
  "target": "005930",
  "market_context": {
    "regime": "rebound_watch",
    "score": 64,
    "yes_count": 6,
    "risk_factors": ["USD/KRW still near warning zone"],
    "confirmations_needed": ["foreign cash flow", "program buy"]
  }
}
```

Agent별 역할:

- Macro agent: VIX, S&P500, HY OAS, F&G 해석
- Currency agent: USD/KRW, DXY, 외국인 전송 경로 해석
- Flow agent: 외국인/기관/프로그램 확인
- Derivatives agent: Put/Call, futures, VKOSPI
- Equity risk agent: 개별 후보가 반등장에 적합한지 검증
- CIO: market gate와 candidate evidence를 합성해 BUY/HOLD/REJECT

## 10. 테스트 계획

### 10.1 Unit Tests

신규 테스트:

- `tests/test_crash_rebound.py`

검증 항목:

- VIX 구간 판정
- F&G 구간 판정
- USD/KRW 구간 판정
- 14개 시그널 yes/no/unknown 카운트
- unknown이 많을 때 confidence 하향
- `rebound_confirmed` 조건
- scanner policy multiplier boundary
- stale source 처리

### 10.2 Integration Tests

- `run_crash_rebound_check(dry_run=True)` artifact 생성
- `alpha_scanner.create_scanner_run()` 결과에 market policy 포함
- workflow Top3 결과에 `market_context` 포함
- Telegram 메시지 중복 fingerprint 쿨다운

### 10.3 Frontend Tests

- API normalization
- `Market Rebound Gate` 카드 상태별 렌더링
- unknown source 표시
- Top3 후보 카드 market badge 표시

## 11. 구현 순서

### Phase 1: Read-only Gate

목표: 스코어에 영향 없이 시장 상태 artifact 생성.

작업:

1. `crash_rebound.py` 신규 작성
2. 6개 기본 지표 + 일부 14개 시그널 평가
3. latest/history artifact 저장
4. admin endpoint 추가
5. dashboard read-only 카드 추가
6. 테스트 통과

### Phase 2: Scanner Policy 연결

목표: 알파 스캐너 후보에 제한적 시장 보정 반영.

작업:

1. `alpha_scanner.py` candidate feature에 `market_rebound_context` 추가
2. `market_rebound_adjustment`, `market_risk_penalty` 계산
3. Top3 선정 이유에 market evidence 추가
4. 스캐너 artifact에 source freshness 저장
5. 테스트/드라이런 비교

### Phase 3: Workflow / GraphRAG 연결

목표: 다중 종목 GraphRAG 분석에서 시장 레짐을 공통 컨텍스트로 사용.

작업:

1. `workflow.py` record에 `market_context` 저장
2. Agent Debate prompt/tool input에 market context 포함
3. CIO verdict가 시장 레짐과 후보별 증거 충돌을 명시
4. Telegram Top3 메시지에 market gate 요약 1줄 추가

### Phase 4: Learning Feedback

목표: 반등 시그널이 실제 forward return 개선에 기여했는지 검증.

작업:

1. outcome tracker에 `market_regime_at_detection` 저장
2. `rebound_watch` vs `normal` 성과 비교
3. false positive 원인 태그 저장
4. 학습 정책이 효과 없는 시그널의 가중치를 낮추도록 advisory 생성

## 12. 운영 안전장치

- 자동매매 없음.
- `unknown`이 많은 날은 `confidence=low`로 강제.
- 정책/뉴스/소셜은 score 단독 보정 금지.
- 데이터 소스 2개 이상 stale이면 scanner policy는 `observe_only`.
- Top3 자동 알림은 `BUY` 판정 + market gate confidence medium 이상일 때만 강화.
- 폭락장에서는 "반등 가능성 증가" 표현만 사용하고 "상승 확정" 표현 금지.

## 13. 성공 기준

기능 성공은 화면 추가가 아니라 검출력 개선으로 판단한다.

KPI:

- Top3 5거래일 forward return 평균 개선
- false positive 비율 감소
- 폭락장/반등장 구간별 hit rate 개선
- stale/unknown source 표시율 100%
- Telegram 중복/과잉 알림 감소
- 시장 리스크가 높은 날 후보 알림 품질 개선

## 14. 결론

이 설계는 첨부된 폭락장 반등 체크 프롬프트를 실제 운영 시스템으로 바꾼 구조다.

핵심은 "프롬프트로 시장을 물어보는 기능"이 아니라, 검증 가능한 지표를 구조화하고 알파 스캐너의 후보 검출과 Top3 검증 단계에 시장 레짐을 반영하는 것이다. 초기에는 read-only로 관찰하고, 백테스트와 forward outcome이 충분히 쌓이면 제한적 점수 보정으로 확장하는 방식이 가장 안전하다.
