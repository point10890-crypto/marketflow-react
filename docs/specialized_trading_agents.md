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

`--out`에 `report.json`과 `report.html`이 생성됩니다.

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
