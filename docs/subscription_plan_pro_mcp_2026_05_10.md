# 📐 MarketFlow MiroFish 구독 플랜 설계서 — PRO+MCP / Ultra PRO+MCP

**작성일**: 2026-05-10
**기준 가격**: PRO ₩50,000 + MCP add-on ₩40,000 = **PRO+MCP ₩90,000/월**
**대상**: MiroFish admin/endpoints 인프라 → 일반 사용자 SaaS 화

---

## 0. Executive Summary

| 사항 | 값 |
|---|---|
| Tier 수 | **5단계** (Free / PRO / PRO+MCP / Ultra / Ultra+MCP) |
| 최저가 / 최고가 | ₩0 / **₩190,000/월** |
| 손익분기점 | **PRO+MCP 4명** + 기존 Pro 30명 |
| 신규 인프라 비용 | **$0~50/월** (기존 재사용 + MCP 서버 host) |
| 출시 시점 | **3주** (Phase 1) |
| 마진 (PRO+MCP) | **약 96%** ($1.50/유저 운영비 기준) |

**MCP add-on 의 정체**: 사용자가 자기 도구 (Claude Desktop / Cursor / 자체 봇) 에서 우리 분석 엔진을 직접 호출하는 권한 — 즉, **MarketFlow 를 자기 워크플로우의 일부로 통합**.

---

## 1. 시장 포지셔닝 — ₩90,000 가격대 정당성

### 1.1 경쟁사 가격 비교 (월간)

| 서비스 | 가격 | 핵심 가치 |
|---|---|---|
| TradingView Premium | $59.95 (≒₩80,000) | 차트 + 기술적 지표 |
| 알파스퀘어 (한국) | ~₩99,000 | 퀀트 백테스트 |
| 슈퍼서치 (한국) | ₩100,000+ | 종목 검색 |
| Quantiwise (기관) | ₩200,000+ | 기관용 데이터 |
| **MarketFlow PRO+MCP** | **₩90,000** | **AI 자동화 + MCP 통합** |
| **MarketFlow Ultra+MCP** | **₩190,000** | **+ 실시간 + API + 자체 모델** |

**차별화 — 다른 서비스가 못 하는 것**:
1. **MCP 표준 통합** — Claude Desktop 에서 "삼성전자 분석해줘" → 자동 실행
2. **5인 페르소나 토론 + ReACT CIO** — 다른 곳에 없는 결과물
3. **한국 시장 + 미국 + Crypto 통합** — 단일 SaaS 에 3-market
4. **개인 알고리즘 통합** — API key 로 자기 자동화에 임베딩

### 1.2 타겟 사용자 페르소나

#### PRO+MCP (₩90,000)
- 개인 투자 자산 1-10억 규모
- 매월 구독 비용 < 수익 변동성 1% 미만
- Claude / ChatGPT / Cursor 적극 사용
- 자기 코드 / 노트북 + MarketFlow 결합 원함

#### Ultra+MCP (₩190,000)
- 개인 자산 10억+ 또는 가족사무소 / 소형 자문사
- 외부 시스템 (자기 트레이딩 봇, 텔레그램 알림 봇) 통합 원함
- 실시간 신호 + API 자동화 필수
- 1-on-1 지원 / 우선 응답 가치 인정

---

## 2. 5-Tier 구조 매트릭스

### 2.1 권한 + 한도 비교

| 영역 | Free | PRO | PRO+MCP | Ultra | Ultra+MCP |
|---|---|---|---|---|---|
| **월 가격** | ₩0 | ₩50,000 | **₩90,000** | ₩100,000 | **₩190,000** |
| **읽기 권한** | | | | | |
| Pre-computed (KOSPI 200 + S&P 500) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 24h 캐시 결과 보기 | ❌ | ✅ | ✅ | ✅ | ✅ |
| **분석 권한 (live LLM)** | | | | | |
| 일일 종목 분석 한도 | 0 | 5건 | 15건 | 30건 | 무제한 |
| Reflexion 메모리 누적 | ❌ | ✅ | ✅ | ✅ | ✅ |
| 5인 페르소나 토론 | ❌ | ✅ | ✅ | ✅ | ✅ |
| Bull/Bear debate round | ❌ | ❌ | ✅ | ✅ | ✅ |
| 차트 패턴 자동 인식 (Vision) | ❌ | ❌ | ✅ | ✅ | ✅ |
| **MCP 통합 ⭐** | | | | | |
| Claude Desktop 연결 | ❌ | ❌ | ✅ | ❌ | ✅ |
| 사용자 API key 발급 | ❌ | ❌ | ✅ | ❌ | ✅ |
| 자기 봇/스크립트 호출 | ❌ | ❌ | ✅ (rate-limit) | ❌ | ✅ (높은 quota) |
| 외부 cron / 워크플로우 | ❌ | ❌ | ✅ (5 schedules) | ❌ | ✅ (무제한) |
| Webhook 통합 | ❌ | ❌ | ❌ | ❌ | ✅ |
| **데이터 export** | | | | | |
| CSV / JSON 다운로드 | ❌ | ❌ | ✅ | ✅ | ✅ |
| Parquet bulk export | ❌ | ❌ | ❌ | ❌ | ✅ |
| 백테스트 raw 결과 | ❌ | ❌ | ✅ | ✅ | ✅ |
| **알림** | | | | | |
| 텔레그램 채널 (공통) | ✅ | ✅ | ✅ | ✅ | ✅ |
| 개인 텔레그램 봇 | ❌ | ❌ | ❌ | ✅ | ✅ |
| Webhook (Discord/Slack) | ❌ | ❌ | ❌ | ❌ | ✅ |
| Email (HTML 리포트) | ❌ | ✅ (주간) | ✅ (일간) | ✅ (실시간) | ✅ (실시간) |
| **자체 학습 모델** | | | | | |
| AlphaGen 자동 발굴 alpha 보기 | ❌ | ❌ | ❌ | ✅ | ✅ |
| FactorVAE TOP-N 결과 | ❌ | ❌ | ❌ | ✅ | ✅ |
| Reflexion 본인 메모리 export | ❌ | ❌ | ✅ | ✅ | ✅ |
| **지원** | | | | | |
| 텔레그램 그룹 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 1-on-1 채널 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 우선 응답 (24h 내) | ❌ | ❌ | ✅ | ✅ | ✅ |
| 전담 슬랙 채널 | ❌ | ❌ | ❌ | ❌ | ✅ |

### 2.2 한 줄 정의

- **Free**: "오늘의 KOSPI 200 + S&P 500 AI 분석 결과를 본다"
- **PRO**: "내가 보고 싶은 종목 5건/일 직접 분석"
- **PRO+MCP**: "내 Claude Desktop 에서 우리 AI 를 부른다 + 일 15건 + 자기 자동화"
- **Ultra**: "실시간 + 자체 학습 모델 + 무제한 + 1:1"
- **Ultra+MCP**: "Ultra + 자기 봇/시스템에 완전 통합 + Webhook + 우선순위"

---

## 3. ⭐ MCP Add-on 의 ₩40,000 가치 정당화

> **핵심 질문**: 왜 PRO 50,000 위에 +40,000 을 더해야 하나?

### 3.1 MCP add-on 만의 5대 차별 기능

#### 기능 1 — Claude Desktop / Cursor 직접 통합
사용자 PC 의 Claude Desktop 설정에 MarketFlow MCP 서버를 연결하면:
```
사용자: "삼성전자 MiroFish 분석해줘"
Claude Desktop → 우리 MCP 서버 호출 → MiroFish run → 결과를 사용자에게 표시
```
즉, **사용자가 우리 사이트를 열지 않아도** 자기 작업 흐름 안에서 분석 가능.

**기술적 가치**: 다른 SaaS 가 못 흉내내는 독점 기능 (MCP 표준 = 2025 신규).

#### 기능 2 — 사용자 API Key
PRO+MCP 가입 시 발급되는 API key:
```
sk_marketflow_pro_<user_id>_<random32>
```
사용자가 자기 노트북 / Jupyter / 자기 봇에서:
```python
import requests
r = requests.post(
    'https://api.bit-man.net/api/v1/mirofish/run',
    headers={'X-API-Key': 'sk_marketflow_pro_3_xyz...'},
    json={'target': '삼성전자', 'agent_count': 7}
)
```
**가치**: 자기 자동화 시스템에 우리 AI 결과를 임베딩.

#### 기능 3 — 사용자 cron / 워크플로우 (5개 schedules)
사용자가 자기 watchlist 를 매일 / 매시간 자동 분석:
```
매일 09:00 → ['삼성전자', '카카오', 'NVDA'] 자동 분석
매시간 → KOSPI 상승률 TOP 10 스캔
주간 일요일 → 보유 포트폴리오 backtest
```
결과는 사용자 텔레그램 / 이메일 / Webhook 으로 자동 발송.

#### 기능 4 — Bull/Bear debate round (5인 토론 후 직접 반박 라운드)
PRO 의 5인 토론 + **TradingAgents 패턴 추가**:
- Round 1: 5인 페르소나 의견
- Round 2: ⭐ 김리스크 ↔ 박모멘텀 직접 반박 (PRO+MCP 전용)
- Round 3: 이퀀트 / 최역발상 / 정헤지 종합 평가
- 최종: CIO ReACT 7-tool 판정

**가치**: 의견 수렴/발산 명확화, 더 깊은 분석.

#### 기능 5 — 차트 패턴 자동 인식 (Gemini Vision / Claude Vision)
사용자 종목 차트 자동 캡처 → Vision LLM 으로 패턴 인식:
- VCP (Volatility Contraction Pattern)
- Cup & Handle
- Head & Shoulders
- Mark Minervini SEPA Stage 2

**가치**: 사람이 차트 보고 패턴 발견하는 작업 자동화.

### 3.2 ₩40,000 add-on 가격 산정 근거

| 기능 | 1회 가치 (개인 추정) | 월 사용 빈도 | 월 가치 |
|---|---|---|---|
| Claude Desktop 통합 | ₩2,000/회 | 30회 | ₩60,000 |
| API key 자기 통합 | ₩1,500/회 | 50회 | ₩75,000 |
| Cron 자동 분석 | ₩500/회 | 60회 | ₩30,000 |
| Bull/Bear debate | ₩1,500/회 | 20회 | ₩30,000 |
| Chart Vision | ₩1,000/회 | 30회 | ₩30,000 |
| **합계 가치** | | | **₩225,000** |
| **할인 가격** | | | **₩40,000 (82% off)** |

→ "차익 ₩185,000" 마케팅 포인트 가능.

---

## 4. 기술 구현 설계

### 4.1 MCP 서버 호스팅

#### 옵션 A — 사용자 PC 직접 호스팅 (권장)
사용자가 자기 Claude Desktop 에 MCP 서버 등록:
```json
// ~/.config/claude/claude_desktop_config.json
{
  "mcpServers": {
    "marketflow-mirofish": {
      "command": "npx",
      "args": ["-y", "@marketflow/mirofish-mcp"],
      "env": {
        "MARKETFLOW_API_KEY": "sk_marketflow_pro_3_..."
      }
    }
  }
}
```

**장점**: 운영 비용 0 — 사용자 PC 에서 실행, 우리 API 만 호출
**구현**: npm 패키지 `@marketflow/mirofish-mcp` 게시 (TypeScript MCP server)

#### 옵션 B — 우리가 직접 호스팅 (Ultra+MCP 전용)
Cloudflare Workers 위에 MCP HTTP transport:
```
https://mcp.bit-man.net/sse
```
사용자가 자기 워크플로우 시스템 (Cline, Goose) 에서 SSE 연결.

### 4.2 신규 라우트 + 모듈

**Backend (`app/routes/v1_mirofish.py` 신규)** — MCP add-on 전용 API:
```python
POST   /api/v1/mirofish/run                  # MCP 호출 entry
GET    /api/v1/mirofish/runs/{id}            # 결과 조회
POST   /api/v1/mirofish/schedules            # cron 등록
GET    /api/v1/mirofish/schedules            # 내 cron 목록
DELETE /api/v1/mirofish/schedules/{id}       # cron 삭제
GET    /api/v1/mirofish/api-keys             # 내 키 목록
POST   /api/v1/mirofish/api-keys             # 신규 발급
DELETE /api/v1/mirofish/api-keys/{id}        # 폐기
GET    /api/v1/mirofish/quota                # 잔여 한도 조회
POST   /api/v1/mirofish/webhooks             # Ultra+MCP — Webhook 설정
```

**Auth**:
- 기존 admin token (브라우저) 와 분리된 **API key 시스템**
- HMAC SHA-256 서명 검증
- Rate limit: PRO+MCP 분당 5호출 / Ultra+MCP 분당 30호출

**DB 추가** (`users.db` SQLite):
```sql
CREATE TABLE api_keys (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,    -- bcrypt of 'sk_xxx'
    name TEXT,
    created_at TIMESTAMP,
    last_used_at TIMESTAMP,
    revoked_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE user_schedules (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    cron_expr TEXT NOT NULL,           -- '0 9 * * 1-5'
    target TEXT NOT NULL,              -- '삼성전자' 또는 watchlist json
    delivery_channel TEXT,             -- 'telegram' | 'email' | 'webhook'
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE user_quotas (
    user_id INTEGER PRIMARY KEY,
    daily_runs_used INTEGER DEFAULT 0,
    last_reset_at DATE,
    monthly_api_calls INTEGER DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### 4.3 결제 — Stripe 플랜 코드

```python
# app/services/stripe_plans.py
STRIPE_PLANS = {
    'pro': {
        'price_id': 'price_pro_50000_krw',
        'amount_krw': 50_000,
        'interval': 'month',
        'addons': [],
    },
    'pro_mcp': {
        'price_id': 'price_pro_mcp_90000_krw',
        'amount_krw': 90_000,
        'interval': 'month',
        'base': 'pro',
        'addons': ['mcp'],
    },
    'ultra': {
        'price_id': 'price_ultra_100000_krw',
        'amount_krw': 100_000,
        'interval': 'month',
        'addons': [],
    },
    'ultra_mcp': {
        'price_id': 'price_ultra_mcp_190000_krw',
        'amount_krw': 190_000,
        'interval': 'month',
        'base': 'ultra',
        'addons': ['mcp'],
    },
}

# 업그레이드/다운그레이드 시 prorated billing 자동 (Stripe)
```

### 4.4 frontend 변경

**신규 페이지**:
- `/billing` — tier 선택 + Stripe checkout
- `/account/api-keys` — API key 관리 + 재발급
- `/account/schedules` — 사용자 cron 목록 + 등록 UI
- `/account/quota` — 잔여 한도 시각화 (오늘 사용 5/15)

**기존 `AdminEndpointsPage.tsx`** — admin 전용 유지, 신규 사용자 페이지는:
- `MirofishConsolePage.tsx` — 일반 사용자용 (입력 + 분석 + 결과 보기)
- `MirofishMcpSetupPage.tsx` — Claude Desktop 통합 가이드

---

## 5. 비용 모델 — 100명 시나리오 (5-tier 분포)

### 5.1 사용자 분포 가정

| Tier | 인원 | 월 매출 |
|---|---|---|
| Free | 50 | ₩0 |
| PRO | 25 | ₩1,250,000 |
| **PRO+MCP** | **15** | **₩1,350,000** |
| Ultra | 7 | ₩700,000 |
| **Ultra+MCP** | **3** | **₩570,000** |
| **합계** | **100** | **₩3,870,000** |

### 5.2 운영 비용 추정

| 항목 | 월 비용 |
|---|---|
| LLM (Gemini Flash 주력) | ~$15 |
| LLM (Ultra Pro Claude/GPT-4o) | ~$10 |
| Tavily 검색 | $30 |
| FRED / ECOS / SEC EDGAR | $0 |
| Cloudflare Pages + tunnel | $0 |
| miniPC 전기 | ~₩30,000 = $20 |
| Stripe 수수료 (3.6%) | ₩139,000 |
| 기타 (이메일 SMTP / SMS) | $10 |
| **합계** | **~$85 = ₩115,000** |

### 5.3 마진

| 사항 | 값 |
|---|---|
| 월 매출 | **₩3,870,000** |
| 월 운영비 | ₩115,000 |
| **순이익** | **₩3,755,000** |
| **마진율** | **97%** |

### 5.4 손익분기점

- 운영비 ₩115,000 회수 ↔ **PRO+MCP 1.4명** = **2명** 가입 시 흑자
- PRO+MCP 4명 가입 시 영업이익 ₩245,000+

---

## 6. Phase 별 출시 로드맵

### Phase 1 — 3주 (PRO + PRO+MCP 베타)

**Week 1**:
- Day 1-2: DB 스키마 + API key 발급/검증 시스템
- Day 3-4: `/api/v1/mirofish/run` HMAC 인증 + rate limit
- Day 5: Stripe `pro` + `pro_mcp` 플랜 등록

**Week 2**:
- Day 1-2: `@marketflow/mirofish-mcp` npm 패키지 작성 (TypeScript MCP server)
- Day 3-4: `/billing` + `/account/api-keys` 페이지
- Day 5: 사용자 cron 시스템 (`scheduler.py` 사용자 task 추가)

**Week 3**:
- Day 1-2: Bull/Bear debate round 추가 (`agent_debate.py`)
- Day 3: Email HTML 리포트 (PRO 주간 / PRO+MCP 일간)
- Day 4: 베타 테스트 5명 모집
- Day 5: 출시 + 텔레그램 공지

### Phase 2 — 1개월 (Ultra / Ultra+MCP)

- Webhook (Discord/Slack) 통합
- 개인 텔레그램 봇 (사용자별 token)
- 차트 Vision 패턴 인식
- 1-on-1 슬랙 채널 자동 생성
- 자체 알고리즘 결과 (AlphaGen / FactorVAE) 노출

### Phase 3 — 2-3개월 (자체 모델 차별화)

- AlphaGen 자체 학습 (GPU 24h)
- FactorVAE 한국 시장 학습
- Reflexion 사용자별 개인화 메모리
- "내 PRO+MCP AI는 매주 학습한다" 마케팅

---

## 7. 마케팅 / 정당성 메시지

### 7.1 PRO+MCP 핵심 카피

> "이제 Claude / Cursor 에서 'MiroFish 분석해줘' 한 마디면 끝"
> 
> ✅ Claude Desktop / Cursor / Cline 직접 통합
> ✅ 사용자 API key — 자기 봇/노트북에서 호출
> ✅ 일 15건 무제한 분석 (PRO 5건 → 3배)
> ✅ Bull vs Bear 직접 토론 라운드
> ✅ 차트 패턴 자동 인식 (Vision AI)
> 
> **₩40,000 add-on = 5가지 차별 기능 = 시장가 ₩225,000 가치**

### 7.2 Ultra+MCP 핵심 카피

> "내 트레이딩 시스템에 우리 AI를 완전 임베딩"
> 
> ✅ 무제한 분석 + 실시간 LLM
> ✅ Webhook (Discord / Slack / 자기 봇)
> ✅ 자체 학습 알파 모델 결과
> ✅ 1-on-1 슬랙 채널 + 우선 응답
> ✅ Parquet 대량 export

---

## 8. 위험 + 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| API key 유출 | LLM 비용 폭발 | rate limit + IP allow-list + 즉시 폐기 UI |
| 가격대 거부감 | 가입율 낮음 | 14일 무료 체험 PRO+MCP |
| MCP 표준 변경 | 호환성 깨짐 | Anthropic spec follow + 자동 업데이트 |
| 사용자 자동화 abuse | 분당 호출 폭주 | 분당 5/30 hard cap + 일일 quota |
| Gemini API 가격 인상 | 마진 압박 | DeepSeek 폴백 + 자체 모델로 점진 이동 |
| 한국어 서비스 약관 미비 | 법적 리스크 | 약관 / 개인정보 / 환불 정책 명시 |

---

## 9. 즉시 실행 가능 — 다음 액션

1. ✅ **이 문서 승인** (가격 50/40/100/90 OK?)
2. ⏳ Stripe 한국 ₩ 통화 플랜 등록
3. ⏳ DB 스키마 마이그레이션 (api_keys / user_schedules / user_quotas)
4. ⏳ `app/routes/v1_mirofish.py` Blueprint 작성
5. ⏳ `@marketflow/mirofish-mcp` npm 패키지
6. ⏳ Frontend `/billing` 페이지

---

## 10. 결정 필요 사항

1. **가격 확정**: PRO ₩50,000 / +MCP ₩40,000 / Ultra ₩100,000 / +MCP ₩90,000 OK?
2. **무료 체험 기간**: 7일 / 14일?
3. **PRO+MCP 일일 한도**: 15건 적정한가? (10 or 20?)
4. **MCP 서버 배포 채널**: npm / GitHub release / Mac brew?
5. **API key 보안**: HMAC + IP allow-list 만으로 충분한가? (HMAC + JWT 추가?)
6. **출시 마케팅**: 텔레그램 채널 공지 / 이메일 / 커뮤니티 게시?

---

## 부록 — Claude Desktop 통합 사용자 가이드 (베타 매뉴얼 초안)

### Step 1 — PRO+MCP 가입
1. https://bit-man.net/billing 접속
2. PRO+MCP 선택 → Stripe 결제
3. 결제 완료 후 자동으로 API key 발급

### Step 2 — Claude Desktop 설정
1. Claude Desktop → Settings → Developer → Edit Config
2. 다음 추가:
```json
{
  "mcpServers": {
    "marketflow": {
      "command": "npx",
      "args": ["-y", "@marketflow/mirofish-mcp"],
      "env": {
        "MARKETFLOW_API_KEY": "sk_marketflow_pro_3_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
      }
    }
  }
}
```
3. Claude Desktop 재시작

### Step 3 — 사용
Claude Desktop 에서:
> "삼성전자 MiroFish 분석해줘"
> "내 watchlist (삼성, SK하이닉스, 카카오) 5인 토론 결과 보여줘"
> "지난주 KOSPI 200 TOP 10 변화 추적"

→ 우리 MCP 서버가 자동 호출 + 결과 표시.

---

**문서 링크**:
- 본 설계서: `docs/subscription_plan_pro_mcp_2026_05_10.md`
- 딥리서치: `docs/mcp_deep_research_2026_05_10.md` §9
- Phase 2 plan: `docs/mirofish_phase2_plan_2026_05_02.md`

**승인 후 Phase 1 (3주) 진행 — 단일 commit + 검증 게이트.**
