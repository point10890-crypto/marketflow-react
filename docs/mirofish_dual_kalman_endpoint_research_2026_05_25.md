# MiroFish Dual Kalman Endpoint Research

작성일: 2026-05-25
검토 파일: `C:\Users\dynas\Downloads\deep-research-report2.md`
대상: MarketFlow / MiroFish Alpha Scanner / GraphRAG Analysis

## 1. 결론

`deep-research-report2.md`의 핵심은 듀얼 칼만 필터를 주가 방향 예언기로 쓰지 말고, 알파스캐너 후보의 노이즈, 동적 계수, 잠재 변동성, 신호 불확실성을 추정하는 검증 계층으로 쓰라는 것이다.

현재 MarketFlow에는 이미 다음 체인이 있다.

```text
Alpha Scanner
  -> scanner runs / feature vectors / evidence ledger
  -> workflow scan-analyze
  -> GraphRAG batch analysis
  -> Top3
  -> Telegram / outcomes
```

따라서 새 엔드포인트는 MCP 자동화 자체가 아니라, 좋은 종목 검출력을 높이기 위해 아래 위치에 붙이는 것이 맞다.

```text
Alpha Scanner 후보
  -> Dual Kalman Signal Gate
  -> GraphRAG / 6-Agent / CIO verdict
  -> Final Top3
  -> outcome validation
```

## 2. 보고서에서 채택할 원칙

| 원칙 | MarketFlow 적용 |
|---|---|
| 원시 가격 예측 금지 | 종가 방향 예측이 아니라 수익률, 스프레드, 동적 계수, 변동성 추정에 사용 |
| online filter only | 라이브 신호는 `x_t|t`만 사용하고 smoother 결과 금지 |
| 작은 상태벡터 | 6~12개 이하의 해석 가능한 피처로 시작 |
| 작은 파라미터벡터 | `log_q`, `log_r`, `lambda_volatility`, `lambda_volume`, decay 정도로 제한 |
| one-step validation | walk-forward, 비용 차감, look-ahead bias 방지 |
| 이벤트 기반 확장 | KIS/TradingView/가격 파일 갱신 이벤트와 연결, REST 남발 금지 |

## 3. 우선 붙일 엔드포인트 후보

### P0. Dual Kalman 상태/헬스 엔드포인트

```http
GET /api/admin/mirofish/kalman/status
```

목적:

- DKF 엔진 사용 가능 여부 확인
- 입력 소스 신선도 확인
- 마지막 run / 마지막 backtest / 모델 안정성 요약

응답 핵심 필드:

```json
{
  "service": "mirofish-dual-kalman",
  "ready": true,
  "mode": "scanner_signal_gate",
  "latest_run_id": "dkf_...",
  "source_freshness": {
    "daily_prices": "fresh",
    "scanner_run": "fresh",
    "kis": "optional",
    "tradingview": "optional"
  },
  "model_health": {
    "innovation_warning_count": 0,
    "divergence_count": 0,
    "lookahead_safe": true
  }
}
```

서비스 위치:

- `app/services/mirofish/dual_kalman.py`
- route: `app/routes/admin_mirofish.py`

### P0. 스캐너 후보 DKF 배치 분석

```http
POST /api/admin/mirofish/kalman/runs
```

목적:

- 최신 scanner run 또는 지정 scanner run의 후보들을 DKF로 재평가
- live ranking을 바로 변경하지 않고 shadow score와 gate 결과를 artifact로 저장

요청:

```json
{
  "scanner_run_id": "latest",
  "symbols": ["005930", "034020"],
  "limit": 20,
  "horizon_days": 5,
  "profile": "linear_dkf_v1",
  "use_kis_live": false,
  "commit_to_scanner": false
}
```

응답:

```json
{
  "id": "dkf_20260525_...",
  "status": "completed",
  "scanner_run_id": "mfas_...",
  "candidate_count": 20,
  "lookahead_safe": true,
  "links": {
    "self": "/api/admin/mirofish/kalman/runs/dkf_...",
    "signals": "/api/admin/mirofish/kalman/runs/dkf_.../signals"
  }
}
```

저장 위치:

```text
data/admin_mirofish/kalman_runs/{run_id}/run.json
data/admin_mirofish/kalman_runs/{run_id}/signals.json
data/admin_mirofish/kalman_runs/{run_id}/diagnostics.json
```

### P0. DKF 신호 조회

```http
GET /api/admin/mirofish/kalman/runs/{run_id}/signals
```

목적:

- 후보별 DKF 결과를 Alpha Board와 MCP tool에서 읽는다.

후보별 필드:

```json
{
  "symbol": "005930",
  "name": "삼성전자",
  "market": "KOSPI",
  "scanner": {
    "alpha_score": 74,
    "risk_score": 17,
    "ranking_score": 64.65
  },
  "kalman": {
    "latent_return_z": 1.24,
    "fair_value_gap_z": 0.72,
    "volatility_state": "normal",
    "innovation_z": 0.81,
    "signal_confidence": 0.67,
    "uncertainty_penalty": 4.2,
    "gate": "pass"
  },
  "score_delta": 3.1,
  "shadow_alpha_score": 77.1,
  "reason": "scanner momentum is supported by stable latent trend and normal innovation"
}
```

핵심:

- `gate=pass`: GraphRAG Top3 후보로 넘길 수 있음
- `gate=watch`: 분석은 가능하지만 확신도 제한
- `gate=block`: 급등 노이즈, 과도한 innovation, 변동성 폭주 등으로 Top3 자동화에서 제외 또는 감점

### P0. 기존 workflow에 DKF 게이트 연결

권장 방식은 새 워크플로우 엔드포인트를 너무 늘리지 않고 기존 엔드포인트를 확장하는 것이다.

```http
POST /api/admin/mirofish/workflow/scan-analyze
```

추가 payload:

```json
{
  "limit": 5,
  "top_n": 3,
  "quality_gate": "dual_kalman",
  "kalman_profile": "linear_dkf_v1",
  "min_kalman_confidence": 0.55,
  "block_high_innovation": true
}
```

효과:

```text
scanner candidates
  -> eligible candidates
  -> DKF signal gate
  -> GraphRAG batch only for gated names
  -> final_score에 DKF score_delta 반영
  -> Top3 Telegram
```

별도 엔드포인트를 원하면 다음 이름이 적절하다.

```http
POST /api/admin/mirofish/workflow/scan-kalman-analyze
```

하지만 운영상으로는 기존 `scan-analyze`에 옵션을 붙이는 쪽이 UI와 scheduler 변경량이 작다.

## 4. P1 엔드포인트

### P1. 단일 종목 DKF state 조회

```http
GET /api/admin/mirofish/kalman/targets/{symbol}/state
```

목적:

- GraphRAG Analysis 화면에서 특정 종목의 현재 상태를 설명한다.
- 최종판결 카드에 “이 판결이 어떤 종목의 어떤 상태를 보고 나온 것인지”를 더 명확히 붙인다.

출력:

- 잠재 추세
- 공정가치 괴리
- 변동성 상태
- observation noise
- 마지막 업데이트 시각
- source freshness

### P1. DKF walk-forward backtest

```http
POST /api/admin/mirofish/kalman/backtests
```

목적:

- live score에 반영하기 전, DKF gate가 실제로 false positive를 줄이는지 검증한다.

요청:

```json
{
  "scanner_run_window_days": 60,
  "horizons": [1, 3, 5, 20],
  "cost_bps": 20,
  "slippage_bps": 15,
  "profile": "linear_dkf_v1"
}
```

필수 검증 지표:

- T+1/T+3/T+5/T+20 hit rate
- average forward return
- benchmark-relative return
- max drawdown
- turnover
- false-positive reduction
- gate별 성과: pass/watch/block
- lookahead_safe 여부

### P1. DKF artifact 조회

```http
GET /api/admin/mirofish/kalman/runs/{run_id}/diagnostics
GET /api/admin/mirofish/kalman/runs/{run_id}/feature-matrix
```

목적:

- 디버깅과 MCP agent 분석용.
- feature, innovation, covariance warning을 따로 확인한다.

## 5. P2 MCP tools/resources

FastMCP에 붙일 도구:

```text
get_dual_kalman_status
run_dual_kalman_batch
get_dual_kalman_signals
get_dual_kalman_target_state
run_dual_kalman_backtest
run_scan_kalman_top3_workflow
```

MCP resources:

```text
mirofish://kalman/status
mirofish://kalman/latest
mirofish://kalman/signals/latest
mirofish://kalman/backtests/latest
```

보안 원칙:

- 기본은 read-only.
- `run_dual_kalman_batch`는 artifact 생성만 허용.
- scanner live ranking 변경은 별도 `commit_to_scanner=true`와 관리자 권한이 필요.
- Telegram 전송은 기존 confirmation guard를 그대로 따른다.

## 6. 점수 반영 설계

초기에는 live score를 바꾸지 않고 `shadow_alpha_score`만 저장한다.

```text
kalman_score_delta =
  + latent_return_confirmation
  + fair_value_gap_confirmation
  - innovation_spike_penalty
  - volatility_state_penalty
  - low_confidence_penalty
```

워크플로우 final score에는 다음처럼 작은 비중만 반영한다.

```text
final_score_v3 =
  final_score_v2
+ min(max(kalman_score_delta, -8), +8)
```

운영 전환 조건:

1. DKF gate가 `block`으로 분류한 후보의 forward 성과가 실제로 낮다.
2. `pass` 후보가 기존 Top3보다 T+5/T+20 성과가 좋다.
3. 비용 차감 후에도 false positive 감소 효과가 있다.
4. 적어도 30~50개 이상 workflow sample이 쌓인다.

## 7. 구현 순서

### 1단계: read-only DKF prototype

파일:

```text
app/services/mirofish/dual_kalman.py
tests/test_mirofish_dual_kalman.py
```

작업:

- `daily_prices.csv`에서 후보별 최근 120~250일 OHLCV 로드
- 수익률, 5/20일 모멘텀, 변동성, 거래량 surprise feature 생성
- linear Kalman baseline 구현
- synthetic recovery test 추가

### 2단계: route + artifact

파일:

```text
app/routes/admin_mirofish.py
app/services/mirofish/__init__.py
tests/test_admin_mirofish_dual_kalman.py
```

엔드포인트:

```text
GET  /api/admin/mirofish/kalman/status
POST /api/admin/mirofish/kalman/runs
GET  /api/admin/mirofish/kalman/runs/{run_id}
GET  /api/admin/mirofish/kalman/runs/{run_id}/signals
```

### 3단계: workflow gate

파일:

```text
app/services/mirofish/workflow.py
tests/test_mirofish_workflow_dual_kalman_gate.py
```

작업:

- `quality_gate='dual_kalman'` 옵션 추가
- GraphRAG batch 전에 DKF gate 실행
- result `score_breakdown.inputs.kalman`과 `components.kalman` 추가

### 4단계: UI / MCP

파일:

```text
frontend-react/src/lib/mirofishApi.ts
frontend-react/src/pages/admin/AdminEndpointsPage.tsx
app/services/mirofish/mcp_server.py
app/services/mirofish/autonomous_mcp.py
```

UI:

- Alpha Board 후보 카드에 `DKF pass/watch/block`
- Top3 workflow control plane에 `Kalman Gate`
- Endpoint card: `Dual Kalman Gate`

### 5단계: backtest

파일:

```text
app/services/mirofish/dual_kalman_backtest.py
tests/test_mirofish_dual_kalman_backtest.py
```

작업:

- walk-forward only
- smoothing 금지
- 비용/슬리피지 반영
- gate별 forward outcome 비교

## 8. 최종 권고

가장 먼저 붙일 엔드포인트는 `POST /api/admin/mirofish/kalman/runs`와 `GET /api/admin/mirofish/kalman/runs/{run_id}/signals`이다. 이유는 단순하다. 이 둘은 기존 스캐너와 GraphRAG를 깨지 않고, DKF가 실제로 좋은 종목 검출에 도움이 되는지 shadow로 검증할 수 있다.

그 다음 `quality_gate='dual_kalman'`를 `workflow/scan-analyze`에 붙인다. 이때도 live ranking 전체를 바꾸는 것이 아니라, GraphRAG로 넘길 후보의 우선순위와 confidence cap을 조정하는 보조 게이트부터 시작해야 한다.

이 구조가 성공하면 MiroFish의 목적에 직접 연결된다.

```text
더 많은 자동화가 아니라,
더 나은 후보 검출,
더 빠른 거짓 신호 제거,
더 검증 가능한 Top3 선별.
```
