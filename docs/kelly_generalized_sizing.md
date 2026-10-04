# 일반화 켈리와 검증 손익률 연결

일반화 모드를 기존 오프라인 백테스트에 연결한다. 실제 주문·CIO 승인·차트 유사사례의 운영 비중 정책은 변경하지 않는다. 기본 모델은 기존 empirical이다. 운영 전문 에이전트에 generalized 설정을 전달하면 unsupported_agent_kelly_model로 보류하여 서로 다른 추정치를 같은 승인 근거로 해석하지 않도록 한다.

## 계산과 단위

- `p`: 검증 구간 순이익 표본 / (순이익 + 순손실 표본). 순손익 0 표본은 별도로 기록한다. 기존 자격 판정의 승률은 전체 표본 기준을 유지한다.
- `b`: 검증 표본의 평균 순이익률. 10%는 `0.10`이며 손익비 `b/a`와 다르다.
- `a`: 검증 표본 평균 순손실률의 절댓값. `0 < a <= 1`, `b > 0`이어야 한다.
- 일반화 원값: `f* = p/a - (1-p)/b`.
- 연구 비중: `min(0.20, max(0, f*) * coefficient)` 후 기존 종목 변동성 가드를 적용한다.
- 기본 계수 0.5, VIX가 30 이상이면 설정 계수와 0.25 중 작은 값. 수치가 없는 VIX는 `null`로 기록하고 설정 계수를 쓰는 정책 기본값임을 표시한다.

`p=.60, a=b=1`이면 원값 20%, 하프 10%, 쿼터 5%다. `p=.60, a=b=.10`이면 원값 200%이므로 하프와 쿼터 모두 최종 20% 상한에 도달한다. 쿼터가 항상 최종 비중을 하프의 절반으로 만드는 것은 아니다. 계산 중 반올림하지 않는다.

실현 손익 크기가 서로 다르면 평균 이익·손실로 압축한 generalized는 두 점 근사다. empirical은 전체 실제 순수익률의 `mean(log(1+fR))`를 최대화하며, 두 결과를 보고서에 함께 남긴다. 손실이나 이익 표본 한쪽이 없으면 일반화 근거는 보류한다. 통계·재무 검증을 통과하지 못한 종목은 진단값이 양수여도 연구 비중 0%다.

## 실행

저장소에서 PowerShell:

```powershell
# 기존 empirical 방식
.\.venv\Scripts\python.exe scripts/backtest_winrate_kelly.py --demo --out data/kelly_research/empirical-demo

# 일반화 방식: demo는 합성 데이터이며 실제 검출력의 증거가 아님
.\.venv\Scripts\python.exe scripts/backtest_winrate_kelly.py --demo --kelly-model generalized --out data/kelly_research/generalized-demo

# 실제 가격·시점별 재무·변동성 CSV
.\.venv\Scripts\python.exe scripts/backtest_winrate_kelly.py --prices prices.csv --fundamentals fundamentals.csv --kelly-model generalized --vix-csv vix.csv --train-end 2023-12-29 --validation-end 2024-12-30 --test-end 2025-12-30 --out data/kelly_research/generalized-actual
```

VIX 입력 형식:

```csv
available_date,vix_index,source_id
2024-01-02,29.9,provider-dataset-version
2024-01-03,30.0,provider-dataset-version
```

`available_date`는 관측 날짜가 아닌 의사결정에 **이용 가능해진 날짜**다. 날짜·출처·유한한 비음수 값은 필수이며 같은 이용가능일의 중복 자료는 거부한다. CSV 날짜의 진위를 독립 검증했다고 주장하지 않는다. 한국장 개장 전에 공개되지 않은 미국 VIX 자료라면 그 다음 이용가능일을 기록해야 한다. 검증 비중은 검증 종료일까지 알려진 자료로 동결하며, 테스트 체결은 이전 시장일까지 이용 가능했던 자료만 사용한다. 테스트 구간에 고위험 VIX가 도착하면 일일 재조정 설정과 관계없이 위험을 축소할 수 있지만 동결된 초기 비중 위로 늘리지 않는다.

가격은 신호 다음 시장일에 진입하고 설정 보유기간 후 청산한다. 표본은 수수료·슬리피지·입력 매도세를 차감한 순손익이다. 기본 매도세 0은 현행 세율을 뜻하지 않는다. 최종 테스트 수익률을 종목 선택이나 켈리 추정에 사용하지 않는다.

## Python / 데이터 프레임

공유 계산 모듈: `app/services/mirofish/kelly_position.py`.

```python
from app.services.mirofish.kelly_position import calculate_kelly_position, two_point_kelly

assert calculate_kelly_position(.60, b=.10, a=.10, vix_index=35) == .20
trace = two_point_kelly([.10, .08, -.05, 0.0])  # 비용 차감 후 실제 검증 표본

# pandas는 선택 사항이며 실행 스크립트에 필수 의존성을 추가하지 않는다.
import pandas as pd
calculations = pd.read_csv('data/kelly_research/generalized-actual/kelly_calculations.csv',
                           dtype={'symbol': str})
```

순수 계산 함수는 표본의 통계적 유의성을 승인하지 않는다. 근거 검증과 실제 비중 적용은 `run_research(..., config={'kelly_model': 'generalized'}, market_volatility=records)`가 담당한다.

출력: `report.html`, 원본 계산 `report.json`, 계산 단계와 표본 수 `kelly_calculations.csv`, 자격 판정 `qualification.csv`, 가상 체결 `fills.csv`, 일별 자산 `equity_curve.csv`. 코드는 초과 레버리지·숏·실제 주문을 실행하지 않는다.

켈리의 최적성은 가정된 분포의 로그성장에 관한 것이다. 표본 오차·시장 변화·갭 하락·거래비용·종목 간 상관을 없애지 않는다. 하프켈리 수익률 75%나 최대 낙폭 절반은 일반적 보장이 아니며 20% 상한도 파산 위험을 0으로 만들지 않는다.

근거: [Thorp의 주식시장 켈리 연구](https://www.edwardothorp.com/wp-content/uploads/2016/11/TheKellyCriterionAndTheStockMarket.pdf), [Busseti·Ryu·Boyd의 위험 제약 켈리 연구](https://stanford.edu/~boyd/papers/kelly.html).
