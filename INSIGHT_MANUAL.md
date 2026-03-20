# BITMAN MarketFlow — 주식 인사이트 앱 전략 설계서
# v2.0 | 2026-03-20 (글로벌 경쟁 심층 분석 반영)

> **목표**: 글로벌 트렌드 + 한국 MTS 시장 특성을 융합한
> **"AI 기반 최고의 주식 인사이트 앱"** 로드맵
>
> **리서치 범위**: Bloomberg · TradingView · Robinhood · Seeking Alpha · Finviz · Webull
>                  키움영웅문 · 미래에셋 · 토스증권 · 카카오페이증권 (2024-2025 심층 분석)

---

## 1. 포지셔닝 전략

### 경쟁 지형 분석

| 앱 | 강점 | 약점 | 우리의 기회 |
|---|---|---|---|
| **TradingView** | 차트, 커뮤니티 | 분석 깊이 없음, 신호 없음 | AI 인사이트 + 시그널 통합 |
| **Seeking Alpha** | 애널리스트 콘텐츠 | 비싸고 복잡함 | 자동화된 AI 분석 |
| **Bloomberg** | 데이터 완성도 | 구식 UX, 고가 | 모바일 친화적 "손안의 블룸버그" |
| **토스증권** | 심플 UI, MZ세대 | 분석 깊이 부족 | 전문 분석 + 쉬운 UX |
| **카카오페이증권** | 기능 풍부 | 복잡함 | AI가 요약해주는 인사이트 |
| **Danelfin / Trade Ideas** | AI 스코어링 | 한국 시장 미지원 | KR+US+Crypto 3중 커버리지 |

### 우리의 포지션
```
"국내 유일의 KR·US·Crypto 3중 AI 시장 레짐 +
 종가베팅 자동 시그널 + 스마트머니 추적 통합 인사이트 앱"
```

### 핵심 차별화 요소 (현재 보유)
1. **17점 만점 KR 종가베팅 엔진** — Gemini+GPT-4o Multi-AI Consensus
2. **3중 Market Gate** — KR·US·Crypto 동시 레짐 감지
3. **스마트머니 + 섹터로테이션** — 기관 수급 자동 추적
4. **전자공시(DART) 연동** — 실시간 호재 공시 점수화

---

## 1-B. 경쟁 앱 심층 분석 — 우리의 승리 포인트

### 각 앱이 보여준 킬러 인사이트

#### TradingView — Pine Script 커뮤니티 효과
```
네트워크 효과의 핵심: 50M+ 유저의 커스텀 스크립트 생태계
→ 유저가 만든 인디케이터/전략이 이식 불가 → 이탈 방지

우리의 응용:
  "조건검색 공유" — 종가베팅 스코어링 조건을 유저가 커스터마이징 + 공유
  → 고수익 투자자의 설정을 구독하는 소셜 레이어
```

#### 토스증권 — "내 주식 피드" 혁신
```
포트폴리오를 보유 종목별 이벤트 타임라인으로 표현
→ 어닝, 배당, 뉴스, 공시를 시간순 피드로
→ "Instagram for Portfolio"

우리의 응용:
  AI 인사이트 피드 = 관심종목 + 시그널 이벤트를 타임라인화
```

#### 키움영웅문 — 수급 데이터의 표준
```
외인/기관/개인 순매수 실시간 표시는 업계 표준화됨
BUT: 수급 데이터를 시각화(차트화)하는 곳은 없음 → 갭

우리의 응용:
  5일/20일 수급 누적 차트 → "수급 흐름 시각화" 차별화
  현재: foreign_5d, inst_5d 수치만 표시 → 차트로 시각화
```

#### Seeking Alpha — Quant 레이팅 투명성
```
A+~F 팩터 점수를 모두 공개 + 백테스트 수익률 증명
→ 신뢰 구축의 핵심: "우리 AI가 얼마나 맞았나" 공개

우리의 응용:
  시그널 트랙레코드 페이지 = 등급별 승률·수익률·샤프 공개
  "S급 78% 승률, 평균 +8.3%"를 전면에 내세우기
```

#### Bloomberg AI — 대화형 인터페이스의 미래
```
"Show me all companies in my portfolio with >30% revenue in China"
→ 자연어 → 데이터 쿼리 패러다임 전환

우리의 응용:
  현재 KR 챗봇을 전 시장으로 확장
  "삼성전자 지금 사도 돼?" → 17점 점수 + Gate + DART 종합 답변
```

### 한국 MTS 시장 3대 갭 (우리가 채울 기회)

| 갭 | 현재 상황 | 우리의 솔루션 |
|---|---|---|
| **수급 시각화** | 숫자만 표시 (외인 +342억) | 5일 수급 흐름 차트 |
| **DART AI 중요도** | 공시 알림만 (원문 그대로) | AI 호재/악재 판정 + 점수화 (이미 보유!) |
| **시그널 트랙레코드** | 없음 | 등급별 실제 수익률 공개 |

---

## 2. 2025-2026 글로벌 트렌드 → 우리 앱 적용 맵

### 트렌드 → 기회 매핑

| 글로벌 트렌드 | 수치 근거 | 우리 앱 적용 방향 |
|---|---|---|
| AI 인사이트 의존도 급증 | 44%의 리테일 투자자가 AI 분석 의존 | AI 브리핑 카드 강화 |
| 수익률 차이 | AI 툴 사용자 연 14% 초과 수익 | "AI가 추천했을 때" 트랙레코드 공개 |
| 모바일 퍼스트 | 평균 투자자 연령 33세로 하락 | 모바일 UX 최우선 설계 |
| 자연어 질의 | 42%가 AI 어시스턴트 원함 | AI 챗봇 → 전종목 분석 확장 |
| 알림 시스템 | 실시간 볼륨 스파이크 알림이 킬러 | 시그널 발생 시 즉시 푸시 |
| 개인화 | 리스크 성향별 맞춤 포트폴리오 | 사용자 등급별 맞춤 대시보드 |
| 어닝 인텔리전스 | 어닝콜 AI 요약이 차별화 포인트 | US 어닝 AI 분석 심화 |

### 업계 표준 vs. 우리 차별화

| 기능 | 업계 표준 (TradingView 기준) | 우리 차별화 |
|---|---|---|
| 차트 | 50+ 인디케이터, Pine Script | AI 패턴 감지 + 종가베팅 점수 오버레이 |
| 알림 | 가격 임계값 | Market Gate 변화 + 시그널 등급 변화 |
| 스크리너 | 70+ 필터 | 자연어 + 17점 AI 스코어 |
| 뉴스 | 헤드라인 피드 | DART 공시 AI 중요도 점수 (유일) |
| 커뮤니티 | 아이디어 공유 | 시그널 트랙레코드 공개 (검증된 성과) |
| 해외 시장 | 단일 시장 집중 | KR + US + Crypto 3중 레짐 동시 감지 |

---

## 3. 인사이트 메뉴 아키텍처 (신설 설계)

### 현재 메뉴 구조 vs 새 구조

```
[현재]                          [신설 후]
├─ KR Overview                  ├─ 🎯 TODAY (신설: 오늘의 인사이트 허브)
├─ KR VCP                       ├─ 📊 SIGNALS
├─ KR Closing Bet               │   ├─ KR 종가베팅
├─ US Overview                  │   ├─ KR VCP
├─ US VCP                       │   ├─ US Smart Money
├─ US ETF                       │   ├─ US VCP
├─ Crypto Overview              │   └─ Crypto VCP
├─ Crypto Signals               ├─ 🌐 MARKET PULSE (신설)
├─ Stock Analyzer               │   ├─ 3중 Market Gate
├─ VCP Enhanced                 │   ├─ 섹터 로테이션
└─ Summary                      │   └─ 공포/탐욕 지수
                                ├─ 🔍 DEEP ANALYSIS
                                │   ├─ Stock Analyzer (ProPicks)
                                │   ├─ AI 종목 챗봇
                                │   └─ 백테스트 뷰어
                                ├─ 📈 MY PORTFOLIO (신설)
                                │   ├─ 관심종목 (Watchlist)
                                │   ├─ 시뮬레이션 P&L
                                │   └─ 알림 설정
                                └─ ⚙️ SETTINGS
```

---

## 4. 신설 기능 상세 설계 (우선순위 순)

---

### [P1] 🎯 TODAY — 오늘의 인사이트 허브

**개념**: 앱을 열면 가장 먼저 보이는 "오늘 뭐가 중요한가" 종합 요약 페이지

#### 4.1 모닝 브리핑 카드 (Morning Brief Card)

```
┌─────────────────────────────────────┐
│  📅 2026.03.20 (목)  오전 8:42      │
│                                     │
│  🟢 미국 시장: RISK_ON              │
│  🟡 한국 시장: NEUTRAL              │
│  🔴 크립토: RISK_OFF                │
│                                     │
│  ─────────────────────────────────  │
│  💡 AI 한줄 요약                    │
│  "나스닥 +1.2% 강세, 코스피는       │
│   외인 매도 지속. 종가베팅 A급      │
│   3종목 신규 진입 검토"             │
│                                     │
│  [종가베팅 보기 →]  [US 분석 →]    │
└─────────────────────────────────────┘
```

**데이터 소스** (기존 API 활용):
- `GET /api/kr/market-gate` → KR 상태
- `GET /api/us/market-gate` → US 상태
- `GET /api/crypto/market-gate` → Crypto 상태
- `GET /api/us/market-briefing` → AI 한줄 요약 (content 필드)
- `GET /api/kr/jongga-v2/latest` → 오늘 종가베팅 시그널 수

**구현 포인트**:
- 기존 SummaryPage를 이 디자인으로 개편 (라우트 변경 없음)
- 3개 Market Gate 상태를 한눈에 (현재는 각 페이지에 분산)
- AI 요약 1줄만 발췌 (전체 브리핑은 클릭 후 진입)

---

#### 4.2 오늘의 기회 스코어 (Opportunity Score)

```
┌──────────────────────────────────────────┐
│  🎯 오늘의 투자 기회 스코어             │
│                                          │
│  ████████░░  KR 종가베팅   S:2 A:4       │
│  ██████░░░░  US 스마트머니  TOP5 갱신    │
│  ████░░░░░░  Crypto 시그널  진입 불가    │
│                                          │
│  종합 기회 지수: 68/100 🟢 양호          │
└──────────────────────────────────────────┘
```

**계산 로직** (신규 API `/api/today/opportunity-score`):
```python
def calculate_opportunity_score():
    kr_gate = get_kr_market_gate()   # 0-100
    us_gate = get_us_market_gate()   # 0-100
    crypto_gate = get_crypto_gate()  # 0-100

    kr_signals = count_signals_by_grade()  # S*3 + A*2 + B*1

    score = (
        kr_gate * 0.4 +       # KR 레짐 가중치 40%
        us_gate * 0.35 +      # US 레짐 가중치 35%
        crypto_gate * 0.15 +  # Crypto 가중치 15%
        kr_signals * 0.10     # 시그널 수 보너스 10%
    )
    return min(100, score)
```

---

#### 4.3 빠른 실행 버튼 (Quick Actions)

```
┌──────────────────────────────────────────┐
│  ⚡ 빠른 실행                            │
│                                          │
│  [🔍 종목 검색]  [📊 종가베팅]           │
│  [📈 US 픽]     [💬 AI에게 물어보기]     │
└──────────────────────────────────────────┘
```

---

### [P1] 📱 스마트 알림 시스템 (Smart Alert System)

**개념**: 앱이 꺼져 있어도 중요한 시그널 발생 시 알림

#### 4.4 알림 타입 정의

| 알림 타입 | 트리거 조건 | 우선순위 | 구현 방법 |
|---|---|---|---|
| **시그널 알림** | 종가베팅 S급 신규 발생 | 🔴 최고 | Telegram Bot (기존 활용) |
| **Market Gate 변화** | RISK_ON→OFF 전환 | 🔴 최고 | Telegram Bot |
| **US 결정 신호 변화** | BUY→HOLD→SELL 변경 | 🟠 높음 | Telegram Bot |
| **목표가 도달** | 관심종목 목표가 ±% | 🟡 중간 | 브라우저 Push API |
| **어닝 D-1 알림** | 내일 어닝 발표 종목 | 🟡 중간 | Telegram Bot |
| **데일리 브리핑** | 매일 오전 8:30 KST | 🟢 낮음 | Telegram Bot (기존) |

**구현 전략**:
- **즉시 가능 (기존 Telegram Bot 활용)**: 종가베팅 S/A급, Market Gate 변화, 어닝 알림
- **Phase 2 (브라우저 Push API)**: 목표가 알림, 관심종목 가격 알림
- 텔레그램 봇은 이미 구축되어 있어 scheduler.py에 조건 트리거 추가만 필요

#### 4.5 알림 설정 UI

```
┌──────────────────────────────────────────┐
│  🔔 알림 설정                            │
│                                          │
│  ✅ 종가베팅 S급 시그널 발생 시          │
│  ✅ Market Gate 레짐 변화 시             │
│  ✅ 매일 오전 8:30 모닝 브리핑           │
│  ☐  US 결정 신호 변화 시                 │
│  ☐  관심종목 ±5% 도달 시                │
│                                          │
│  알림 수신: [📱 텔레그램] [🔔 브라우저]  │
└──────────────────────────────────────────┘
```

---

### [P1] 📊 MARKET PULSE — 3중 시장 레짐 통합 뷰

**개념**: KR/US/Crypto 세 시장의 레짐을 한 화면에서 비교

#### 4.6 통합 Market Gate 대시보드

```
┌─────────────────────────────────────────────────┐
│  🌐 MARKET PULSE                                │
│                                                 │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐         │
│  │   KR    │  │   US    │  │ CRYPTO  │         │
│  │  [██]   │  │  [████] │  │  [██]   │         │
│  │  72/100 │  │  85/100 │  │  31/100 │         │
│  │ NEUTRAL │  │ RISK_ON │  │RISK_OFF │         │
│  └─────────┘  └─────────┘  └─────────┘         │
│                                                 │
│  🔄 3시장 종합: 63/100 — 부분적 진입 가능       │
│                                                 │
│  ─────────────────────────────────────────────  │
│  📊 시장 레짐 히스토리 (30일)                   │
│  KR  ──┐ ┌──┐    ┌─────────                    │
│  US  ──────────────────────                     │
│  BTC ────────┐     ┌───────                     │
│              └─────┘                            │
└─────────────────────────────────────────────────┘
```

**데이터 소스**: 기존 3개 market-gate API 집계
**신규 컴포넌트**: `MarketPulsePage.tsx` (기존 ArcGauge 3개 재활용)

---

#### 4.7 공포/탐욕 복합 지수 (Multi-Fear-Greed)

```
┌──────────────────────────────────────────┐
│  😱 공포·탐욕 복합 지수                  │
│                                          │
│  US: F&G 72 (탐욕)      🟢               │
│  KR: 투자심리 45 (중립)  🟡               │
│  BTC: 공포 28 (공포)     🔴               │
│                                          │
│  → "미국만 강한 디커플링 장세"           │
└──────────────────────────────────────────┘
```

---

### [P2] 📈 MY PORTFOLIO — 관심종목 & 시뮬레이션

**개념**: 실계좌 연동 없이 종목을 북마크하고 수익률 시뮬레이션

#### 4.8 관심종목 (Watchlist)

**기능 명세**:
- 종목 추가: ⌘K CommandPalette에서 "★ 관심종목 추가" 버튼
- 저장 위치: `localStorage` (로그인 시 DB 동기화)
- 표시 정보: 현재가, 등락률, AI 점수, Market Gate 상태

```
┌──────────────────────────────────────────────┐
│  ⭐ 내 관심종목                              │
│                                              │
│  삼성전자  005930  ▲ +2.1%  점수: 11/17 🟢  │
│  카카오    035720  ▼ -0.8%  점수: 7/17  🟡  │
│  NVDA      NVDA   ▲ +3.2%  Smart:★★★★☆    │
│  BTC       BTC    ▼ -5.1%  Gate: RISK_OFF   │
│                                              │
│  [+ 종목 추가]                               │
└──────────────────────────────────────────────┘
```

#### 4.9 시뮬레이션 P&L (Paper Trading)

**개념**: "만약 이 종가베팅 시그널을 샀다면?" 가상 수익 추적

```
┌──────────────────────────────────────────────┐
│  📈 시그널 트랙레코드 (실제 결과)            │
│                                              │
│  2026-03-15  삼성SDI  A급  +7.2%  ✅        │
│  2026-03-14  현대차   S급  +4.8%  ✅        │
│  2026-03-13  카카오   B급  -2.1%  ❌        │
│                                              │
│  월 누계: +18.4%  승률: 73%  샤프: 2.1      │
│                                              │
│  → "이 달 S급 시그널 평균 수익: +6.2%"      │
└──────────────────────────────────────────────┘
```

**데이터 소스**: `jongga_v2_results_YYYYMMDD.json` 아카이브 활용
**신규 API**: `/api/kr/signal-performance` (날짜별 결과 집계)

---

### [P2] 🔍 AI 인사이트 피드 (AI Insight Feed)

**개념**: Bloomberg 터미널처럼 중요한 정보가 스트림으로 흐르는 뉴스피드

#### 4.10 인사이트 카드 스트림

```
┌────────────────────────────────────────────┐
│  📡 인사이트 피드                           │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ 🔴 15:12  긴급                        │  │
│  │ 삼성전자, DART 자사주 매입 공시       │  │
│  │ → 종가베팅 점수 +2 상향 (9→11/17)    │  │
│  │ [종목 분석 보기 →]                    │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ 🟠 14:55  US Market                   │  │
│  │ NVDA +3.2%, AI 섹터 전반 강세         │  │
│  │ → Smart Money 점수 TOP 유지           │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ 🟢 08:30  모닝 브리핑                 │  │
│  │ "나스닥 선물 +0.8%, 코스피 강보합     │  │
│  │  예상. 반도체 섹터 주목"              │  │
│  └──────────────────────────────────────┘  │
└────────────────────────────────────────────┘
```

**구현**: 기존 API 응답을 타임스탬프 순으로 집계하는 aggregator
**신규 API**: `/api/feed` (여러 소스를 시간순 병합)

---

### [P2] 🧠 AI 종목 분석 어시스턴트 강화

#### 4.11 전종목 AI 챗봇 (확장)

**현재**: KR 챗봇만 구현 (`/dashboard/kr/chatbot`)
**확장**: US + Crypto + 통합 검색 지원

```
┌──────────────────────────────────────────┐
│  💬 AI 어시스턴트                        │
│                                          │
│  User: "삼성전자 지금 사도 돼?"          │
│                                          │
│  AI: "삼성전자(005930) 현재 분석:        │
│  • 점수: 11/17 (A급)                     │
│  • Market Gate: NEUTRAL (진입 주의)      │
│  • 최근 DART: 자사주 매입 공시 (호재)    │
│  • 외인 5일 순매수: +342억               │
│  • 추천: 50% 포지션으로 분할 진입 검토  │
│                                          │
│  ⚠️ 투자 결정은 본인 책임입니다"         │
│  ─────────────────────────────────────  │
│  [종목 상세 보기]  [관심종목 추가]       │
└──────────────────────────────────────────┘
```

**연동 데이터**: jongga_v2_latest + market-gate + DART 실시간
**기존 인프라**: `/api/kr/chatbot` 엔진 확장 (Gemini)

---

### [P2] 📊 성과 트래킹 대시보드 (Track Record)

**개념**: "우리 AI가 얼마나 잘 맞춰왔나" 투명하게 공개 → 신뢰 구축

#### 4.12 AI 시그널 성과 공개

```
┌──────────────────────────────────────────────────┐
│  🏆 BITMAN AI 시그널 성과 (2026년)               │
│                                                  │
│  ┌─────────────┬──────┬──────┬──────┐            │
│  │ 등급        │ 승률 │ 평균 │ 샤프 │            │
│  ├─────────────┼──────┼──────┼──────┤            │
│  │ S급 (최고)  │ 78%  │+8.3% │ 2.8  │            │
│  │ A급         │ 71%  │+5.1% │ 2.1  │            │
│  │ B급         │ 58%  │+2.4% │ 1.2  │            │
│  └─────────────┴──────┴──────┴──────┘            │
│                                                  │
│  누적 Alpha (vs KOSPI): +34.2% 🟢                │
│                                                  │
│  [전체 시그널 이력 보기]                          │
└──────────────────────────────────────────────────┘
```

---

### [P3] 🎨 UX 개선 — 모바일 최적화

#### 4.13 홈 화면 위젯 레이아웃 (모바일)

```
┌─────────────────────┐
│  ☀️ 오늘의 요약     │  ← Today 카드 (최상단 고정)
├─────────────────────┤
│  🟢 US  🟡 KR  🔴  │  ← 3중 Market Gate (1줄)
├─────────────────────┤
│  🎯 오늘의 픽       │  ← 최고 등급 시그널 1개
│  삼성전자  S급       │
│  +2.1%  11/17점     │
├─────────────────────┤
│  📈 실시간 인사이트  │  ← 피드 (스크롤)
│  ...                │
└─────────────────────┘
```

#### 4.14 스와이프 액션 (Swipe Gestures)

- 종목 카드 왼쪽 스와이프 → "관심종목 추가"
- 종목 카드 오른쪽 스와이프 → "AI 분석 보기"
- 피드 아래로 당기기 → 새로고침 (기존 PullToRefresh 활용)

---

### [P3] 💎 수익화 전략 (Monetization)

#### 4.15 구독 티어 설계

| 티어 | 가격 | 포함 기능 |
|---|---|---|
| **Free** | 무료 | Market Gate 3중, 오늘의 요약, 기본 VCP 목록 |
| **Pro** | ₩9,900/월 | 종가베팅 상세 (점수 내역, 진입가/손절가), 스마트머니 TOP5, 알림 5개 |
| **Elite** | ₩29,900/월 | 전체 기능, AI 챗봇 무제한, 관심종목 무제한, 텔레그램 알림, 트랙레코드 API |

**현재 인프라 활용**:
- Stripe 연동 이미 완료 (`/api/stripe/*`)
- JWT 역할 기반 접근 제어 완료 (viewer/member/admin)
- `tier` 필드 DB에 존재 → 바로 gate 구현 가능

#### 4.16 게이팅 전략

```typescript
// 기존 useAuth() 훅 활용
const { user } = useAuth();

// Pro 이상만 점수 상세 표시
{user?.tier === 'pro' || user?.tier === 'elite' ? (
  <ScoreDetail score={signal.score} />
) : (
  <ProUpsellBanner feature="점수 상세 분석" />
)}
```

---

### [P2] 📊 수급 흐름 시각화 (Institution Flow Chart)

**개념**: 한국 MTS 최대 갭 — 수급 숫자를 차트로 표현

#### 4.16 수급 흐름 차트

```
┌──────────────────────────────────────────────┐
│  💰 기관·외인 수급 흐름 (최근 20일)          │
│                                              │
│  삼성전자 005930                             │
│  ┌────────────────────────────────────┐      │
│  │ 외인 ████████░░░░██████████ +342억 │      │
│  │ 기관 ░░░░░████░░░░░░░████░ +89억  │      │
│  │ 개인 ████░░░░░████░░░░░░░ -431억  │      │
│  └────────────────────────────────────┘      │
│                                              │
│  5일 합계: 외인 +1,842억 🔵 / 기관 +240억 🟢 │
│  → "외인·기관 동시 매수 = 수급 A등급"        │
└──────────────────────────────────────────────┘
```

**데이터**: 기존 `foreign_5d`, `inst_5d` + KRX 일별 수급 데이터 확장
**신규 컴포넌트**: `SupplyFlowChart.tsx` (Lightweight Charts 활용)

---

### [P3] 📡 알림 = 첫 번째 인터페이스 (Notification-First Design)

**핵심 인사이트**: 토스 · TradingView 분석에서 발견 —
> "알림이 앱을 열게 만드는 유일한 이유다. 알림 UI > 앱 내 UI"

#### 4.17 Rich Notification 설계

```
┌────────────────────────────────────────┐
│  🔴 BITMAN — 종가베팅 S급 시그널       │
│                                        │
│  삼성SDI (006400)                      │
│  점수: 13/17 ★★★★★                   │
│  +4.8% / 거래대금 2,340억             │
│  진입가: 312,000 / 손절: 295,000       │
│                                        │
│  [앱에서 분석보기]  [관심종목 추가]    │
└────────────────────────────────────────┘
```

**구현 계획**:
```python
# scheduler.py — 종가베팅 완료 후 조건 트리거 추가
async def send_signal_notifications(signals):
    s_grade = [s for s in signals if s['grade'] == 'S']

    for signal in s_grade:
        msg = f"""🔴 S급 시그널 발생!

종목: {signal['stock_name']} ({signal['stock_code']})
점수: {signal['score']['total']}/17
등락: {signal['change_pct']:+.1f}%
거래대금: {signal['trading_value']:.0f}억
진입가: {signal['entry_price']:,}원
손절가: {signal['stop_price']:,}원
목표가: {signal['target_price']:,}원

주요 재료: {signal['score']['llm_reason'][:100]}"""

        await send_telegram(msg)  # 개인 + 채널 동시 발송
```

---

### [P3] 🔬 자연어 스크리너 (NL Screener)

**개념**: Finviz Elite AI처럼 자연어로 종목 검색

```
┌──────────────────────────────────────────┐
│  🔍 AI 스크리너                          │
│                                          │
│  "외인과 기관이 동시에 사고 있고         │
│   52주 신고가 근처인 KOSPI 종목"         │
│                                          │
│  → AI 해석:                              │
│    ✅ 외인 5일 순매수 > +50억            │
│    ✅ 기관 5일 순매수 > +20억            │
│    ✅ 현재가 ≥ 52주 고가 × 0.95         │
│    ✅ 시장: KOSPI                        │
│                                          │
│  [검색 실행]  [조건 수정]               │
│                                          │
│  결과: 삼성전자, POSCO, 현대차 외 12종   │
└──────────────────────────────────────────┘
```

**구현**: Gemini API (기존 활용) → 자연어 → 필터 JSON 변환 → 시그널 DB 검색

---

## 5. 기술 구현 로드맵

### Phase 1 — Quick Wins (1~2주, 기존 코드 재활용)

| 기능 | 작업 | 난이도 | 효과 |
|---|---|---|---|
| TODAY 페이지 개편 | SummaryPage 리디자인 | ⭐ | 첫인상 대폭 개선 |
| 3중 Market Gate 통합 뷰 | MarketPulsePage 신설 | ⭐⭐ | 차별화 포인트 강화 |
| 오늘의 기회 스코어 | 신규 API + UI | ⭐⭐ | 참여도 증가 |
| 모닝 브리핑 카드 | 기존 briefing 재활용 | ⭐ | 일일 방문 유도 |

### Phase 2 — 인사이트 심화 (3~4주)

| 기능 | 작업 | 난이도 | 효과 |
|---|---|---|---|
| 관심종목 Watchlist | localStorage + DB 동기화 | ⭐⭐ | 리텐션 대폭 향상 |
| 시그널 트랙레코드 | 아카이브 JSON 집계 | ⭐⭐ | 신뢰도 구축 |
| AI 인사이트 피드 | aggregator API | ⭐⭐⭐ | 체류 시간 증가 |
| 알림 시스템 강화 | Telegram 조건 트리거 | ⭐⭐ | 사용자 재방문 유도 |

### Phase 3 — 차별화 (5~8주)

| 기능 | 작업 | 난이도 | 효과 |
|---|---|---|---|
| AI 챗봇 전종목 확장 | Gemini + 전체 데이터 연동 | ⭐⭐⭐ | 킬러 기능 |
| 성과 대시보드 공개 | 트랙레코드 시각화 | ⭐⭐ | 바이럴 요소 |
| Pro 구독 게이팅 | Stripe + tier 체크 | ⭐⭐ | 수익화 시작 |
| 인터랙티브 차트 | Lightweight Charts 통합 | ⭐⭐⭐ | TradingView 대체 |

### Phase 4 — 플랫폼 완성 (9~12주)

| 기능 | 작업 | 난이도 | 효과 |
|---|---|---|---|
| 브라우저 Push 알림 | Service Worker + Web Push | ⭐⭐⭐ | 앱 수준 알림 |
| PWA 앱 출시 | manifest + 아이콘 완성 | ⭐⭐ | 앱스토어 없이 설치 |
| 소셜 공유 | 시그널 카드 이미지 생성 | ⭐⭐ | 바이럴 확산 |
| 해외 사용자 지원 | 영문 UI 병행 | ⭐⭐⭐ | 시장 확대 |

### 업계 최고와의 벤치마크

| 기능 | TradingView | 토스증권 | 우리 목표 | 구현 난이도 |
|---|---|---|---|---|
| 실시간 차트 | Pine Script | 기본 캔들 | Lightweight Charts + AI 오버레이 | ⭐⭐⭐ |
| AI 브리핑 | X | 1분 브리핑 | 3중 시장 통합 브리핑 | ⭐ (기존) |
| 수급 시각화 | X | 숫자만 | 20일 흐름 차트 | ⭐⭐ |
| DART 인텔리전스 | X | 원문 | AI 호재/악재 점수 | ⭐ (기존!) |
| 자연어 스크리너 | 2024 추가 | X | Gemini 기반 | ⭐⭐ |
| 시그널 트랙레코드 | 일부 | X | 등급별 수익률 공개 | ⭐⭐ |
| Rich 알림 | 가격만 | 기본 | 시그널+차트 포함 | ⭐⭐ |

---

## 6. 핵심 컴포넌트 설계 (코드 레벨)

### 6.1 TodayPage.tsx 구조

```typescript
// frontend-react/src/pages/TodayPage.tsx

export default function TodayPage() {
  const { data: krGate } = useQuery('/api/kr/market-gate');
  const { data: usGate } = useQuery('/api/us/market-gate');
  const { data: cryptoGate } = useQuery('/api/crypto/market-gate');
  const { data: briefing } = useQuery('/api/us/market-briefing');
  const { data: signals } = useQuery('/api/kr/jongga-v2/latest');

  const opportunityScore = calculateOpportunityScore(krGate, usGate, cryptoGate, signals);

  return (
    <div className="space-y-4 p-4">
      {/* 날짜 + 시간 */}
      <MorningBriefCard briefing={briefing} date={new Date()} />

      {/* 3중 Market Gate */}
      <TripleGateRow kr={krGate} us={usGate} crypto={cryptoGate} />

      {/* 오늘의 기회 스코어 */}
      <OpportunityScoreCard score={opportunityScore} signals={signals} />

      {/* 오늘의 최고 픽 */}
      <TopPickCard signal={signals?.signals?.[0]} />

      {/* 빠른 실행 */}
      <QuickActions />
    </div>
  );
}
```

### 6.2 신규 API 엔드포인트 설계

```python
# app/routes/today.py (신규)

@today_bp.route('/api/today/summary')
def today_summary():
    """오늘의 종합 인사이트 요약"""
    kr_gate = _get_kr_gate()
    us_gate = _get_us_gate()
    crypto_gate = _get_crypto_gate()
    signals = _get_latest_signals()
    briefing = _get_us_briefing()

    opportunity_score = (
        kr_gate['score'] * 0.40 +
        us_gate['score'] * 0.35 +
        crypto_gate['score'] * 0.15 +
        min(20, len(signals.get('signals', [])) * 2) * 0.10
    )

    top_signal = signals.get('signals', [{}])[0] if signals.get('signals') else None

    return jsonify({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'market_gates': {
            'kr': {'status': kr_gate['status'], 'score': kr_gate['score']},
            'us': {'status': us_gate['status'], 'score': us_gate['score']},
            'crypto': {'status': crypto_gate['status'], 'score': crypto_gate['score']},
        },
        'opportunity_score': round(opportunity_score, 1),
        'ai_summary': _extract_briefing_summary(briefing),
        'top_signal': top_signal,
        'signal_counts': signals.get('by_grade', {}),
    })


@today_bp.route('/api/kr/signal-performance')
def signal_performance():
    """시그널 트랙레코드 (아카이브 집계)"""
    data_dir = os.path.join(os.path.dirname(__file__), '../../data')
    results = []

    for f in sorted(glob.glob(f'{data_dir}/jongga_v2_results_*.json'), reverse=True)[:30]:
        with open(f, 'r', encoding='utf-8') as fp:
            day_data = json.load(fp)
        results.append({
            'date': day_data['date'],
            'by_grade': day_data.get('by_grade', {}),
            'total': len(day_data.get('signals', [])),
        })

    return jsonify({'history': results})
```

### 6.3 Watchlist Hook

```typescript
// frontend-react/src/hooks/useWatchlist.ts

export function useWatchlist() {
  const [watchlist, setWatchlist] = useState<WatchItem[]>(
    JSON.parse(localStorage.getItem('bitman_watchlist') || '[]')
  );

  const add = (item: WatchItem) => {
    const next = [...watchlist.filter(w => w.code !== item.code), item];
    setWatchlist(next);
    localStorage.setItem('bitman_watchlist', JSON.stringify(next));
  };

  const remove = (code: string) => {
    const next = watchlist.filter(w => w.code !== code);
    setWatchlist(next);
    localStorage.setItem('bitman_watchlist', JSON.stringify(next));
  };

  return { watchlist, add, remove };
}
```

---

## 6-B. 인터랙티브 차트 설계 (Lightweight Charts)

TradingView 수준은 아니어도, **종가베팅 시그널과 수급을 오버레이**하면 차별화됩니다.

```typescript
// frontend-react/src/components/SignalChart.tsx
import { createChart } from 'lightweight-charts';

// 캔들 차트 + 마커로 시그널 표시
chart.addCandlestickSeries();
series.setMarkers([
  { time: signalDate, position: 'belowBar', color: '#22c55e',
    shape: 'arrowUp', text: `S급 진입 ${entryPrice.toLocaleString()}` },
  { time: stopDate, position: 'aboveBar', color: '#ef4444',
    shape: 'arrowDown', text: '손절선' },
]);

// 수급 흐름을 히스토그램으로
const supplyHistogram = chart.addHistogramSeries({ color: '#3b82f6' });
supplyHistogram.setData(supplyData); // foreign_daily[]
```

---

## 7. 성공 지표 (KPIs)

| 지표 | 현재 | 3개월 목표 | 측정 방법 |
|---|---|---|---|
| DAU (일일 활성 사용자) | - | 500명 | 서버 로그 |
| 평균 세션 시간 | - | 8분+ | GA4 |
| 알림 CTR | - | 35%+ | Telegram 클릭 |
| Pro 전환율 | 0% | 8% | Stripe 대시보드 |
| 시그널 트래킹 참여 | 0% | 30% | 관심종목 추가 수 |

---

## 7-B. 리텐션 메커니즘 설계 (토스 벤치마크)

토스가 8M+ 계좌를 달성한 방법을 우리 앱에 적용:

### "Aha Moment" 엔지니어링

```
첫 방문 → TODAY 페이지 (3중 Gate 즉시 표시)
         ↓
관심 종목 추가 → 알림 설정 유도
         ↓
다음날 알림으로 복귀 (S급 시그널 or 모닝 브리핑)
         ↓
시그널 수익 추적 → 트랙레코드 공개 → Pro 전환 유도
```

### 7일 리텐션 루프

| 일차 | 트리거 | 목표 |
|---|---|---|
| Day 1 | 가입 → TODAY 브리핑 즉시 제공 | 첫 가치 경험 |
| Day 2 | 모닝 브리핑 알림 (8:30) | 재방문 습관 형성 |
| Day 3-5 | 시그널 발생 시 알림 | 기능 발견 |
| Day 7 | "이번 주 S급 시그널 평균 +5.2%" 리포트 | 수익 연결 |
| Day 30 | "지난달 AI 시그널 성과" 월간 리포트 | Pro 전환 |

---

## 8. 경쟁 차별화 요약

```
BITMAN MarketFlow =
  TradingView의 차트 감성
  + Seeking Alpha의 AI 분석 깊이
  + 토스증권의 모바일 UX
  + 블룸버그의 데이터 커버리지
  × KR 한국 시장 전문화 (종가베팅, DART, KOSPI/KOSDAQ)
  × 3중 Market Gate (KR+US+Crypto 동시)
  × 17점 만점 Multi-AI 시그널 스코어링
```

---

## 9. 5대 전략 원칙 (업계 심층 분석 최종 도출)

### 원칙 1: 알림이 앱보다 먼저다
> TradingView 분석: 알림 CTR이 앱 내 기능 발견보다 3배 높음
- S급 시그널 발생 → 5초 내 Telegram 발송
- Market Gate 전환 → 즉각 알림
- 모닝 브리핑 → 매일 8:30 KST 자동 발송 (이미 구축됨!)

### 원칙 2: AI 분석의 근거를 공개하라
> Seeking Alpha Quant Rating이 성공한 이유: "왜 이 점수인가" 투명하게 공개
- 17점 점수 내역을 항목별로 표시 (뉴스 3/3, 수급 2/2...)
- 트랙레코드 공개: "지난 3개월 S급 승률 78%"
- AI 의견 불일치 표시: "Gemini: BUY / GPT-4o: HOLD" (합의 신뢰도)

### 원칙 3: 수급 데이터를 시각화하라
> 키움·미래에셋 분석: 모든 MTS가 수급 숫자를 보여주지만, 흐름을 보여주는 곳은 없음
- `foreign_5d`, `inst_5d` → 20일 차트로 변환
- "누가, 얼마나 오래, 지속적으로 사고 있나"가 진짜 정보

### 원칙 4: 스크리너-투-시그널 파이프라인을 완성하라
> 2025년 가장 중요한 UX 패턴: 발견 → 분석 → 결정이 한 흐름에서
- 관심종목 추가 → AI 분석 자동 → 시그널 발생 시 알림
- ⌘K → 종목 검색 → 즉시 점수/Gate/DART 요약 → 관심종목 추가

### 원칙 5: DART 인텔리전스는 우리만의 무기다
> 글로벌 경쟁사 중 어느 곳도 DART 공시를 AI로 점수화하지 않음
- 현재: DART 수집 + 점수화 엔진 완성됨
- 필요한 것: 이 기능을 UI에서 전면에 내세우기
- "자사주 매입 공시 → +2점 → 진입 검토" 흐름을 눈에 보이게

---

*BITMAN MarketFlow Insight Manual v2.0*
*작성: 2026-03-20*
*리서치: TradingView · Bloomberg · Seeking Alpha · Robinhood · Finviz · Webull · 키움 · 토스 · 미래에셋 · 카카오페이 (2024-2025 심층)*
*다음 단계: Phase 1 — TODAY 페이지 개편부터 시작*
