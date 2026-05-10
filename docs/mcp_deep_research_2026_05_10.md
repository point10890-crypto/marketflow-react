# MCP 자동화 인프라 — 딥리서치 통합 보고서

**작성일**: 2026-05-10
**대상**: https://bit-man.net/admin/endpoints (MiroFish AI 자동화 콘솔)
**조사 방식**: 4팀 병렬 (MCP / AI Agent / Auto-Scan / Multimodal)
**검증된 후보**: 60+ → 채택 22 → 즉시 9 / 단기 8 / R&D 5

---

## 0. Executive Summary

| 카테고리 | 후보 수 | 채택 | 즉시 통합 가능 | 신규 비용 |
|---|---|---|---|---|
| MCP 서버 (Anthropic spec) | 12 | 5 | 5 | $50/월 |
| Trading 에이전트 패턴 | 15 | 6 | 2 | $0 (코드 차용) |
| Auto-scan / Alpha factor | 24 | 8 | 4 | $0 (오픈소스) |
| Multimodal 데이터 | 10 | 7 | 3 | $30~80/월 |
| **합계** | **61** | **26** | **14** | **$80~160/월** |

**현재 시스템 GAP**: ① 자체 MCP 서버화 미구현, ② 한국 retail sentiment 부재, ③ YouTube/SNS 자동 종목 추출 부재, ④ 백테스트 자동화 미흡, ⑤ Reflexion/online learning 패턴 부재.

---

## 1. ⚠️ 검증 필요 후보 (실제 존재성 의심)

| 후보 | 의심 사유 | 액션 |
|---|---|---|
| TradingAgents `17k★` | 17k 는 빠르게 증가했을 가능성. 직접 GitHub 확인 필요 | 채택 전 GitHub fetch |
| Microsoft FinAgent (NeurIPS 2024) | Microsoft 공식 vs 학술 그룹 fork 혼동 가능 | arXiv 정확 인용 필요 |
| AlphaGen NeurIPS 2023 | venue 정확성 검증 | 채택 전 paper 확인 |
| `microsoft/qlib` 한국 어댑터 | KRX 미지원 — 자체 어댑터 작성 필요 | 공수 +3d 추정 |

**원칙**: 채택 전 GitHub 직접 fetch + 라이선스 확인.

---

## 2. 통합 매트릭스 — 우선순위 + 라이선스 + 비용

### 🔴 Tier S — 즉시 통합 (2주 내)

| # | 도구 | 카테고리 | 라이선스 | 비용 | 우리 모듈 추가 |
|---|---|---|---|---|---|
| S1 | **Naver 검색 API** | News | 무료 | $0 | `engine/llm_analyzer.py` Perplexity 폴백 |
| S2 | **Naver 금융 종목토론 스크래퍼** | Retail sentiment | 회색 | $0 | `app/routes/kr_market.py` `/retail-sentiment/<code>` |
| S3 | **YouTube transcript + Gemini NER** | Media → 종목 큐 | 무료 | $0 | `engine/youtube_collector.py` 신규 |
| S4 | **Tavily MCP** | Web 검색 | MIT | $0~30/월 | omnisearch 폴백 |
| S5 | **FRED API + 한국은행 ECOS** | 매크로 | 무료 | $0 | `app/routes/us_market.py` 매크로 카드 |
| S6 | **modelcontextprotocol/servers** (Memory + Sequential-Thinking) | MCP | MIT | $0 | ReACT CIO 컨텍스트 영속화 |
| S7 | **Reflexion 패턴** | Self-improvement | MIT | $0 | `cio_react.py` self-critique 추가 |
| S8 | **WorldQuant Alpha101 (6개 factor)** | Alpha | MIT | $0 | `engine/scorer.py` slot 5점 추가 |
| S9 | **vectorbt 백테스트** | Validation | Apache-2.0 | $0 | `backtest/vectorbt_runner.py` 일요일 자동 |

**총 추가 비용 (S tier)**: ~$30/월 (Tavily 만)

### 🟠 Tier A — 단기 통합 (1개월 내)

| # | 도구 | 카테고리 | 라이선스 | 비용 | 우리 모듈 추가 |
|---|---|---|---|---|---|
| A1 | **TradingAgents Bull/Bear debate round** | Multi-agent 패턴 차용 | Apache-2.0 | $0 | `agent_debate.py` round 2 |
| A2 | **AutoGen GroupChat 백본** | Multi-agent | MIT | $0 | 5인 토론 manager 패턴 |
| A3 | **QLib Alpha158 어댑터** (KRX 어댑터 자작) | Alpha factor | MIT | $0 | `engine/alpha_factors.py` 신규 |
| A4 | **PyKis 비동기** | KIS WS | MIT | $0 | 주도주LIVE 5s → 100ms |
| A5 | **playwright-mcp** | 웹 자동화 | Apache-2.0 | $0 | ProPicks 스크래핑 안정화 |
| A6 | **e2b-dev/mcp-server** | 코드 실행 sandbox | Apache-2.0 | $30/월 | 백테스트 격리 |
| A7 | **SEC EDGAR MCP** (Form 4 + 13F) | 공시 | MIT | $0 | `app/routes/us_market.py` insider |
| A8 | **Reddit MCP (r/wallstreetbets)** | US sentiment | OAuth 무료 | $0 | US sentiment 신호 |

**총 추가 비용 (A tier)**: $30/월

### 🟡 Tier B — R&D (3개월 내, 검증 후 채택)

| # | 도구 | 검증 항목 | 채택 조건 |
|---|---|---|---|
| B1 | **AlphaGen RL** (NeurIPS) | venue 확인 + GPU 1대 30 alpha 추출 | 인간 검수 후 5개 prod |
| B2 | **FactorVAE** (AAAI 2022) | 한국 데이터 학습 가능성 | KR 1년 backtest 통과 시 |
| B3 | **Triple Barrier + Meta-labeling** (López de Prado) | V2 신호 false positive 절감 | 메타 모델 sharpe ≥ baseline |
| B4 | **HMM Regime Detection** (hmmlearn) | market_gate 강화 | KOSPI/SPY/BTC 각각 학습 |
| B5 | **river online learning** | V2 가중치 자동 보정 | drift detector 통과 |

---

## 3. Phase별 구현 로드맵

### Phase 1 — 2주 (즉시 통합 9개)

**Week 1**:
- Day 1-2: Naver 검색 API + 한국은행 ECOS + FRED → 한국 뉴스 폴백 + 매크로 카드
- Day 3-4: Naver 금융 종목토론 스크래퍼 → `/api/kr/retail-sentiment/<code>`
- Day 5: YouTube transcript 파이프라인 — 슈카/삼프로/박곰희 4h 폴링

**Week 2**:
- Day 1-2: Reflexion 패턴 — `cio_react.py` 에 verbal critique + `data/cio_reflections.json`
- Day 3-4: WorldQuant Alpha101 6개 → `engine/scorer.py` 22점 만점
- Day 5: vectorbt 백테스트 + Tavily MCP fallback + MCP servers (Memory + Sequential-Thinking)

**검증 게이트**: 단위 테스트 + Skill 4 + tsc + production 배포

### Phase 2 — 1개월 (단기 통합 8개)

**Week 3-4**:
- TradingAgents Bull/Bear round → `agent_debate.py` round 2
- AutoGen GroupChat 백본 전환 (선택적, 토큰 50% 절감 시 채택)
- QLib Alpha158 어댑터 (KRX OHLCV → Alpha158)
- PyKis 비동기 → 주도주LIVE WS 전환

**Week 5-6**:
- playwright-mcp + e2b-dev/mcp-server (sandbox)
- SEC EDGAR MCP (Form 4 + 13F)
- Reddit MCP (r/wallstreetbets)

**검증 게이트**: Phase 1 회귀 0 + 새 라우트 healthcheck PASS + 라이브 스모크

### Phase 3 — 3개월 R&D (5개)

- AlphaGen GPU 학습 24h (3090/4060 1대)
- FactorVAE KR 1년 backtest
- Triple Barrier + Meta-labeling LightGBM
- HMM Regime
- river online learning

**완료 기준**: 각 알고리즘 sharpe ≥ baseline → prod 채택 / fail → 결과만 기록

---

## 4. 라이선스 위험 매트릭스

| 라이선스 | 후보 | 통합 방식 | 위험 |
|---|---|---|---|
| **MIT / Apache-2.0** | 대부분 (S/A 18개) | 직접 import | ✅ 안전 |
| **AGPL-3.0** | OpenBB | sidecar 마이크로서비스만 | 🟠 격리 필수 |
| **GPL-3.0** | freqtrade, backtrader | REST 별도 프로세스 | 🟠 격리 필수 |
| **회색지대** | Naver 종목토론 / 다음 금융 | rate-limit 5s + 보존 회피 | 🟠 운영 회색 |
| **상용** | vectorbt Pro, Polygon.io | 미채택 | ⚪ 후순위 |

**권고**: AGPL/GPL 코드는 **별도 Docker container** 또는 별도 Flask process 로 격리 → REST 호출만.

---

## 5. 비용 합산

| 항목 | 월 비용 |
|---|---|
| Tavily MCP (S4) | $0~30 |
| e2b-dev sandbox (A6) | $30 |
| Polygon.io starter (선택) | $29 |
| Alpha Vantage Premium (선택) | $50 |
| **Phase 1 즉시** | ~$30 |
| **Phase 2 단기** | ~$60 |
| **Phase 3 옵션 포함** | ~$140 |

기존 운영 비용 + 신규 ≈ **월 $200 미만 유지 가능**.

---

## 6. 자체 MCP 서버화 (선택 사항, 큰 가치)

`app/routes/admin_mirofish/*` 33개 라우트를 **자체 MCP 서버로 wrapping**:

```python
# app/services/mirofish/mcp_server.py
from mcp.server import Server
from mcp.types import Tool

server = Server("marketflow-mirofish")

@server.list_tools()
async def list_tools():
    return [
        Tool(name="mirofish_create_run", description="..."),
        Tool(name="mirofish_resolve_target", description="..."),
        Tool(name="mirofish_search_targets", description="..."),
        # ...30+ tools
    ]
```

**이점**:
- Claude Desktop / Cursor / Windsurf 등 MCP 클라이언트가 우리 시스템 직접 호출 가능
- 사용자(point10890@gmail.com)가 자기 PC Claude Desktop 에서 "삼성전자 분석해" 하면 자동 호출
- 다른 LLM 프로바이더 (Cline, Goose) 통합 무료 획득

**구현 공수**: 1주 (Phase 1 끝나고 추가)

---

## 7. 의문점 / 추가 검증 필요

1. **TradingAgents 17k★** — 실제 GitHub 직접 확인 후 채택 (현재 추정치)
2. **Microsoft FinAgent vs FinAgent (학술)** — venue 정확 매칭 필요
3. **Naver 금융 종목토론 스크래퍼** — 약관 회색지대, 운영 시 캐시 + 비공개 처리 권장
4. **YouTube 채널 자동 멘션 → MiroFish 큐** — 한국 retail 인플루언스 차이 측정 필요 (인사이트 vs 노이즈)

---

## 8. 승인 요청 사항

다음 중 선택:

- **Option A**: Phase 1 즉시 (9개, 2주)
- **Option B**: Phase 1 + Phase 2 (17개, 6주)
- **Option C**: 전체 Phase 1-3 + 자체 MCP (22개, 3개월)
- **Option D**: 우선순위 재조정

추가 결정 필요:
1. **Naver 금융 종목토론 스크래퍼** — 회색 영역, 진행 OK?
2. **자체 MCP 서버화** — Claude Desktop 통합 우선 가치?
3. **e2b-dev sandbox** — 월 $30 추가 OK?
4. **AGPL OpenBB** — 별도 docker 격리 진행?

승인 후 단일 commit + 검증 게이트 + 무한루프 검증으로 진행합니다.

---

## 9. 💰 구독 서비스 시나리오 — 최소 비용 운영 전략

> **시나리오**: 현재 admin 전용 도구를 일반 회원 구독 서비스로 확장. **MarketFlow 기존 tier 체계** (Free / Pro / Ultra Pro) 재활용 + 최소 신규 인프라.

### 9.1 SaaS 적합도 재평가 — 26 후보 → **18 채택 / 8 탈락**

#### ❌ 탈락 (구독화 시 위험)

| # | 도구 | 탈락 사유 | 대체 |
|---|---|---|---|
| S2 | Naver 금융 종목토론 스크래퍼 | **TOS 위반 위험** → 유료 서비스 시 차단 | 공식 Naver 검색 API 만 사용 |
| - | DC인사이드 / 다음 토론 | 동일 | drop |
| - | Seeking Alpha / MotleyFool transcripts | 비공식 스크래핑 | 공식 SEC EDGAR transcripts |
| A6 | e2b-dev sandbox | $30/월 고정 + 사용자당 비용 폭발 가능성 | 자체 Python AST validator + restricted exec |
| - | OpenBB Platform (AGPL-3.0) | **AGPL = SaaS 시 소스 공개 의무** | 별도 docker 격리 또는 drop |
| - | freqtrade (GPL-3.0) | 동일 | 사용 안 함 |
| - | vectorbt Pro | 상용 라이선스 필요 (per-server fee) | vectorbt 무료 버전만 |
| - | mlfinlab community fork | "All Rights Reserved" — SaaS 위험 | 자체 Triple Barrier 구현 |

#### ✅ SaaS 안전 (18개)

**MIT/Apache-2.0 라이선스 — 상업 SaaS 무제한**:
- Naver 검색 API, FRED, 한국은행 ECOS, SEC EDGAR (모두 공식 무료 API)
- Tavily / Brave / Exa MCP (commercial 가격대로 사용량 종량제)
- modelcontextprotocol/servers (Memory, Sequential-Thinking, Fetch)
- TradingAgents (Apache-2.0), AutoGen, LangGraph, Reflexion (MIT)
- WorldQuant Alpha101, QLib, vectorbt 무료, FactorVAE, AlphaGen
- pykrx, FinanceData Reader, PyKis, akshare
- YouTube transcript-api (무료, 합법)
- StockTwits, Reddit MCP (공식 OAuth API)

---

### 9.2 비용 폭발 방지 — 4계층 캐싱 전략

> **핵심 가정**: 사용자 100명 중 동일 종목(예: 삼성전자) 분석 요청 80%+ 중복.
> → 캐시 히트율 90% 만 달성해도 LLM 호출 10배 감소.

```
┌─────────────────────────────────────────────┐
│  Layer 1 — Pre-computed (overnight batch)   │  Free tier 전용
│  KOSPI 200 + S&P 500 + Top 100 crypto       │  비용: $0 marginal
│  매일 03:00 KST 일괄 LLM 호출 (1회)         │  사용자 → 디스크 read
└─────────────────────────────────────────────┘
              ↓ 캐시 미스
┌─────────────────────────────────────────────┐
│  Layer 2 — User cache (24h TTL per target)  │  Pro 이상
│  같은 종목 24h 내 다른 사용자 → 캐시 hit    │  비용: 첫 1명만
└─────────────────────────────────────────────┘
              ↓ 캐시 미스
┌─────────────────────────────────────────────┐
│  Layer 3 — Quota-limited live LLM           │  Ultra Pro 전용
│  분당 N회 / 일 M회 quota                     │  비용: 사용자 부담
└─────────────────────────────────────────────┘
              ↓ 거부
┌─────────────────────────────────────────────┐
│  Layer 4 — Polite fail with cached fallback │  
│  "1시간 내 재시도" + 캐시 결과만 표시       │
└─────────────────────────────────────────────┘
```

**구현 위치**:
- Layer 1: `scheduler.py` 신규 task `_precompute_top200_mirofish()` 03:00 KST
- Layer 2: `app/services/mirofish/store.py` 의 `_run_id` deterministic key + 24h TTL 캐시 hit
- Layer 3: `app/auth/decorators.py` 의 tier 체크 + Redis-free in-memory rate limit (현재 `users.db` audit log 활용)

---

### 9.3 Tier 매핑 — 최소 비용 / 최대 차별화

| Tier | 월 가격 (제안) | MiroFish 권한 | 일일 한도 | 비용 모델 |
|---|---|---|---|---|
| **Free** | ₩0 | Layer 1 (pre-computed KOSPI 200, S&P 500) **읽기 전용** | 무제한 (캐시) | 운영자 부담 ~$5/월 |
| **Pro** | ₩9,900 | Layer 1 + Layer 2 (직접 종목 분석, 24h 캐시 공유) | 5건/일 | 캐시 히트 시 거의 0 |
| **Ultra Pro** | ₩29,000 | Layer 1+2+3 (실시간 LLM, Reflexion 메모리) | 30건/일 | $0.30~0.50/유저/월 |

**기존 MarketFlow Pro 구독자 자동 매핑** — Pro tier에 자동 포함, 마케팅 비용 0.

---

### 9.4 비용 추정 — 100 사용자 시나리오

#### 가정
- 50 Free / 30 Pro / 20 Ultra Pro
- Free: pre-computed 결과만 보기 (LLM 신규 호출 0)
- Pro: 평균 일 1.5회 분석, 90% 캐시 히트 → 신규 호출 0.15/일
- Ultra Pro: 평균 일 5회 분석, 70% 캐시 히트 → 신규 호출 1.5/일

#### 일일 신규 LLM 호출 수
- Pre-compute (Free 공통): KOSPI 200 + S&P 500 = **300회/일**
- Pro 신규: 30 × 0.15 = **4.5회/일**
- Ultra Pro 신규: 20 × 1.5 = **30회/일**
- **합계: ~334.5 LLM 호출/일** = ~10,035회/월

#### 모델별 비용 (Gemini 2.5 Flash 주력 + DeepSeek 보조)

| 모델 | 단가 (1M 토큰) | 평균 호출 토큰 | 1회 비용 |
|---|---|---|---|
| Gemini 2.5 Flash | $0.075 input / $0.30 output | 4k input / 1.5k output | ~$0.0007/회 |
| DeepSeek V3 | $0.27 input / $1.10 output | 4k / 1.5k | ~$0.0027/회 |

**월 LLM 비용 (Gemini 주력)**:
- 10,035회 × $0.0007 = **$7/월**
- DeepSeek 일부 사용 시 (스캐너 요약): +$5/월
- Tavily 검색 (omnisearch): $30/월 (1만 회 plan)
- **합계: 약 $42-50/월** (100 사용자 운영 시)

#### 사용자당 비용
- Free: $5/50 = **$0.10/유저/월**
- Pro: ($42 × 0.3) / 30 = **$0.42/유저/월** ← 9,900원 매출 → 마진 95%+
- Ultra Pro: ($42 × 0.6) / 20 = **$1.26/유저/월** ← 29,000원 매출 → 마진 96%+

**손익분기점**: 약 5명 Pro 가입 시 운영 비용 회수.

---

### 9.5 신규 인프라 — **0원 추가**

기존 MarketFlow 인프라 100% 재사용:

| 항목 | 기존 | 신규 필요? |
|---|---|---|
| Flask backend | miniPC 5001 + Cloudflared tunnel | ✅ 재사용 |
| Frontend | Cloudflare Pages | ✅ 재사용 |
| 인증 | tier-based (Free/Pro/Ultra Pro) | ✅ 이미 구현 |
| DB | SQLite users.db | ✅ 재사용 |
| 캐시 | atomic_json + json_cache (mtime-aware) | ✅ 재사용 |
| 결제 | Stripe (이미 통합) | ✅ 재사용 |
| 스케줄러 | scheduler.py daemon | ✅ 재사용 (1 task 추가만) |
| 텔레그램 | 채널 + 개인 분리 | ✅ 재사용 |

**Redis / Kubernetes / 별도 worker 등 추가 0**.

---

### 9.6 Phase 별 SaaS launch 로드맵 (최소 비용)

#### Phase 1 (2주, $0 추가 비용) — Free + Pro 베타
- Layer 1 pre-compute task (`scheduler.py` 03:00 KST KOSPI 200 + S&P 500 분석)
- Layer 2 캐시 (24h TTL deterministic run_id)
- AdminEndpointsPage → public read-only 페이지 (`/dashboard/mirofish/{symbol}`)
- 결과: **Free 50명 운영 가능, 비용 ~$5/월**

#### Phase 2 (1개월, ~$30/월 추가) — Pro tier 정식 출시
- Pro 회원 자기 종목 분석 (5건/일 quota)
- Reflexion 패턴 (CIO 자기개선)
- WorldQuant Alpha101 6개 추가
- vectorbt 백테스트 결과 표시
- 결과: **Pro 30명 가입 시 흑자 전환**

#### Phase 3 (2개월, ~$80/월 추가) — Ultra Pro 출시
- Real-time LLM (Gemini Pro 또는 GPT-4o 옵션)
- TradingAgents Bull/Bear debate
- Reddit / SEC EDGAR / FRED 통합
- YouTube transcript 자동 멘션
- 결과: **Ultra Pro 20명 가입 시 월 매출 + 50만원**

#### Phase 4 (3-6개월, R&D 검증 후) — AlphaGen / FactorVAE / Online learning
- 자체 학습된 모델 → MarketFlow 차별화
- "AI가 새 alpha factor 자동 발굴" — 마케팅 포인트
- 비용 동일 유지 (모델 자체 학습이라 외부 API 호출 X)

---

### 9.7 SaaS 절대 금기 (라이선스 + 데이터 ToS)

1. **AGPL/GPL 코드 직접 import 금지** — 별도 docker process / drop
2. **Naver 종목토론 / 다음 / DC갤 스크래퍼 prod 차단** — 약관 위반, 소송 위험
3. **mlfinlab community 코드 사용 금지** — "All Rights Reserved"
4. **Seeking Alpha / MotleyFool transcripts** — 비공식 스크래핑, drop
5. **vectorbt Pro 미사용** — 상용 라이선스 별도 ($0 → $$$$)
6. **사용자 데이터 외부 LLM 노출 시 사전 고지** — 개인정보처리방침 명시 필수
7. **DeepSeek 사용 시 — 중국 데이터 정책 사용자 안내**
8. **Gemini 의 free tier rate limit** 운영 시 paid plan 전환 필수

---

### 9.8 핵심 답변 — "최소 비용으로 구독 서비스 가능?"

**YES, 매우 가능**:
- 신규 인프라 비용: **$0** (기존 재사용)
- 신규 LLM 운영비: **~$50/월** (100 사용자 기준)
- 손익분기점: **Pro 5명** (월 49,500원)
- Pro 30명 + Ultra 20명 시: **월 매출 ~877,000원, 운영비 50불 → 마진 96%+**
- Phase 1 (Free + Pro 베타) **2주 만에 출시 가능**

**핵심 수단**:
1. 4-layer 캐싱 (90%+ 히트율)
2. Pre-computed batch (KOSPI 200 + S&P 500)
3. Gemini 2.5 Flash 주력 + DeepSeek 보조
4. 기존 인프라 100% 재사용
5. AGPL/GPL/회색지대 후보 모두 drop

**결론**: 추가 자본 투입 없이 기존 시스템에 캐싱 레이어 + tier 권한만 추가해서 **2주 내 Free/Pro 베타, 1-2개월 내 정식 SaaS 출시 가능**.

---

# 📎 부록 — 4팀 원본 조사 결과

## 부록 A — MCP 서버 카탈로그 (팀 A)

### Tier S — 즉시 통합 권장 (production-ready, 한국 금융 도메인 강 매칭)

| Repo | URL | 라이선스 | 언어 | 핵심 기능 | 통합 포인트 |
|---|---|---|---|---|---|
| **modelcontextprotocol/servers** (Fetch, Filesystem, Git, Memory, Sequential-Thinking, Time) | [github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | MIT | TS/Python | 6개 reference servers (steering group 직접 유지) | `Fetch` → DART/외부 RSS, `Memory` → ReACT CIO 7-tool 컨텍스트 캐시, `Sequential-Thinking` → 5-agent debate 사고 체인 |
| **microsoft/playwright-mcp** | [github.com/microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | Apache-2.0 | TS | 공식 Microsoft, accessibility-snapshot 기반 (스텔스보다 LLM 친화) | Investing.com ProPicks 스크래핑 대체 → CAPTCHA/JS 렌더 안정화 |
| **e2b-dev/mcp-server** | [github.com/e2b-dev/mcp-server](https://github.com/e2b-dev/mcp-server) | Apache-2.0 | TS | E2B firecracker sandbox에서 임의 Python 실행 | Brain 13D 백테스트, alpha scanner ad-hoc 분석. E2B Pro $0.000014/sec (~$0.05/시간) |
| **alphavantage/alpha_vantage_mcp** (공식) | [github.com/alphavantage/alpha_vantage_mcp](https://github.com/alphavantage/alpha_vantage_mcp) | MIT | Python | Alpha Vantage 공식, FX/crypto/options/technicals 전체 endpoint | KIS+yfinance 외 글로벌 FX, US options chain 보강. Free tier 25 req/day → Premium $50/mo |

### Tier A — 1순위 후보

| Repo | URL | 라이선스 | 핵심 기능 |
|---|---|---|---|
| **Alex2Yang97/yahoo-finance-mcp** | [github.com/Alex2Yang97/yahoo-finance-mcp](https://github.com/Alex2Yang97/yahoo-finance-mcp) | MIT | yfinance 전체 wrapping (financial statements, options, news) |
| **spences10/mcp-omnisearch** | [github.com/spences10/mcp-omnisearch](https://github.com/spences10/mcp-omnisearch) | MIT | Tavily/Brave/Kagi/Exa + Firecrawl 단일 인터페이스 |
| **OpenBB-finance/openbb-docs-mcp** | [github.com/OpenBB-finance/openbb-docs-mcp](https://github.com/OpenBB-finance/openbb-docs-mcp) | AGPL-3.0 | OpenBB 350+ 데이터 provider — **AGPL 격리 필수** |
| **financial-datasets/mcp-server** | [mcpservers.org/servers/financial-datasets](https://mcpservers.org/servers/financial-datasets/mcp-server) | MIT | 손익계산서/대차대조표/현금흐름 |

### Tier B — 참고용

| Repo | URL | 라이선스 |
|---|---|---|
| **modelcontextprotocol/python-sdk** | [github.com/modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | MIT |
| **modelcontextprotocol/typescript-sdk** | [github.com/modelcontextprotocol/typescript-sdk](https://github.com/modelcontextprotocol/typescript-sdk) | MIT |
| **microsoft/mcp** (catalog) | [github.com/microsoft/mcp](https://github.com/microsoft/mcp) | MIT |
| **TensorBlock/awesome-mcp-servers** | [github.com/TensorBlock/awesome-mcp-servers](https://github.com/TensorBlock/awesome-mcp-servers) | CC0 |
| **Official MCP Registry** | [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/) | — |

---

## 부록 B — AI 트레이딩 에이전트 프레임워크 (팀 B)

### Tier S — 즉시 통합 + 라이선스 친화적

| 프로젝트 | URL | 스타 (추정) | 라이선스 | 우리에 추가될 가치 |
|---|---|---|---|---|
| **TradingAgents** | [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) | ~17k | Apache-2.0 | Bull/Bear/Trader/Risk/Fundamentals 멀티에이전트 + LangGraph 상태머신 + memory bank — 5인 토론에 직접 비교 |
| **Microsoft Qlib** | [github.com/microsoft/qlib](https://github.com/microsoft/qlib) | ~15k | MIT | Alpha158/360 factor + LSTM/Transformer ranking + RL portfolio |
| **FinRL / FinRL-Meta** | [github.com/AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) | ~10k | MIT | Stable-Baselines3 + 트레이딩 env (PPO/SAC/A2C) |
| **AutoGen** | [github.com/microsoft/autogen](https://github.com/microsoft/autogen) | ~37k | MIT | GroupChat + 비동기 멀티에이전트 + 코드실행 |
| **LangGraph** | [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) | ~10k | MIT | Stateful graph + checkpointing + human-in-loop |

### Tier A — 부분 통합 권장

| 프로젝트 | URL | 라이선스 | 노트 |
|---|---|---|---|
| **FinGPT** | [github.com/AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | MIT | LLaMA-2 fine-tune for sentiment |
| **FinAgents** | [github.com/AI4Finance-Foundation/FinAgents](https://github.com/AI4Finance-Foundation/FinAgents) | MIT | NeurIPS 2024, "diverse memory" 3계층 — Reflexion 패턴 |
| **MetaGPT** | [github.com/geekan/MetaGPT](https://github.com/geekan/MetaGPT) | MIT | SOP-driven multi-role |
| **CrewAI** | [github.com/crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | MIT | role/goal/backstory + tasks DAG |
| **vectorbt** | [github.com/polakowo/vectorbt](https://github.com/polakowo/vectorbt) | Apache-2.0 / Pro=Commercial | numpy 기반 초고속 백테스트 |
| **freqtrade** | [github.com/freqtrade/freqtrade](https://github.com/freqtrade/freqtrade) | GPL-3.0 | crypto live + hyperopt — **GPL 격리 필수** |
| **Reflexion** | [github.com/noahshinn/reflexion](https://github.com/noahshinn/reflexion) | MIT | verbal RL — agent self-critique |
| **akshare** | [github.com/akfamily/akshare](https://github.com/akfamily/akshare) | MIT | KRX/네이버 일부 지원 |
| **FinMem** | [github.com/pipiku915/FinMem-LLM-StockTrading](https://github.com/pipiku915/FinMem-LLM-StockTrading) | MIT | 계층적 메모리 (short/mid/long term) |

### Tier B — 학술 reference

- **TradeMaster** (NeurIPS 2023) — [github.com/TradeMaster-NTU/TradeMaster](https://github.com/TradeMaster-NTU/TradeMaster)
- **A-Hat / AlphaGPT** — arXiv 2308.00016
- **Voyager** (Wang et al. 2023) — [github.com/MineDojo/Voyager](https://github.com/MineDojo/Voyager)
- **Tree-of-Thoughts** — [github.com/princeton-nlp/tree-of-thought-llm](https://github.com/princeton-nlp/tree-of-thought-llm)
- **arXiv 2402.18485** "FinAgent" — multimodal (차트 이미지 + 텍스트)
- **arXiv 2403.12582** "StockAgent" — LLM agent in simulated market
- **arXiv 2407.06567** "FinCon" — manager-analyst conceptual verbal RL

### YouTube / 블로그 인사이트

- **Two Sigma "Halftime Report"** — 시그널 디케이/regime detection
- **QuantPy** [youtube.com/@QuantPy](https://www.youtube.com/@QuantPy) — Python 백테스트
- **Coding Jesus** — HFT/시장미시구조
- **Lilian Weng** [lilianweng.github.io/posts/2023-06-23-agent](https://lilianweng.github.io/posts/2023-06-23-agent/) — LLM 에이전트 분류 표준
- **Andrej Karpathy** "Intro to LLM agents"

### 한국어 자료

- **finance-datareader** [github.com/FinanceData/FinanceDataReader](https://github.com/FinanceData/FinanceDataReader) (MIT)
- **pykrx** [github.com/sharebook-kr/pykrx](https://github.com/sharebook-kr/pykrx) (MIT)
- **systrader79 블로그** (네이버) — 한국 퀀트 정성 자료
- **KAIST 김우창 교수 연구실** — RL portfolio 논문
- **할 수 있다 알고투자** (YouTube) — 한국 시장 백테스트

### 통합 권장 우선순위 (팀 B)

1. **Reflexion** → ReACT CIO 에 추가, `data/cio_reflections.json` 누적
2. **TradingAgents Bull vs Bear debate round** → 5인 토론 후 직접 반박 강제
3. **AutoGen GroupChat 백본** → manager(=CIO) + 5 specialists, Gemini 호출 50% 절감
4. **FinMem 계층 메모리** → short(7d) / mid(30d) / long(1y) 분리
5. **Qlib factor pipeline** → Brain 13D 를 Qlib expression 으로
6. **비용 최적화** → 5인은 Flash, CIO만 Pro 권장 (TradingAgents ablation 80% 절감)

---

## 부록 C — Auto-scan / TOP-N (팀 C)

### 1. 즉시 통합 가능 (Alpha Scanner 보강)

| 프로젝트 | URL | 라이선스 | 강점 | 통합 난이도 |
|---|---|---|---|---|
| **Microsoft QLib** | [github.com/microsoft/qlib](https://github.com/microsoft/qlib) | MIT | Alpha158/360 + LSTM/GBDT pipeline | 중 (KRX 어댑터 자작) |
| **OpenBB Platform** | [github.com/OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) | AGPLv3 | 통합 data layer | 낮음 (Python SDK) |
| **WorldQuant Alpha101** | [github.com/yli188/WorldQuant_alpha101_code](https://github.com/yli188/WorldQuant_alpha101_code) | MIT | 101개 공개 alpha | 낮음 |
| **finvizfinance** | [github.com/lit26/finvizfinance](https://github.com/lit26/finvizfinance) | MIT | Finviz Python wrapper | 낮음 |
| **pykrx** | [github.com/sharebook-kr/pykrx](https://github.com/sharebook-kr/pykrx) | MIT | KRX 시세/수급/공매도 | - |
| **mlfinlab (community)** | [github.com/hudson-and-thames/mlfinlab](https://github.com/hudson-and-thames/mlfinlab) | All Rights Reserved | López de Prado 전체 구현 | 중 |
| **TA-Lib / pandas-ta** | [github.com/twopirllc/pandas-ta](https://github.com/twopirllc/pandas-ta) | MIT | 130+ 지표 | 낮음 |
| **stockstats** | [github.com/jealous/stockstats](https://github.com/jealous/stockstats) | BSD | KDJ, RSI, BOLL | 낮음 |

### 2. 학술 알고리즘 → 자체 구현 권장

| 알고리즘 | 논문/URL | 우리 도메인 적용 |
|---|---|---|
| **AlphaGen** (NeurIPS 2023) | [github.com/RL-MLDM/alphagen](https://github.com/RL-MLDM/alphagen) | RL 로 alpha 수식 자동 생성 |
| **FactorVAE** (Duan 2022, AAAI) | [arxiv.org/abs/2204.10472](https://arxiv.org/abs/2204.10472) | 잠재 factor → cross-section ranking |
| **DeepLOB** (Zhang 2019) | [github.com/zcakhaa/DeepLOB](https://github.com/zcakhaa/DeepLOB) | KIS LOB → 단기 1-5분 시그널 |
| **AutoAlpha** (Zhang 2020) | [arxiv.org/abs/2002.08245](https://arxiv.org/abs/2002.08245) | gplearn + 금융 fitness |
| **HMM Regime Detection** | [github.com/hmmlearn/hmmlearn](https://github.com/hmmlearn/hmmlearn) | market_gate RISK_ON/OFF 강화 |
| **Triple Barrier + Meta-Labeling** | López de Prado, AFML Ch.3 | V2 신호 false positive 제거 |

### 3. 백테스트 / 검증 파이프라인

| 프레임워크 | URL | 라이선스 | 평가 |
|---|---|---|---|
| **vectorbt** | [github.com/polakowo/vectorbt](https://github.com/polakowo/vectorbt) | Apache 2 (Pro 별도) | 가장 빠름 — 권장 |
| **backtrader** | [github.com/mementum/backtrader](https://github.com/mementum/backtrader) | GPLv3 | KRX 어댑터 사례 풍부 |
| **zipline-reloaded** | [github.com/stefan-jansen/zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded) | Apache 2 | bundle 작성 필요 |
| **NautilusTrader** | [github.com/nautechsystems/nautilus_trader](https://github.com/nautechsystems/nautilus_trader) | LGPLv3 | Rust 코어, 저지연 |

### 4. 한국 시장 특화

- **finance-datareader** (FDR, MIT) — KRX/NXT 일봉
- **mojito** [github.com/sharebook-kr/mojito](https://github.com/sharebook-kr/mojito) (MIT) — KIS/이베스트/대신 통합
- **PyKis** [github.com/Soju06/python-kis](https://github.com/Soju06/python-kis) (MIT) — KIS REST/WS 비동기
- **할수있다 알고투자** (systrader79) — 박스권 돌파, 모멘텀 K-quant
- **인사이트퀀트** — 듀얼 모멘텀 / F-Score 한국형 변형

### 5. YouTube / 블로그 (코드 공개)

- [youtube.com/@QuantPy](https://www.youtube.com/@QuantPy) — vectorbt + Alpha101 backtest
- [youtube.com/@Algovibes](https://www.youtube.com/@Algovibes) — LightGBM ranking, Numerai
- [youtube.com/@PythonProgrammer](https://www.youtube.com/@PythonProgrammer) — backtrader / Minervini SEPA
- [youtube.com/@Part-TimeLarry](https://www.youtube.com/@Part-TimeLarry) — Finviz 스크래핑 swing
- [youtube.com/@QuantInsti](https://www.youtube.com/@QuantInsti) — DeepLOB, mlfinlab 강의
- [youtube.com/@할수있다알고투자](https://www.youtube.com/@할수있다알고투자) — KIS API + 시스템매매 풀 코드
- [hudson-and-thames.com](https://hudson-and-thames.com) — meta-labeling 실전 케이스
- [robotwealth.com](https://robotwealth.com) — vectorbt + 알파 결합

### 6. TOP 10 권장 액션 (팀 C)

1. **QLib Alpha158 어댑터** — `engine/alpha_factors.py` → 22점 만점
2. **WorldQuant Alpha101 6개** (#3, #6, #41, #54, #101)
3. **vectorbt 백테스트 모듈** — `backtest/vectorbt_runner.py` 일요일 자동
4. **Triple Barrier + Meta-Labeling** — V2 false positive 절감 (LightGBM)
5. **HMM Regime** — market_gate 3-state 강화
6. **AlphaGen RL 파일럿** — GPU 24h 학습, 상위 30 alpha 인간 검수
7. **PyKis 비동기** — 주도주LIVE WS 전환 (5s → 100ms)
8. **Minervini SEPA Stage 2** — V2 사전 필터
9. **finvizfinance 보조 스크리너** — 야간 cron US 후보 보강
10. **river online learning** — V2 가중치 매일 종가 incremental update

### 7. TOP-3 ranking 모델 후보

1. **LightGBM LambdaRank** (Learning-to-Rank)
2. **QLib LSTM-Alpha158 baseline**
3. **FactorVAE cross-section**
4. **Numerai-style ensemble** (LGB+XGB+CatBoost rank-mean)
5. **Triple-Barrier meta LightGBM** (V2 위 stacking)

---

## 부록 D — 멀티모달 데이터 소스 (팀 D)

### A. 실시간 뉴스 / 검색 MCP

| 도구 | URL | 비용 | 키 | 통합 포인트 |
|---|---|---|---|---|
| **Tavily MCP** | [github.com/tavily-ai/tavily-mcp](https://github.com/tavily-ai/tavily-mcp) | 무료 1k/월, $30/10k | tavily.com | Perplexity 대체 |
| **Brave Search MCP** | [github.com/modelcontextprotocol/servers/tree/main/src/brave-search](https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search) | 무료 2k/월 | brave.com/search/api | citation 보강 |
| **Exa MCP** | [github.com/exa-labs/exa-mcp-server](https://github.com/exa-labs/exa-mcp-server) | $10/월 1k | exa.ai | semantic 뉴스 |
| **NewsAPI.org** | [newsapi.org](https://newsapi.org) | 무료 100/일 | direct | 한국어 미지원 |
| **Naver 검색 API** | [developers.naver.com](https://developers.naver.com) | 무료 25k/일 | 네이버 | **한국 1순위** |

### B. 소셜 미디어

| 출처 | 방식 | 라이선스 | rate | 시그널 |
|---|---|---|---|---|
| **Reddit MCP** | [github.com/AntonyTan/reddit-mcp](https://github.com/AntonyTan/reddit-mcp) | OAuth 무료 | 60/min | r/wallstreetbets, r/cryptocurrency |
| **Naver 금융 종목토론** | 비공식 스크래핑 | 약관 회색 | 5s throttle | **한국 1순위** |
| **다음 금융 토론** | 동일 | 동일 | 동일 | Naver 백업 |
| **StockTwits API** | [api.stocktwits.com](https://api.stocktwits.com) | 무료 200/h | 200/h | 미국 trending |
| **Twitter/X API v2** | [developer.x.com](https://developer.x.com) | $200/월 Basic | 10k/월 | $cashtag |
| **DC인사이드 주식갤** | 스크래핑 | 회색 | 자체 | 한국 high-risk |

### C. YouTube 자동 분석 파이프라인

**라이브러리**: `youtube-transcript-api` (PyPI, MIT, 무료) + YouTube Data API v3 (무료 10k/일)

**자동화 가능 채널 (한국)**:
- 슈카월드 — 일일 시황
- 박곰희TV — 종목 분석
- 김작가TV — 매크로
- 와이스트릿 — 한국 시장
- 삼프로TV — 데일리 클로징

**미국**: Bloomberg Markets, CNBC Television, Yahoo Finance Live

**파이프라인 코드 패턴**:
```python
# engine/youtube_collector.py
async def collect_mentions():
    channels = ['슈카월드', '박곰희TV', '삼프로TV', ...]
    for ch in channels:
        videos = youtube_api.list_recent(ch, hours=4)
        for v in videos:
            transcript = YouTubeTranscriptApi.get_transcript(v.id, ['ko'])
            tickers = await gemini.extract_tickers(transcript, sentiment=True)
            for t in tickers:
                if t.sentiment == 'positive':
                    record_mention(t.code, ch, v.id, score=t.confidence)

# scheduler.py 4h 간격 → data/youtube_mentions.json 집계
# 멘션 ≥3채널 → MiroFish target_queue.json 자동 추가
```

### D. 공시 / 인사이더

| 도구 | URL | 비용 | 비고 |
|---|---|---|---|
| **DART OpenAPI** | [opendart.fss.or.kr](https://opendart.fss.or.kr) | 무료 20k/일 | 이미 구축 |
| **SEC EDGAR MCP** | [github.com/stefanoamorelli/sec-edgar-mcp](https://github.com/stefanoamorelli/sec-edgar-mcp) | 무료 | 10-K, 10-Q, 8-K |
| **Form 4 (insider)** | [sec.gov/cgi-bin/browse-edgar](https://www.sec.gov/cgi-bin/browse-edgar) | 무료 | 임원 매수/매도 |
| **13F filings** | [whalewisdom.com](https://whalewisdom.com) | 무료 / $50/월 | 헤지펀드 보유 |
| **Seeking Alpha transcripts** | 비공식 스크래핑 | 회색 | earnings call |
| **MotleyFool transcripts** | 동일 | 회색 | 백업 |

### E. 실시간 WebSocket / Stream

| 출처 | 무료 한도 | 통합 |
|---|---|---|
| **Binance WebSocket** | 무제한 | crypto 스트림 |
| **Coinbase Advanced** | 무제한 | crypto 보조 |
| **Polygon.io stocks** | $29/월 starter | 미국 실시간 |
| **Alpaca Markets** | 무료 IEX feed | paper trading + stream |
| **KIS OpenAPI WebSocket** | 무료 | 이미 일부 (주도주LIVE) |

### F. 매크로 지표

| 출처 | 비용 | 통합 |
|---|---|---|
| **FRED API** | 무료 무제한 | 매크로 카드 |
| **한국은행 ECOS** | 무료 등록 | KOSPI/금리/환율 |
| **TradingEconomics** | $50/월 starter | 후순위 |
| **Alpha Vantage** | 무료 25/일 | 환율/매크로 백업 |

### TOP 10 빠른 추가 권장 (팀 D)

1. **Naver 검색 API** — 한국 뉴스 폴백, 0.5d, $0
2. **Naver 금융 종목토론 스크래퍼** — 한국 retail sentiment, 1d, $0
3. **YouTube Transcript 파이프라인** — 슈카/삼프로 종목 멘션, 2d, $0
4. **Tavily MCP** — Perplexity 영구 대체, 0.3d, $0~30/월
5. **FRED API 매크로 카드** — 미국 briefing 보강, 0.5d, $0
6. **SEC EDGAR MCP** — Form 4 + 13F, 1d, $0
7. **한국은행 ECOS** — 환율/금리, 0.5d, $0
8. **StockTwits trending** — 미국 retail mood, 0.5d, $0
9. **Reddit MCP (WSB)** — 미국 retail sentiment, 1d, $0
10. **Polygon.io starter** — 미국 실시간, 1d, $29/월

---

# 📁 보고서 메타정보

- **작성**: Claude (4팀 병렬 조사 종합)
- **조사 기간**: 2026-05-10 (단일 세션)
- **참여 팀**: Team A (MCP), Team B (Trading agents), Team C (Auto-scan), Team D (Multimodal)
- **검증 상태**: 조사 단계 완료, **채택 전 GitHub 직접 fetch 권장**
- **다음 액션**: 사용자 승인 → Phase 1 (Tier S 9개) 즉시 구현
- **관련 문서**:
  - `docs/mirofish_ascii_brain_admin_plan.md` — 초기 설계 (2026-05-02)
  - `docs/mirofish_phase2_plan_2026_05_02.md` — Phase 2 plan
  - `docs/mirofish_alpha_stock_detection_master_plan_2026_05_04.md` — Alpha Scanner master
- **저장소**: `/c/bitman_marketfloww/docs/mcp_deep_research_2026_05_10.md`

