# 특화 주식 분석 에이전트 실행 안내

데이터 → 퀀트 → 위험 관리 → CIO → 가상 체결을 독립 Python 에이전트로 구현했습니다. 각 에이전트는 `asyncio.Queue`로 메시지를 받고 자신의 판정만 추가합니다. SQLite에 완료 단계를 기록하므로 중단 후 같은 입력·실행 ID로 재개할 수 있습니다. 새 API 키, LLM 호출, Celery/Redis 서버는 필요하지 않습니다.

이 버전은 연구와 **가상 체결 전용**입니다. 증권사 주문 API를 호출하지 않습니다. 일일 실행 제한은 저장소에서 강제하며, 자동 예약 작업은 설치하지 않습니다. 운영 연결 전에 검증된 자료와 실제 계좌·체결 계약이 별도로 필요합니다.

## 구성

| 담당 | 구현 | 판정 및 전달 내용 |
|---|---|---|
| 데이터 감시 | `app/services/mirofish/trading_agents/data_agent.py` | 시총 순으로 TOP100을 먼저 확정하고 현재 재무 안전성 검사. 가격·재무·출처 검증 실패 시 보류 |
| 퀀트 검출 | `quant_agent.py` | 기존 Kelly 연구 엔진으로 학습/검증 통과 여부를 동결. 현재 날짜의 -2σ 신호만 신규 후보로 최대 3종목 전달 |
| 비중·위험 | `risk_agent.py` | 실현 순수익 표본의 켈리 추정값 × 최대 0.5. 종목 20%, 전체 60%, 현금 40% 한도. 높은 사전 변동성에서는 추가 절반 축소 |
| CIO 조정 | `orchestrator.py` | 출처·통계·종목 식별·비중·실행 가격을 다시 검사하고 승인/보류. 완료 메시지 재사용, 단계 제한 시간 및 오류 기록 |
| 가상 체결 | `execution_agent.py`, `store.py` | 저장된 CIO 승인과 비중 해시 확인. 매도 후 매수, 비용 후 순자산 기준 비중 계산. 계좌·날짜당 한 번만 원자적으로 반영 |

현재 시총 우량주를 과거에 적용한 연구에는 생존 편향이 남습니다. 부실주 필터만으로 생존 편향이 제거되지는 않습니다. -2σ는 경험적 수익률 패턴 가설이며 저평가나 반등을 보장하지 않습니다. 20%는 상한으로, 항상 배정되는 고정 최적 비중이 아닙니다.

## 바로 실행

저장소 루트에서 실행합니다. 아래 명령은 같은 `--run-id`와 같은 입력으로 반복해도 추가 가상 주문을 만들지 않습니다.

```powershell
python scripts/run_specialized_trading_agents.py --demo `
  --run-id specialized-demo-20261003 `
  --database data/kelly_research/trading_agents/verification/demo.sqlite `
  --out data/kelly_research/trading_agents/verification/demo
```

`--demo`는 이익 패턴을 인위적으로 만든 합성 자료입니다. 종목 코드와 가격도 테스트용입니다. 통계 문턱을 통과하고 가상 체결까지 연결되는지 확인하는 용도이며, 실제 시장 검출력이나 성과를 뜻하지 않습니다. 휴일 달력이 없는 합성 자료의 다음 평일 가격 가정 역시 실거래 가격이 아닙니다.

확보한 실제 자료의 승인 상태를 점검합니다.

```powershell
python scripts/run_specialized_trading_agents.py `
  --acquired-data data/kelly_research/long_history_20261002 `
  --cohort data/kelly_research/large_cap_20261001_v2/report.json `
  --run-id acquired-audit-20261003-v2 `
  --database data/kelly_research/trading_agents/verification/acquired-v2.sqlite `
  --out data/kelly_research/trading_agents/verification/acquired-v2
```

실제 자료 점검 모드는 CSV/재무 파일 해시와 TOP100 일치를 검사합니다. 아직 검증되지 않은 가격 보정·최초 공시 수치를 `true`로 승격하지 않습니다. 실제 수집 시각을 보존하고, 수집 시각이 없는 출처는 누락으로 표시합니다. 보고서 생성 시각을 수집 시각으로 대신하지 않습니다. 대량 과거 행을 퀀트에 전달하지 않고 보류 사유를 기록합니다. 확보 완료와 투자 근거 승인 완료는 다른 상태입니다. 확보 내역과 남은 검증은 [historical data guide](kelly_historical_data_acquisition.md)에 있습니다.

검증된 자체 입력은 명시적으로 전달합니다.

```powershell
python scripts/run_specialized_trading_agents.py --request path/to/paper_request.json `
  --run-id my-paper-session-001 --database data/kelly_research/trading_agents/my-account.sqlite `
  --out data/kelly_research/trading_agents/my-session
```

`--request`는 다운로드나 환경변수 조회를 수행하지 않습니다. 동일 계좌의 후속 날짜에는 이전 보고서의 `execution.portfolio`를 입력해야 합니다. 저장된 계좌와 다른 잔고를 주면 새 체결을 거부합니다. 같은 계좌·같은 날짜로 다른 실행 ID를 주면 `duplicate_day`로 추가 체결을 막습니다. 이 CLI는 날짜별 실제 거래소 세션을 스스로 추정하지 않으므로 다음 거래일과 실행 가능한 가격을 사용자가 제공해야 합니다.

기존 Python 작업에서도 같은 인터페이스를 사용할 수 있습니다. CLI와 동일하게 명시적인 입력·실행 ID를 전달하고 보고서 상태를 확인합니다.

```python
from app.services.mirofish.trading_agents.orchestrator import TradingOrchestrator

orchestrator = TradingOrchestrator("data/kelly_research/trading_agents/my-account.sqlite")
report = await orchestrator.run(request, run_id="my-paper-session-001")
```

입력 필드 전체 계약은 [architecture specification](superpowers/specs/2026-10-03-specialized-trading-agents-design.md)에 있습니다. 핵심은 다음과 같습니다.

- `as_of`, 날짜가 있는 `universe/current_financials/prices/fundamentals`, 순서가 엄격한 `splits`를 제공합니다. 학습 < 검증 < 최종 기간 ≤ 관측 날짜입니다.
- `evidence`에 가격 보정·재무 최초 공시 검증 여부와 4개 출처의 실제 수집 시각·SHA-256을 제공합니다. 플래그만 바꿔 검증을 대신하면 안 됩니다. 미래 수집 시각은 차단됩니다. 합성 입력에는 `synthetic/trusted_fixture=true`가 필요합니다.
- 신규 진입에는 관측일의 신호와 통계 통과 근거가 필요합니다. 과거 신호만으로 새 진입하지 않습니다. 기존 검증 보유주는 재조정할 수 있고, 검증 완료 후 자격을 잃은 보유주는 가상 청산할 수 있습니다. 자료 부족·계산 실패를 청산 신호로 해석하지 않습니다.
- `execution.date`는 `as_of`보다 뒤이며 각 가격에는 같은 날짜·양수 가격·양수 거래량·출처를 제공합니다. 실행 가격은 과거 자격 선별에 사용하지 않습니다.
- `portfolio`는 현금과 코드별 수량, `account_id`는 가상 계좌 식별자입니다. 수수료·슬리피지·매도세 가정은 bp 단위입니다. 예제의 5/10/0은 실험 가정이며 현행 세율 안내가 아닙니다.
- `config.risk`는 기본 위험 한도를 강화할 수 있습니다. 연구용 통계 문턱을 낮춰도 CIO의 최소 표본 30, 관측 승률 60%, Wilson 하한 60%, 손익비 1 이상, 양의 순기대수익 기준은 낮아지지 않습니다.
- API 키·비밀번호·접근 토큰 필드는 메시지와 저장소에 들어가기 전에 거부됩니다.

## 결과 해석

`--out`에 원본 실행 결과 `report.json`, 켈리 귀결 근거 `kelly_attribution.json`, 표시용 `report.html`이 생성됩니다. 별도 켈리 표시 파일은 동결된 메시지와 원장을 수정하지 않습니다.

보고서 맨 위 **실제 조사 종목**에서 입력 시총 순위·종목명·코드·시장·재무 1차 판정·승률 검사 상태·켈리 승인 목표를 확인합니다. 재무 통과 종목은 바로 보이고 보류 종목은 사유와 함께 펼칠 수 있습니다. 2026-10-01 입력 TOP100의 52종목은 재무 1차 통과이고, 가격패턴·승률·켈리 최종 검사 미실행 상태입니다. 매수 추천이나 검증된 60% 승률 종목 목록으로 해석하지 않습니다. 미계산 승률·비중을 0%로 채우지 않습니다. 합성 실행에는 **합성 검증 종목**으로 명확히 표시합니다.

실제 목록 표시 추가 후 켈리·목록·CLI 관련 38개 검사가 통과했습니다. 저장된 실제 보고서의 100종목명·코드 표시, 재무 통과 52/보류 48, 100행의 켈리 미계산과 CIO 승인 목표 0, 보고서·원장 보존을 확인했습니다.

### 검출 결과를 켈리 비중으로 읽기

화면은 종목의 검증 표본·승률·손익비를 먼저 제시하고 다음 순서로 최종 목표 비중과 금액을 보여줍니다.

1. 검증 기간의 비용 차감 주식 수익률 `R_i`로 `mean(log(1 + f * R_i))`를 최대화하는 `0 ≤ f ≤ 1`의 경험적 켈리 추정값을 사용합니다. 학습/검증 자격이 통과한 뒤 **검증 기간만** 추정에 사용합니다. 최종 평가 기간 수익률은 비중 계산에 사용하지 않습니다.
2. 추정값에 기록된 안전 계수(기본 0.5, 하프 켈리)를 곱합니다.
3. 종목 비중 상한(기본 20%)을 적용합니다.
4. 현재 사전 변동성이 기준(기본 3%)을 초과하면 **상한 적용 후** 비중을 추가 절반 축소합니다.
5. 전체 노출과 최소 현금 한도에 맞춰 공통 비율로 축소합니다. 이 값이 `risk.targets`와 일치할 때만 비중 귀결을 표시합니다.

이항식 `f = p - (1 - p) / b`의 설명용 예시인 `p=60%, b=1 → 20%, 하프 켈리 10%`를 별도로 표시합니다. 이 식은 실패하면 베팅액 전액을 잃는 두 결과 가정입니다. 주식은 실제 이익·손실 크기와 순수익 분포가 다르므로 이항식 진단값을 주식 비중으로 대체하지 않습니다. 표본에 0% 수익이 있으면 진단값의 `1-p`는 그 표본도 실패로 단순화합니다. 경험적 계산은 개별 순수익을 그대로 사용합니다. 켈리는 손실이나 파산 위험의 제거를 보장하지 않습니다.

합성 종목 A의 기록은 검증 31표본, 승률 80.65%, 손익비 1.889, 제약 켈리 100% → 하프 50% → 종목 상한 20%입니다. 현재 변동성 2.27%는 3% 이하이고 전체 노출 한도도 넘지 않아 최종 비중 20%가 됩니다. 초기 가상 자산 100만원의 비용 전 배정 계획은 20만원, 비용 후 순자산 999,699.99원의 목표 평가액은 199,940.00원입니다. 매수 현금 지출 200,240.01원에는 비용이 포함되어 두 금액과 다릅니다. **합성 자료의 동작 예시**이며 실제 종목 검출이나 투자 성과가 아닙니다.

통계 자격만 통과하고 현재 신규 진입 신호가 없는 종목, 손익비 기준 미달 종목, 비교 지수도 별도 판정표에서 배정되지 않는 이유를 보여줍니다. 데이터 검증 미완료이면 실제 승률·켈리·승인 비중·금액은 대기 상태입니다. CIO 보류 시 계산은 검토용이고 승인 금액을 표시하지 않습니다. 당일 중복 실행은 추가 체결 0건으로 표시하며 비용 후 순자산이 없는 기록에서 평가액을 만들지 않습니다.

완료된 실행을 다시 수집하거나 거래하지 않고 새 표시로 재출력할 수 있습니다.

```powershell
python scripts/run_specialized_trading_agents.py --render-report `
  data/kelly_research/trading_agents/verification/demo/report.json `
  --out data/kelly_research/trading_agents/kelly-view
```

이 모드는 실행 ID나 데이터베이스를 필요로 하지 않으며 에이전트를 호출하거나 원장을 열지 않습니다. 같은 원본 디렉터리에 출력해도 원본 `report.json` 바이트를 보존합니다. 출력 JSON을 원장과 대조해 진본 인증하는 기능은 아니며, 저장된 Risk 계산의 단계별 일치 여부를 표시합니다.

켈리 표시 추가 검증에서 관련 에이전트 회귀 검사 183개, 독립 검토 수정 후 최종 표시·원본 보존 검사 22개가 통과했습니다. 합성 실행·실제 자료 보류·당일 중복의 기존 보고서를 재출력하여 원본 보고서와 SQLite의 바이트 보존 및 새 실행 없음도 확인했습니다. 강화된 현금 100% 정책의 최종 비중 0%도 정상 계산 경로로 표시합니다. 입력이 출력 `kelly_attribution.json`이나 HTML/임시 HTML 경로와 충돌하면 쓰기 전에 거부합니다.

| 필드 | 의미 |
|---|---|
| `data.status` 및 `reasons` | 자료가 승인 가능한지. `blocked`이면 다음 에이전트는 검출·주문을 진행하지 않음 |
| `quant.qualified` | 학습/검증 통과 근거. 최종 기간 승률로 선별하지 않음 |
| `quant.candidates` | 오늘 신규 진입 검토 가능한 검출 종목. 0~3개가 정상 |
| `risk.targets` | 비용 반영 전 목표 비중. 0은 검증된 기존 보유분 청산 목표 |
| `approval.decision/reason` | CIO의 최종 승인 또는 구체적 보류 이유 |
| `execution.fills/portfolio` | 실제 주문과 무관한 가상 체결 및 비용 후 잔고. 연구용 분수 수량 허용 |
| `stages` | 단계별 메시지 해시와 부모 연결. 재개 시 이를 검증하며 완료 단계를 다시 계산하지 않음 |

`status=completed`는 **가상 실행 완료**입니다. 미래 승률을 인증하지 않습니다. `held`는 안전하게 보류한 정상 결과이고 CLI 종료 코드는 0입니다. 입력·저장소·단계 오류는 종료 코드 2이며 민감한 원문을 출력하지 않고 오류 유형만 알립니다.

## 확인한 결과

2026-10-03 실행에서 합성 자료는 4개 테스트 종목 중 현재 후보 1개, 비용을 반영한 가상 매수 1건을 생성했습니다. 동일 실행 재개와 같은 날 새 실행에서 중복 체결이 차단됩니다.

실제 확보 자료 점검은 현재 시총 TOP100, 재무 통과 52개에서 **보류·체결 0건**입니다. 가격 421,295행과 재무 6,880건 확보만으로 검증 완료를 선언하지 않습니다. 현재 투자 가능한 실종목을 이 시스템으로 검출했다는 뜻은 아닙니다.

주요 회귀 검사는 해시 변조, 출처 누락, 잘못된 Wilson 하한, 높은 변동성, 청산 목표, 미래 가격, 비용 후 한도, 저장 중 실패 rollback, 동시 실행, 날짜 중복, 잔고 불일치, 중단 후 복구를 포함합니다.

```powershell
python -m pytest tests/test_trading_data_agent.py tests/test_trading_quant_risk_agents.py `
  tests/test_trading_execution_store.py tests/test_trading_orchestrator.py `
  tests/scripts/test_run_specialized_trading_agents.py -q
```

2026-10-03 최종 전체 Python 검사는 **3,279개 통과, 4개 건너뜀, 실패 0개**입니다. 처음 전체 실행은 OpenAI/Pydantic 모델 import 중 Windows native 예외 `0xc000001d`로 종료됐으며, 원인은 확인되지 않았습니다. 이 사건에 대한 소스·의존성 변경 없이 전체 재실행이 통과했습니다. JUnit과 재실행 로그, 실제 CLI·저장소 검증은 `data/kelly_research/verification/` 및 `data/kelly_research/trading_agents/verification/`에 보존했습니다.
