# Alpha Scanner Dual Kalman Harness

작성일: 2026-05-25
대상: MarketFlow / MiroFish Alpha Scanner

## 1. 목표

이번 작업의 목표는 듀얼 칼만 필터 기능 자체가 아니다.

목표는 알파스캐너가 수익 가능성이 높은 Top3 후보를 더 정확히 검출하도록, 기존 후보의 신호 안정성, 노이즈, 변동성, 동적 추세를 정량 검증하는 shadow gate를 추가하는 것이다.

```text
scanner 후보
  -> dual kalman pass/watch/block
  -> GraphRAG Top3
  -> outcome tracker
  -> backtest feedback
```

## 2. 하네스 규율

1. Live ranking 대체 금지
   - 초기 구현은 `shadow_alpha_score`, `score_delta`, `gate`만 생성한다.
   - 기존 alpha/risk score의 주도권을 빼앗지 않는다.

2. Look-ahead bias 금지
   - `daily_prices.csv`는 분석 기준 시점까지의 row만 사용한다.
   - smoother, 전체 표본 정규화, 미래 성과 라벨을 live signal에 사용하지 않는다.

3. Top3 검출 강화 기준
   - `pass`: GraphRAG 자동 분석 우선순위를 높일 수 있음.
   - `watch`: 분석은 가능하되 confidence cap을 둠.
   - `block`: 순간 급등, innovation spike, 과열 변동성 등으로 자동 Top3 후보에서 제외 또는 강한 감점.

4. 성과 검증 전 과신 금지
   - DKF 결과가 실제 T+5/T+20 성과 개선을 보일 때만 live score 반영 비중을 키운다.

5. 수치 생성 책임
   - LLM은 숫자를 만들지 않는다.
   - DKF 수치와 score delta는 가격/거래량/스캐너 artifact에서 계산한다.

## 3. 종료 조건

- DKF service unit test 통과
- admin route registration test 통과
- workflow quality gate focused test 통과
- `python -m compileall app/services/mirofish/dual_kalman.py app/routes/admin_mirofish.py app/services/mirofish/workflow.py` 통과

## 4. 이번 구현 범위

P0만 구현한다.

- `GET /api/admin/mirofish/kalman/status`
- `POST /api/admin/mirofish/kalman/runs`
- `GET /api/admin/mirofish/kalman/runs/{run_id}`
- `GET /api/admin/mirofish/kalman/runs/{run_id}/signals`
- `quality_gate=dual_kalman` workflow 옵션

P1 backtest endpoint와 UI card는 다음 작업으로 남긴다.
