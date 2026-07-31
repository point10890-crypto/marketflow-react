# Goodrich 검출 파이프라인 점검 · 게이트 정리 · 측정 하네스 구축

작성일: 2026-07-30
대상: `https://bit-man.net/dashboard/ai-bain/goodrich`
저장소: `C:\bitman_marketfloww` (main)
커밋 범위: `1b296c6` → `eccf2bc` (6커밋, 10파일, +1,144 / -67)
배포: 미니PC(192.168.55.103) `eccf2bc` 반영 완료

---

## 0. 요약

세 단계로 진행했다.

1. **점검** — 워크플로우와 분석 파이프라인을 읽고 결함 10건을 식별했다.
2. **폐기 수정** — 그중 최우선 결함(recovery-leader 우회 경로)을 제거하고 게이트 정의를 단일화했다.
3. **측정 하네스** — "작동하는가"가 아니라 "수익 나는 종목을 고르는가"를 재기 위한 원장·평가·벤치마크 기반을 세우고, 프로덕션 실데이터로 첫 실측을 냈다.

가장 중요한 결과는 3단계에서 나왔다: **후보 유니버스에는 알파가 있는데 랭킹 함수가 그것을 뒤집고 있다.**

---

## 1. 실제 파이프라인 구조

```
브라우저 /dashboard/ai-bain/goodrich        App.tsx:186 (ProGuard + lazy)
  ├─ GET  /api/admin/mirofish/goodrich/fund-manager            ┐
  ├─ GET  .../history?limit=10                                 ├ Promise.all
  ├─ GET  .../performance?window_days=30                       ┘
  └─ POST .../research                          수동 "시장 다시 분석"
        ↓ Flask 인증 경계 (admin_or_aibain_required)
        ↓ goodrich_client.run_research()
            1) kis_screener.run_screening(force=True) → candidate_pool
            2) rows[:20] 각각 get_price_trend_metrics() → 추세 게이트
            3) 후보 <3개면 stand_aside
            4) run_multi_mcp_analysis() → profit gate → LLM 심층분석 → CIO 승인
            5) CIO 승인 <3개면 stand_aside
            6) POST Goodrich FastAPI /v1/fund-manager/research (90s)
            7) _validate_market_leader_contract() 계약 검증

별도: schtasks 30분 주기 → scripts/run_goodrich_intraday_cycle.py
      → monitor + research + 텔레그램 (+ 이번에 추가된 원장 기록)
```

인프라 확인 사항:

- 미니PC는 **Windows**(10.0.26100)다. `deploy/` 아래 PowerShell·schtasks 스크립트가 그대로 유효하다.
- `Goodrich-TradingOS`(uvicorn 127.0.0.1:8000)와 `MarketFlow-Goodrich-30Min` 모두 미니PC에 등록·가동 중이다.
- Goodrich 원본 API는 인증이 없어 SSH로 직접 조회 가능하다. 성과 원자료를 뽑을 때 이 경로를 썼다.

---

## 2. 점검에서 나온 결함

### 2.1 recovery-leader가 구조적으로 죽은 경로였다 (수정 완료)

`goodrich_client.py`는 `trend_passed OR recovery_leader_passed`로 후보를 통과시켰지만,
그 후보가 넘어가는 `multi_mcp_orchestrator._evidence_packet()`은 **완화 없는 원본 게이트**를 다시 적용했다.
실제 코드로 재현한 결과:

```
profit_gate.passed = False
failed checks      = ['positive_5d', 'positive_20d', 'above_ma20', 'trend_score', 'drawdown']
```

recovery-leader로만 통과한 종목은 정의상 이 중 최소 하나를 못 넘기므로
심층분석 대상에서 제외되고 → CIO 승인 목록에 없고 → 최종 필터에서 걸러진다.
즉 **프로덕션에서 단 한 번도 발동할 수 없는 기능**이었다.

부작용이 더 나빴다. recovery-leader가 후보 수를 3개 이상으로 부풀려 1차 stand_aside를 통과시키므로,
**불필요하게 Multi-MCP LLM 심층분석 비용을 지불한 뒤** `multi_mcp_cio_approved_below_minimum`이라는
엉뚱한 사유로 대기 전환됐다.

기존 테스트 `test_goodrich_research_accepts_bounded_recovery_leader`는
`run_multi_mcp_analysis`를 통째로 모킹해 전원 승인시켰기 때문에 이 모순을 볼 수 없었다.

### 2.2 아직 남아 있는 결함

| # | 내용 | 영향 |
|---|---|---|
| 1 | 장 마감 후 90분 초과 시 GET이 502 → 프런트가 `Promise.all`이라 페이지 전체가 에러 | 야간·주말 대시보드가 장애처럼 보임 |
| 2 | POST `/research`가 read-only 전용 데코레이터(`admin_or_aibain_required`) 사용, 쿨다운·비용 한도 없음 | 구독자가 무제한 LLM 실행 유발 가능 |
| 3 | 프런트 100초 타임아웃 안에 스크리닝+LLM+업스트림 POST를 동기 처리 | 사용자에겐 실패, 서버는 계속 실행 |
| 4 | `get_fund_manager`가 `multi_mcp_runs/latest.json`을 상관관계·신선도 검증 없이 병합 | 화면 종목과 무관한 근거 메타데이터 부착 가능 |
| 5 | 30분 사이클 텔레그램에 dedupe 없음 | 대기 구간엔 동일 메시지 하루 13회 |
| 6 | `integration.universe_size`를 "검출 범위"로 표시 (GET 경로에선 항상 ≤3) | 스캔 범위 오표기, `candidate_count`는 미표시 |
| 7 | `cash_wait_reason`·`profit_gate_passed_count`·`multi_mcp` 블록이 화면에 미노출 | 대기 사유를 사용자가 알 수 없음 |
| 8 | `goodrich_client.py`에 로깅 전무 | 502/503 원인 진단 불가 |
| 9 | 임계값 전부 하드코딩(`24/45`, `8`, `15`, `90분`, `rows[:20]`) | 튜닝 불가 |
| 10 | 설계 문서가 실제와 불일치(`fixed-6`, 엔드포인트 2개로 기술) | 문서 신뢰도 |

---

## 3. 변경 1 — recovery-leader 폐기 (`ca0d6e9`)

- **`multi_mcp_orchestrator.py`**: `TREND_GATE_RULES`를 단일 진실 소스로 신설하고
  `trend_gate_checks()` / `passes_trend_gate()`로 노출. `_evidence_packet`과
  `architecture_manifest`가 모두 여기서 값을 읽어 **두 게이트가 다시 갈라질 수 없게** 했다.
- **`goodrich_client.py`**: 인라인 추세 판정을 `passes_trend_gate()`로 교체.
  `recovery_leader_*`·`gate_mode`·중복 `is_preferred` 할당 제거.
  `trend_gate` 메타데이터는 `rule_source` + `passed_count`로 정리.
- **테스트**: 모킹으로 결함을 가리던 기존 테스트를 실제 회귀 테스트 2개로 교체.
  ① 반등주만 있는 풀은 심층분석에 도달하지 않고 대기 전환
  ② 전달된 모든 후보가 **모킹하지 않은** Multi-MCP profit gate를 통과

RED 단계에서 `002210 forwarded but fails ['positive_5d', ...]`로 결함이 재현됐고 수정 후 통과했다.

> **주의**: 이 수정은 코드 정합성으로는 옳지만 **수익성에는 영향이 없다.**
> 4장에서 밝혀졌듯 해당 경로는 지금까지 픽을 단 한 건도 게시한 적이 없다.

---

## 4. 검출 성과 진단 — 기존 지표는 생존편향이었다

### 4.1 Goodrich `/performance` 원자료 (90일)

```
total_picks 36 | evaluated 1 | target_hits 0 | stop_hits 1
hit_rate 0.0% | average_return -0.9% | costs_included false
```

36픽 중 **평가된 것이 1건**이다. 나머지는 `replaced` 32건, `stood_aside` 3건.
30분마다 TOP3를 교체하는데 목표가는 +12~14%, 손절가는 -7~8% 밴드다.
대형주가 30분 안에 그 밴드를 건드릴 확률은 0에 가까워, 사실상 **교체 로그**를 성과로 보고하고 있었다.

### 4.2 게이트 경로는 한 번도 게시된 적이 없다

Multi-MCP 심층분석 전체 실행 이력(5회):

| run | status | 후보 | profit gate 통과 | CIO 승인 |
|---|---|---|---|---|
| 20260729_072416 | selective_portfolio | 9 | 2 | 2 |
| 20260730_003038 | cash_wait | 3 | 3 | 0 |
| 20260730_010026 | selective_portfolio | 3 | 3 | 1 |
| 20260730_020322 | selective_portfolio | 3 | 2 | 1 |
| 20260730_023027 | selective_portfolio | 3 | 3 | 1 |

**단 한 번도 3개에 도달하지 않았다.** `run_research`는 매번 stand_aside했다.
즉 대시보드 TOP 3는 **100% Goodrich 자체 랭킹 산출물**이며,
MarketFlow 게이트를 통과해 게시된 픽은 0건이다.
게시물에 당일 -6.67% NAVER가 포함된 것이 그 증거다(MarketFlow 게이트는 `change_pct > 0` 요구).

### 4.3 그 밖의 패턴

- **종목 편중**: 36픽 중 셀트리온 9회, 현대차 4회. 상위 6종목이 25/36.
- **LLM이 판단하지 않음**: WATCH 34 / BUY_CANDIDATE 2, 초기 conviction 전부 기본값 50.
  `_critic_review`는 BUY 계열 + conviction≥60만 승인하므로 이 픽들은 CIO를 통과할 수 없다.
- **하락 종목 게시**: 당일 등락률이 명시된 46건 중 19건이 마이너스.

---

## 5. 변경 2 — 측정 하네스 (`3c6acb8`, `7491d16`, `0342328`, `166d929`, `eccf2bc`)

### 5.1 `app/services/mirofish/goodrich_ledger.py` (신규)

| 함수 | 역할 |
|---|---|
| `record_snapshot` / `backfill_from_history` | 게시된 모든 픽을 `(cycle_id, symbol)` 키로 append-only JSONL 적재. **교체가 기록을 지우지 못한다.** |
| `evaluate_pick` | 진입일보다 **엄격히 이후** 세션만 출구로 사용(look-ahead 차단). 벤치마크는 **날짜 정렬**. 왕복 비용 차감분 산출 + **사용한 비용률을 결과에 반환**. |
| `benchmark_ticker` / `evaluate_ledger` | 픽의 시장에 맞는 지수 프록시 선택(미상이면 대표지수 폴백), 원장 전체 평가 후 사용 벤치마크를 각 호라이즌에 각인 |
| `summarize` | 호라이즌별 집계. 결과 없는 픽은 **pending**으로 세고 0%로 희석하지 않는다 |

설계상 지킨 것:

- **날짜 정렬 필수**: 지수가 특정 세션을 빠뜨렸을 때 위치 정렬은 거짓 초과수익을 만든다.
  같은 날짜의 종가가 양쪽에 다 있을 때만 초과수익을 주장한다.
- **비용률 반환**: 잘못된 비용 가정이 승률에 조용히 스며들지 않고 눈에 보이게 한다.
  기본값 왕복 0.23%는 **확인이 필요한 가정**이지 사실이 아니다.
- **pending ≠ 0%**: 기존 `/performance`가 저지른 오류를 반복하지 않는다.

원장 경로: `data/admin_mirofish/goodrich_ledger.jsonl`

### 5.2 30분 사이클 배선

`scripts/run_goodrich_intraday_cycle.py`가 매 사이클 게시 픽을 원장에 기록한다.
측정이 검출을 깨뜨릴 수 없도록 예외를 격리해 실패 시 `ledger_error`로 상태에만 노출한다.

### 5.3 벤치마크 확보

초과수익 로직은 있었지만 **저장된 지수 시계열이 어디에도 없었다**
(`market_gate_cache.json`은 최신 스냅샷 1건, `daily_prices.csv`에는 지수·지수ETF 없음,
`fdr.StockListing('KRX')`는 주식만 반환).

- `BENCHMARK_TICKERS` = KODEX 200(069500), KODEX 코스닥150(229200)
- `scheduler._with_benchmark_tickers`가 수집 유니버스에 프록시를 편입(중복·이름 덮어쓰기 없음)
- `scripts/backfill_benchmark_prices.py`로 2024-01-02부터 **1,254행 백필 완료**(재실행 안전)

ETF를 일반 종목과 같은 파일에 수집하므로 양쪽이 동일한 거래 캘린더 위에 놓인다.

---

## 6. 첫 실측 (T+1, n=36)

### 6.1 벤치마크 반영 전후

| 지표 | 벤치마크 전 | 벤치마크 후 |
|---|---|---|
| 평균 | -4.44% (중앙값 -3.77%) | **초과수익 -0.63%** |
| 비용 반영 | -4.67% | **-0.86%** |
| 승률 | 27.78% | **초과수익 승률 61.1%** |
| 최악 / 최고 | -22.37% / +6.10% | — |

하락분의 대부분은 종목 선정이 아니라 **시장 베타**였다.
벤치마크 없이 본 -4.44%는 과잉 비관이었다.

### 6.2 핵심 발견 — 랭킹이 알파를 뒤집는다

```
corr(점수, T+1 초과수익) = -0.623      (원수익률 기준 -0.530)

점수 <75    n=20   평균 초과수익  +2.94%
점수 >=75   n=16   평균 초과수익  -5.09%
```

- 후보 유니버스 자체는 시장을 이긴다(초과수익 승률 61%, 저점수 구간 +2.94%).
- 그런데 점수가 높을수록 초과수익이 낮다. **점수는 "당일 이미 오른 정도"의 대리변수**다.
- 최고점 종목(코스모로보틱스 98.42, 당일 +17.06%)이 T+1 -19.02%로 손실 1위였다.

종목별 T+1 원수익률 — 11종목 중 10종목 마이너스:

```
코스모로보틱스 n=3  -19.02%      삼성바이오로직스 n=3  -5.04%
현대무벡스     n=3  -12.93%      NAVER          n=2  -4.52%
아이크래프트   n=1  -10.14%      에스피지        n=3  -3.64%
셀리드         n=2   -7.55%      카카오          n=3  -1.31%
씨피시스템     n=3   -7.38%      현대차          n=4  -0.95%
                                 셀트리온        n=9  +2.93%
```

### 6.3 표본 한계 (반드시 함께 읽을 것)

- 36픽이지만 **독립 종목 11개, 진입일 2일**. 같은 종목의 반복 선정이 표본을 부풀린다.
- **T+1만** 평가 가능. T+3/5/20은 원장에 축적 중.
- 표본 구간이 **한 번의 급락 국면**이다. 상승장에서 고모멘텀 종목의 거동은 다를 수 있다.
- 따라서 확정적 결론이 아니라 **강한 방향성**이다.
  다만 점수 구간 비교는 같은 날 같은 시장을 겪은 종목끼리의 횡단면 비교라 시장 방향으로는 설명되지 않는다.

---

## 7. 작업 중 발생시킨 장애와 처리

### 7.1 미니PC 포트 5001 오염 → 재부팅 (약 30분 다운)

배포 중 구 인스턴스가 살아있는 상태에서 `schtasks /End` 직후 `/Run`을 실행해
5001에 이중 바인딩이 발생했다. `/End`는 런처만 종료하고 python 자식이 남아,
새 인스턴스가 SO_REUSEADDR로 같은 포트에 바인딩됐다.
그 결과 **죽은 PID 소유의 고아 리스닝 소켓**이 남아 커널이 트래픽을 그쪽으로 보냈고,
새 Flask는 `Running on http://127.0.0.1:5001` 로그를 찍어도 TCP connect가 거부됐다.

- 5002 포트 실험으로 **코드가 아닌 포트 문제**임을 분리 확인
- 프로세스가 존재하지 않아 taskkill·conhost 정리로 회수 불가 → 사용자 승인 후 재부팅
- 재부팅 후 MarketFlow·JUST BUY·Goodrich 전 서비스 정상 복구 확인

**재발 방지 절차**: `/End` → flask_app.py python 프로세스 전부 `Stop-Process -Force` →
`Get-NetTCPConnection -LocalPort 5001 -State Listen`이 **빈 값**인지 확인 → 그 다음에만 `/Run`.

진단 팁: 원격 PowerShell `Invoke-WebRequest`는 시스템 프록시를 타서 무조건 타임아웃난다.
`[Net.WebRequest]::Create(...)` + `$req.Proxy=$null` 또는 `Test-NetConnection`으로 판별할 것.

### 7.2 테스트가 실제 원장을 오염 (`0342328`)

사이클에 원장 배선을 넣자 기존 `test_forced_cycle_...`의 픽스처(삼성전자 100/110/95)가
실제 원장에 기록됐다. 공용 픽스처 `_use_temp_paths`가 `LOCK_PATH`·`STATUS_PATH`만
리다이렉트하고 `LEDGER_PATH`를 빠뜨렸기 때문이다.

- 로컬 3행·미니PC 1행 오염 → 전부 제거
- 픽스처가 **사이클이 쓰는 모든 산출물**을 가로채도록 수정
- 자기 테스트가 오염시키는 측정 원장은 신뢰할 수 없으므로 각 테스트가 아니라 픽스처의 책임

---

## 8. 커밋

| 커밋 | 내용 |
|---|---|
| `ca0d6e9` | recovery-leader 우회 폐기, 추세 게이트 정의 단일화 |
| `3c6acb8` | 측정 원장 + look-ahead 안전 T+N / 벤치마크 초과수익 / 비용 |
| `7491d16` | 30분 사이클이 게시 픽을 원장에 기록 |
| `0342328` | 테스트가 실제 원장에 쓰던 결함 수정 |
| `166d929` | KODEX 벤치마크 수집 편입 + 시장별 해석기 |
| `eccf2bc` | 벤치마크 과거 이력 백필 스크립트 |

**검증**: 로컬 `pytest tests -q` → 764개 통과.
미니PC 관련 스위트 34개 통과, 원장 36행/12사이클 정상.
`marketflow-api` / `api.bit-man.net` / `bit-man.net` 전부 200.

---

## 9. 남은 과제 (우선순위)

1. **랭킹 함수 교체** — 데이터가 가리키는 가장 값싼 개선.
   현 점수는 "이미 오른 정도"의 대리변수다. 백필된 2년치 가격 이력으로
   대안 랭킹(눌림목 재돌파, 섹터 대비 상대강도, 수급 연속성)을 look-ahead 없이
   백테스트해 현 점수와 직접 비교할 수 있다.
2. **보유기간·목표가 정합성** — 30분 교체와 +12~14% 목표는 양립하지 않는다.
   D+N 보유 슬롯으로 전환하거나 목표 밴드를 호라이즌에 맞춰 축소.
3. **2.2절 잔여 결함** — 특히 #1(장외 502 + `Promise.all` → `allSettled`)과
   #2(쿨다운·비용 한도), #3(비동기 잡 전환).
4. **표본 축적 대기** — T+3/5/20이 채워지면 위 판단의 신뢰도가 올라간다.

진입 로직 변경은 반드시 이 하네스로 **사전/사후 비교**할 것.
측정 없이 바꾸면 개선인지 개악인지 판별할 수 없다.
