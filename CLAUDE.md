# KR Market Package - Claude Code 자율 운영 가이드
# v2.7.0 (Spring Boot Backend Migration)

## 1. 환경 설정 (절대 고정 - 변경 금지)

### 경로 변수 (모든 Bash 명령어에서 반드시 선언 후 사용)
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
FRONTEND="$PROJECT/frontend"
```

### 절대 규칙
1. **경로**: Windows 경로(`C:\...`) 사용 금지 → 항상 MINGW 경로: `/c/bitman_service`
2. **Python 실행**: 반드시 `"$PYTHON"` 변수 사용. `python`, `py` 직접 사용 금지
3. **인코딩**: Python 실행 시 `PYTHONIOENCODING=utf-8` 환경변수 필수 (cp949 에러 방지)
4. **작업 디렉토리**: 명령어 실행 전 반드시 `cd "$PROJECT"` 선행
5. **따옴표**: 모든 경로 변수는 큰따옴표(`"`)로 감싸기
6. **백그라운드**: 서버는 `&`로 백그라운드 실행 후 포트 확인

### 서버 관리
| 서비스 | 포트 | 시작 명령 |
|--------|------|----------|
| Flask API | 5001 | `cd "$PROJECT" && "$PYTHON" flask_app.py &` |
| Spring Boot | 8080 | `cd "$PROJECT/backend" && ./gradlew bootRun &` |
| Next.js | 4000 | `cd "$FRONTEND" && npm start &` |
| Scheduler | - | `cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" scheduler.py --daemon &` |

```bash
# 포트 확인
netstat -ano | grep -E "5001|8080|4000"
# 프로세스 종료
netstat -ano | grep 5001 | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {} 2>/dev/null
netstat -ano | grep 8080 | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {} 2>/dev/null
netstat -ano | grep 4000 | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {} 2>/dev/null
```

### 프론트엔드 환경변수 (`frontend/.env.local`)
```
NEXTAUTH_URL=http://localhost:4000
NEXTAUTH_SECRET=marketflow-nextauth-secret-change-in-production
AUTH_TRUST_HOST=true
BACKEND_URL=http://localhost:5001
SPRING_BOOT_URL=http://localhost:8080
NEXT_PUBLIC_API_URL=http://localhost:4000
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_placeholder
```

> **중요**: `NEXT_PUBLIC_API_URL`이 설정되면 클라이언트가 `/api/*` → Next.js rewrite → 백엔드로 요청.
> 비어있으면 `/api/data/*` 정적 스냅샷 모드 (Vercel 배포용).
> Summary 대시보드 3개 엔드포인트는 Spring Boot(8080)으로, 나머지는 Flask(5001)로 라우팅.

---

## 2. 프로젝트 아키텍처 (v2.7.0 Spring Boot 추가)

### 디렉토리 구조
```
/c/bitman_service/
├── flask_app.py              # Flask API 진입점 (포트 5001)
├── scheduler.py              # 통합 스케줄러 (US/KR/Crypto, 고정경로)
├── market_gate.py            # KR 시장 레짐 감지 (RISK_ON/OFF/NEUTRAL)
├── config.py                 # 루트 설정 (MarketGateConfig, BacktestConfig)
├── models.py                 # 루트 모델 (Signal, Trade - backtest용)
├── all_institutional_trend_data.py  # 기관 수급 데이터 수집 (scheduler 호출)
├── signal_tracker.py         # VCP 시그널 추적 (scheduler 호출)
├── sync_dashboard.py         # Vercel 데이터 동기화 (scheduler 호출)
├── sync-vercel.sh            # Vercel 배포 스크립트 (수동)
├── start.sh / start_all.bat  # 서버 시작 스크립트
├── .env                      # API 키 관리
│
├── backend/                  # === Spring Boot API (Java 21, Gradle) ===
│   ├── build.gradle.kts      # Spring Boot 3.4.3 + Caffeine
│   ├── gradlew / gradlew.bat # Gradle wrapper
│   └── src/main/java/com/bitman/marketflow/
│       ├── MarketFlowApplication.java     # 진입점 (포트 8080)
│       ├── config/            # AppConfig, CacheConfig, JacksonConfig
│       ├── controller/        # UsMarket, KrMarket, Crypto 컨트롤러
│       ├── service/           # 비즈니스 로직 (Flask 폴백 포함)
│       └── util/              # JsonFileReader (30s TTL 캐시)
│
├── engine/                   # === 종가베팅 V2 핵심 엔진 ===
│   ├── config.py             # V2 설정 (SignalConfig, Grade, 점수 가중치 17점)
│   ├── models.py             # V2 모델 (Signal, ScoreDetail, ChecklistDetail)
│   ├── collectors.py         # 데이터 수집 (KRXCollector, EnhancedNewsCollector)
│   ├── dart_collector.py     # OpenDART 호재공시 수집기
│   ├── llm_analyzer.py       # LLM 분석 + Multi-AI Consensus (Gemini+GPT-4o)
│   ├── scorer.py             # 점수 계산기 (17점 만점, DART+애널리스트 포함)
│   ├── position_sizer.py     # R 기반 포지션 사이징
│   └── generator.py          # 시그널 생성 메인 엔진 (run_screener)
│
├── app/                      # Flask Blueprint 앱
│   ├── __init__.py           # create_app() 팩토리 + Cache-Control 정책
│   ├── routes/
│   │   ├── kr_market.py      # KR API (/api/kr/*) — DATA_DIR 고정경로
│   │   ├── us_market.py      # US API (/api/us/*) — TTL 캐시 + 엔드포인트 최적화
│   │   ├── stock_analyzer.py # ProPicks API (/api/stock-analyzer/*)
│   │   ├── main.py           # 메인 라우트
│   │   └── auth.py           # 인증 API
│   └── utils/
│       ├── cache.py          # 파일 캐시 유틸
│       └── scheduler.py      # 앱 내 가격갱신 스케줄러 (V2 연동, 고정경로)
│
├── us_market/output/         # US 마켓 데이터 (유일한 데이터 소스)
│   ├── briefing.json         # AI Macro Briefing
│   ├── market_data.json      # VIX, Fear&Greed 등
│   ├── prediction.json       # AI 예측
│   ├── sector_heatmap.json   # 섹터 히트맵 데이터
│   ├── top_picks.json        # Smart Money Top Picks
│   ├── ai_summaries.json     # 종목별 AI 요약
│   ├── earnings_impact.json  # 어닝 임팩트 (sector_profiles)
│   ├── earnings_analysis.json # 어닝 분석 (upcoming_earnings 상세)
│   └── sector_rotation.json  # 섹터 로테이션 데이터
│
├── us_market_preview/output/ # → us_market/output/ 심링크 (하위호환)
│
├── frontend/                 # Next.js 14 대시보드
│   ├── .env.local            # 환경변수 (포트 4000/5001)
│   └── src/
│       ├── lib/api.ts        # API 유틸 (USE_DATA_PREFIX 로직)
│       ├── app/dashboard/
│       │   ├── us/
│       │   │   ├── page.tsx           # US 대시보드 메인
│       │   │   ├── briefing/page.tsx  # AI Macro Briefing
│       │   │   ├── heatmap/page.tsx   # Sector Heatmap
│       │   │   └── earnings/page.tsx  # Earnings Impact
│       │   ├── kr/closing-bet/page.tsx    # 종가베팅 대시보드
│       │   └── stock-analyzer/page.tsx    # ProPicks 분석 전용 페이지
│       └── components/layout/
│           ├── Header.tsx         # ⌘K 단축키 + CommandPalette
│           ├── Sidebar.tsx        # 사이드바 (ProPicks 포함)
│           └── CommandPalette.tsx  # 종목 검색 → 리다이렉트
│
├── data/                     # 데이터 저장소 (실시간)
│   ├── jongga_v2_latest.json      # 최신 종가베팅 결과
│   ├── jongga_v2_results_YYYYMMDD.json  # 날짜별 아카이브
│   ├── dart_corp_codes.json       # DART corp_code 매핑 캐시 (7일)
│   ├── daily_prices.csv           # 일별 가격 데이터
│   └── users.db                   # SQLite 유저 DB
│
├── archive/                  # 레거시 코드 보관 (실행 안됨)
│   └── legacy_v1/            # V1 스크립트, 백업 파일
│
├── backtest/                 # 백테스트 엔진
│   └── engine.py
│
└── chatbot/                  # AI 챗봇 (Gemini 기반)
    ├── core.py
    └── prompts.py
```

### 삭제된 파일 (v2.6.0 정리)
| 파일/디렉토리 | 이유 |
|-------------|------|
| `app.py` (root) | stock_analyzer Blueprint로 대체됨 |
| `stock_info.py` | app.py 전용 스크래핑, 미사용 |
| `stock_data.xlsx` | app.py/stock_info.py 전용 데이터 |
| `update_us.py` | us_market/update_all.py로 대체 |
| `start-local.sh` | 잘못된 포트. start.sh/start_all.bat로 대체 |
| `fix_path_issue.bat` | 1회성 경로 수정, 적용 완료 |
| `korean market/` | 2.9GB 프로젝트 통째 복사본 |
| `us-market-pro/` | 930MB 실험용 복사본 |
| `closing-bet-api/` | 390MB Java 프로젝트 (미완성) |
| `__MACOSX/` | 81MB macOS zip 아티팩트 |
| `claude-trading-skills/` | 38MB, skills/와 중복 |
| `backups/` | 139MB tar.gz, git 이력으로 대체 |
| `us_market_preview/*.py` | us_market/과 동일 중복. output/만 심링크로 유지 |
| `kr_market_package/` | 123MB 복사본 (v2.5에서 삭제) |

### 경로 고정 원칙 (모든 파일에 적용 완료)
| 파일 | 경로 방식 | 기준점 |
|------|----------|--------|
| `kr_market.py` | `DATA_DIR = _BASE_DIR + '/data'` | `__file__` 기반 절대경로 |
| `us_market.py` | `_OUTPUT_DIR + _PREVIEW_DIR` (심링크 통일) | `__file__` 기반 절대경로 |
| `app/utils/scheduler.py` | `BASE_DIR` / `DATA_DIR` | `__file__` 기반 절대경로 |
| `scheduler.py` | `Config.BASE_DIR` / `Config.DATA_DIR` | `__file__` 기반 + env 오버라이드 |
| `engine/generator.py` | `os.path.dirname(os.path.abspath(__file__))` | 엔진 패키지 기준 |

---

## 3. 종가베팅 V2 엔진 상세

### 실행 파이프라인
```
run_screener(capital=50_000_000)
  │
  ├─ 1. KRXCollector.get_top_gainers() → KOSPI/KOSDAQ 상승률 상위 30종목
  │
  ├─ 2. _analyze_stock() (각 종목별)
  │   ├─ get_stock_detail() → 52주 고가 등 보완
  │   ├─ get_chart_data(60일) → 이동평균, 차트 패턴
  │   ├─ asyncio.gather(뉴스수집, DART공시수집) → 병렬 실행
  │   ├─ LLM 뉴스 분석 (dart_text 포함)
  │   ├─ get_supply_data() → 5일 누적 수급
  │   ├─ Scorer.calculate() → 17점 만점 점수
  │   ├─ determine_grade() → S/A/B/C 등급
  │   └─ PositionSizer.calculate() → R 기반 포지션
  │
  ├─ 3. 등급순 정렬 (S > A > B, C등급 제외)
  │
  ├─ 4. MultiAIConsensusScreener.screen_candidates()
  │   ├─ GeminiScreener (gemini-2.5-flash) ─┐
  │   │                                       ├─ asyncio.gather (60초 타임아웃)
  │   ├─ OpenAIScreener (gpt-4o) ────────────┘
  │   └─ _build_consensus() → 교집합=CONSENSUS(confidence↑), 단독=하향
  │
  └─ 5. save_result_to_json() → data/jongga_v2_latest.json + 날짜별 아카이브
```

### 점수 체계 (17점 만점)
| 항목 | 배점 | 소스 | 설명 |
|------|------|------|------|
| 뉴스/재료 | 0~3 | LLM 분석 or 키워드 | Perplexity→Gemini→Claude→OpenAI→키워드 폴백 |
| 거래대금 | 0~3 | KRX 시세 | 500억↑:3, 100억↑:2, 5억↑:1 |
| 차트패턴 | 0~2 | 일봉 데이터 | 신고가+이평선 정배열 |
| 캔들형태 | 0~1 | 당일 시세 | 장대양봉, 윗꼬리 짧음 |
| 기간조정 | 0~1 | 60일 차트 | 변동성 축소 후 돌파 |
| 수급 | 0~2 | 투자자별 순매수 | 외인+기관 동시매수:2 |
| 공시(DART) | 0~2 | OpenDART API | 자사주/무상증자:2, 배당/합병:1, 악재:-2 |
| 애널리스트 | 0~3 | yfinance | 컨센서스 (Strong Buy:3, Buy:2, Hold:1) |

### 등급 기준 (17점 만점 기준)
| 등급 | 최소점수 | 최소거래대금 | R배수 |
|------|---------|------------|-------|
| S | 9/17 | 500억 | 1.5x |
| A | 7/17 | 100억 | 1.0x |
| B | 5/17 | 20억 | 0.5x |
| C | <5 | - | 0 (매매안함) |

---

## 4. 데이터 흐름 (End-to-End)

### KR 마켓 데이터 흐름
```
[Engine] run_screener()
    ↓ 저장
[JSON] data/jongga_v2_latest.json
    ↓ 읽기
[Flask] /api/kr/jongga-v2/latest  (kr_market.py → DATA_DIR 고정경로)
    ↓ fetch
[Next.js] page.tsx → ScreenerResult 인터페이스
    ↓ 렌더링
[Dashboard] http://localhost:4000/dashboard/kr/closing-bet
```

### US 마켓 데이터 흐름
```
[Scheduler] us_market/update_all.py → us_market/output/*.json
    ↓ 읽기 (30s TTL 캐시, _OUTPUT_DIR + _PREVIEW_DIR 심링크)
[Flask] /api/us/* (us_market.py)
    ↓ 데이터 변환 (프론트엔드 인터페이스 매핑)
[Next.js] /api/* → rewrite → Flask (BACKEND_URL 설정 시)
    ↓ 렌더링
[Dashboard] http://localhost:4000/dashboard/us/*
```

### US 엔드포인트 ↔ 프론트엔드 매핑
| Flask 엔드포인트 | JSON 소스 | 프론트엔드 페이지 | 데이터 변환 |
|----------------|----------|-----------------|-----------|
| `/api/us/market-briefing` | briefing.json + market_data.json + top_picks.json + sector_rotation.json | `/dashboard/us/briefing` | ai_analysis 구조화, VIX/Fear&Greed 추출, smart_money.picks 매핑 |
| `/api/us/heatmap-data` | sector_heatmap.json | `/dashboard/us/heatmap` | sector_groups → series: SectorSeries[] 변환 |
| `/api/us/earnings-impact` | earnings_impact.json + earnings_analysis.json | `/dashboard/us/earnings` | sector_profiles 유지, upcoming_earnings 병합/보강 |
| `/api/us/preview/prediction` | prediction.json | `/dashboard/us` | 직접 전달 |
| `/api/us/preview/sector-heatmap` | sector_heatmap.json | `/dashboard/us` | 직접 전달 |
| `/api/us/ai-summary/<ticker>` | ai_summaries.json (PREVIEW_OUTPUT_DIR 우선 → US_DATA_DIR 폴백) | `/dashboard/us` | 직접 전달 |
| `/api/us/decision-signal` | 7개 파일 병합 (localhost:5001) | `/dashboard/us` | 종합 신호 생성 |

### Signal.to_dict() 필드 (백엔드 → 프론트엔드 동기화 완료)
```python
{
    "stock_code", "stock_name", "market", "sector",
    "signal_date", "grade",
    "score": {news, volume, chart, candle, consolidation, supply, disclosure, total, llm_reason, llm_source},
    "checklist": {has_news, news_sources, volume_sufficient, is_new_high, is_breakout, ma_aligned,
                  good_candle, has_consolidation, supply_positive, has_disclosure, disclosure_types,
                  negative_news, upper_wick_long, volume_suspicious},
    "current_price", "entry_price", "stop_price", "target_price",
    "quantity", "position_size", "r_value", "r_multiplier",
    "trading_value", "change_pct", "volume_ratio",
    "foreign_5d", "inst_5d",
    "news_items", "themes"
}
```

---

## 5. API 키 관리 (.env)

| 키 | 용도 | 필수 |
|----|------|------|
| `GEMINI_API_KEY` | Gemini 2.5 Flash 분석 + 스크리닝 + AI Macro | O (핵심) |
| `OPENAI_API_KEY` | GPT-4o 스크리닝 | O (Multi-AI) |
| `PERPLEXITY_API_KEY` | 실시간 뉴스 검색 | 선택 (만료 가능) |
| `ANTHROPIC_API_KEY` | Claude 분석 (현재 비활성) | 선택 |
| `DART_API_KEY` | OpenDART 전자공시 | O (공시 기능) |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 알림 | 선택 |
| `TELEGRAM_CHANNEL_BOT_TOKEN` | 채널 전용 봇 | 선택 |

---

## 6. 프론트엔드 (Next.js)

### 핵심 파일
- `frontend/src/app/dashboard/kr/closing-bet/page.tsx` — 종가베팅 대시보드 메인
- `frontend/src/app/dashboard/us/briefing/page.tsx` — AI Macro Briefing
- `frontend/src/app/dashboard/us/heatmap/page.tsx` — Sector Heatmap
- `frontend/src/app/dashboard/us/earnings/page.tsx` — Earnings Impact
- `frontend/src/lib/api.ts` — API 유틸리티 (USE_DATA_PREFIX 로직)

### API 라우팅 로직 (api.ts)
```typescript
// NEXT_PUBLIC_API_URL 설정 시 → 직접 /api/* 호출 (Flask 프록시)
// NEXT_PUBLIC_API_URL 비어있으면 → /api/data/* 정적 스냅샷 (Vercel)
const API_BASE = process.env.NEXT_PUBLIC_API_URL || '';
const USE_DATA_PREFIX = !API_BASE;
```

### TypeScript 인터페이스 (백엔드 완전 동기화)
```typescript
// KR Market
ScoreDetail  { news, volume, chart, candle, consolidation, supply, disclosure, llm_reason, total }
AIPick       { stock_code, stock_name, rank, confidence, reason, risk, source?, gemini_rank?, openai_rank? }
AIPicks      { picks[], models?, consensus_count?, consensus_method? }
ChecklistDetail { has_news, volume_sufficient, is_new_high, is_breakout, ma_aligned, good_candle,
                  has_consolidation, supply_positive, has_disclosure?, disclosure_types?,
                  negative_news, upper_wick_long, volume_suspicious }
Signal       { stock_code, stock_name, market, sector?, grade, score, checklist,
               current_price, entry_price, stop_price, target_price, quantity?, position_size?,
               r_value?, r_multiplier?, change_pct, trading_value, volume_ratio?,
               foreign_5d, inst_5d, news_items?, themes? }
ScreenerResult { date, total_candidates, filtered_count, signals[], by_grade?, by_market?,
                 processing_time_ms?, updated_at, claude_picks? }

// US Market
BriefingData { ai_analysis: {content, citations}, vix: {value, change, level, color},
               fear_greed: {score, label, color}, smart_money: {top_picks: {picks[]}},
               sector_rotation, market_breadth }
EarningsImpactData { sector_profiles: {[sector]: SectorProfile}, upcoming_earnings[] }
SectorSeries { name: string, data: HeatmapItem[] }  // heatmap-data
```

### 버전: v2.5.0 (US Dashboard + Structural Optimization)

---

## 7. US Market 엔드포인트 데이터 변환 상세

### `/market-briefing` 데이터 변환
Flask가 여러 JSON 파일을 병합하여 프론트엔드 `BriefingData` 인터페이스에 맞게 변환:
```python
# briefing.json → ai_analysis 구조화
ai_analysis = { 'content': briefing.get('content'), 'citations': briefing.get('citations', []) }

# market_data.json → vix 추출
volatility = market_data.get('volatility', {})
vix_data = volatility.get('^VIX', {})
vix = { 'value': vix_data.get('current'), 'change': vix_data.get('change_pct'), 'level': ..., 'color': ... }

# fear_greed → color 추가
score = fear_greed.get('score', 50)
fear_greed['color'] = 'green' if score >= 60 else 'red' if score <= 40 else 'yellow'

# top_picks.json → smart_money.picks 매핑
'top_picks' → 'picks' (키 이름 변경)
'composite_score' → 'final_score', 'signal' → 'ai_recommendation'
```

### `/heatmap-data` 데이터 변환
```python
# sector_heatmap.json의 sector_groups dict → series 배열
for sector_name, stocks in sector_groups.items():
    items = [{'x': ticker, 'y': weight, 'price': price, 'change': change, 'color': ''}]
    series.append({'name': sector_name, 'data': items})
```

### `/earnings-impact` 데이터 병합
```python
# earnings_impact.json: sector_profiles (2개 이상)
# earnings_analysis.json: details[] → upcoming_earnings 보강
# 두 파일을 병합하여 sector_profiles + enriched upcoming_earnings 반환
```

---

## 8. 성능 최적화 (v2.5.0)

### _load_preview_json() TTL 캐시
```python
_preview_cache = {}  # {filename: (data, timestamp)}
_CACHE_TTL = 30      # seconds — US 데이터는 스케줄러 4h+ 간격 갱신

def _load_preview_json(filename):
    now = time.time()
    if filename in _preview_cache:
        data, ts = _preview_cache[filename]
        if now - ts < _CACHE_TTL:
            return data          # 캐시 적중 → 디스크 I/O 스킵
    # ... 파일 읽기 후 캐시 저장
```
- **효과**: 페이지 로드당 40+ 디스크 I/O → 캐시 적중 시 0 I/O
- `/decision-signal` 단독으로 7개 파일 로드 → 30초 내 재요청 시 즉시 응답

### Cache-Control 정책 (`app/__init__.py`)
```python
@app.after_request
def add_cache_headers(response):
    if 'application/json' in response.content_type:
        if not response.headers.get('Cache-Control'):
            response.headers['Cache-Control'] = 'public, max-age=30'  # 기본 30초
    return response
```
- **정적 JSON 엔드포인트**: `max-age=30` (브라우저 캐시 30초)
- **실시간 엔드포인트** (portfolio, market-gate): 개별 `no-cache, no-store` 설정

---

## 9. 알려진 이슈 & 해결법

| 이슈 | 원인 | 해결 | 버전 |
|------|------|------|------|
| `UnicodeEncodeError: cp949` | Windows 기본 인코딩 | `PYTHONIOENCODING=utf-8` 환경변수 | v2.0 |
| Perplexity 401 Unauthorized | API 키 만료 | LLM 폴백 체인이 Gemini로 자동 전환 | v2.0 |
| Anthropic API 사용불가 | API 크레딧 소진 | Multi-AI Consensus (Gemini+GPT-4o) 로 대체 | v2.2 |
| DART corp_code 첫 실행 느림 | ZIP 다운로드 | 7일 캐시 (`data/dart_corp_codes.json`) | v2.3 |
| 프론트엔드 체크리스트 미표시 | 중첩 vs 플랫 구조 불일치 | `to_dict()` 반드시 플랫 구조 | v2.3 |
| 경로 충돌 `'data/...'` | 상대경로 사용 | 모든 파일 `DATA_DIR` 절대경로 고정 완료 | v2.4 |
| Briefing "AI analysis not available" | Flask가 content/citations를 top-level로 반환 | `ai_analysis: {content, citations}` 구조화 | v2.5 |
| Briefing VIX/Fear&Greed null | market_data.volatility에서 미추출 | VIX 객체 빌드 + fear_greed.color 매핑 | v2.5 |
| Briefing "No picks available" | top_picks 키 이름/구조 불일치 | `top_picks→picks`, `composite_score→final_score` 매핑 | v2.5 |
| Heatmap "No data available" | sector_groups dict → series 배열 불일치 | `sector_groups→series: SectorSeries[]` 변환 | v2.5 |
| Earnings empty upcoming_earnings | earnings_impact.json에 빈 배열 | earnings_analysis.json 병합 보강 | v2.5 |
| `/decision-signal` 3초 타임아웃 | 존재하지 않는 포트 5002 호출 | `localhost:5001`로 수정 | v2.5 |
| `/ai-summary/<ticker>` 항상 404 | US_DATA_DIR에서만 검색 (파일 없음) | PREVIEW_OUTPUT_DIR 우선 → US_DATA_DIR 폴백 | v2.5 |
| 페이지 로드 지연 (40+ 디스크 I/O) | JSON 캐싱 없음 | 30초 TTL 인메모리 캐시 | v2.5 |
| 브라우저 매번 재요청 | 모든 JSON에 no-cache 적용 | 정적→`max-age=30`, 실시간만 no-cache | v2.5 |
| dead `/sector-heatmap` 라우트 | 11개 yfinance 호출, 프론트엔드 미사용 | 라우트 삭제 + api.ts getSectorHeatmap 제거 | v2.5 |
| `sync-vercel.sh` 잘못된 포트 | `FLASK_PORT=5002` | `FLASK_PORT=5001`로 수정 | v2.5 |
| 점수 체계 문서 불일치 | CLAUDE.md "14점", 실제 17점 | 문서 전체 17점 만점으로 수정 | v2.6 |
| us_market_preview 중복 | 36개 Python + output 이중 보관 | 스크립트 삭제, output 심링크 | v2.6 |
| ~4.5GB dead 디렉토리 | korean market, us-market-pro 등 6개 | 전체 삭제 | v2.6 |
| 6개 dead root Python 파일 | app.py, stock_info.py 등 미사용 | 전체 삭제 | v2.6 |
| api.ts 19개 dead 함수 | 프론트엔드에서 미호출 API 함수 | 삭제 | v2.6 |

---

## 10. 스킬 명령어 (자동 실행)

### 스킬 1: 종가베팅 V2 엔진 실행
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
import asyncio
from engine.generator import run_screener
asyncio.run(run_screener(capital=50_000_000))
"
```

### 스킬 2: 서버 전체 재시작
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
FRONTEND="$PROJECT/frontend"
netstat -ano | grep 5001 | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {} 2>/dev/null
netstat -ano | grep 4000 | awk '{print $5}' | sort -u | xargs -I{} taskkill //F //PID {} 2>/dev/null
sleep 2
cd "$PROJECT" && "$PYTHON" flask_app.py &
sleep 3
cd "$FRONTEND" && npm start &
sleep 5
netstat -ano | grep -E "5001|4000"
```

### 스킬 3: 프론트엔드 빌드 검증
```bash
PROJECT="/c/bitman_service"
cd "$PROJECT/frontend" && npx next build
```

### 스킬 4: 전체 검증 (임포트 + 경로 + 데이터모델)
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
from engine.generator import SignalGenerator, run_screener
from engine.llm_analyzer import LLMAnalyzer, MultiAIConsensusScreener
from engine.dart_collector import DARTCollector
from engine.scorer import Scorer
from engine.models import Signal, ScoreDetail, ChecklistDetail
from engine.config import SignalConfig, Grade
print('[1] Engine imports: OK')

from app import create_app
app = create_app()
routes = sorted([r.rule for r in app.url_map.iter_rules() if '/api/kr/' in r.rule])
print(f'[2] Flask app: OK ({len(routes)} KR routes)')

import os
from app.routes.kr_market import DATA_DIR
assert os.path.isdir(DATA_DIR), f'DATA_DIR missing: {DATA_DIR}'
print(f'[3] Path resolution: OK ({DATA_DIR})')

d = Signal().to_dict()
required = ['current_price', 'sector', 'r_multiplier', 'volume_ratio']
missing = [k for k in required if k not in d]
assert not missing, f'Missing: {missing}'
print(f'[4] Signal.to_dict(): OK')

print()
print('ALL CHECKS PASSED')
"
```

### 스킬 5: 최신 결과 확인
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
import json
with open('data/jongga_v2_latest.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
print(f'Date: {d[\"date\"]}  Signals: {d.get(\"filtered_count\", len(d.get(\"signals\",[])))}')
print(f'By Grade: {d.get(\"by_grade\", {})}')
for s in d['signals']:
    sc = s['score']
    print(f'  {s[\"grade\"]} | {s[\"stock_name\"]:12} | {sc[\"total\"]:2d}/14 | {s[\"change_pct\"]:+.1f}%')
picks = d.get('claude_picks', {})
print(f'AI: {len(picks.get(\"picks\",[]))} picks (Consensus:{picks.get(\"consensus_count\",0)})')
"
```

### 스킬 6: 단일 종목 재분석
```bash
PROJECT="/c/bitman_service"
PYTHON="$PROJECT/.venv/Scripts/python.exe"
STOCK_CODE="005930"
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" -c "
import asyncio
from engine.generator import analyze_single_stock_by_code
result = asyncio.run(analyze_single_stock_by_code('$STOCK_CODE'))
if result:
    d = result.to_dict()
    print(f'{d[\"stock_name\"]} | {d[\"grade\"]} | Score:{d[\"score\"][\"total\"]}')
else:
    print('Analysis failed or grade C')
"
```

### 스킬 7: US 엔드포인트 검증
```bash
PROJECT="/c/bitman_service"
echo "=== US Endpoint Check ==="
curl -s http://localhost:5001/api/us/market-briefing | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'  briefing: ai_analysis={\"content\" in d.get(\"ai_analysis\",{})}')
print(f'  vix: {d.get(\"vix\",{}).get(\"value\",\"N/A\")}')
print(f'  fear_greed: {d.get(\"fear_greed\",{}).get(\"score\",\"N/A\")}')
print(f'  picks: {len(d.get(\"smart_money\",{}).get(\"top_picks\",{}).get(\"picks\",[]))}')
" 2>/dev/null || echo "  briefing: FAILED"

curl -s http://localhost:5001/api/us/heatmap-data | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'  heatmap: {len(d.get(\"series\",[]))} sectors')
" 2>/dev/null || echo "  heatmap: FAILED"

curl -s http://localhost:5001/api/us/earnings-impact | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'  earnings: {len(d.get(\"sector_profiles\",{}))} profiles, {len(d.get(\"upcoming_earnings\",[]))} upcoming')
" 2>/dev/null || echo "  earnings: FAILED"

curl -s http://localhost:5001/api/us/decision-signal | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'  decision-signal: {d.get(\"signal\",\"N/A\")} (confidence: {d.get(\"confidence\",\"N/A\")})')
" 2>/dev/null || echo "  decision-signal: FAILED"
echo "=== Done ==="
```

---

## 11. 개발 패턴 & 규칙

### 코드 수정 시 체크리스트
1. **engine/ 수정** → 스킬 4 (전체 검증) → 스킬 1 (엔진 실행)
2. **frontend/ 수정** → 스킬 3 (빌드 검증) → 브라우저 확인
3. **models.py 수정** → `to_dict()` 플랫 구조 유지 → 프론트엔드 TS 인터페이스 동기화
4. **llm_analyzer.py 수정** → `analyze_news(dart_text)` 시그니처 동기화
5. **.env 수정** → 스킬 2 (서버 재시작)
6. **us_market.py 수정** → 스킬 7 (US 엔드포인트 검증) → 프론트엔드 확인
7. **us_market_preview/output/ JSON 구조 변경** → Flask 변환 로직 동기화 필수

### US 엔드포인트 수정 시 주의사항
- **_OUTPUT_DIR**: `us_market/output/` — 유일한 데이터 소스
- **_PREVIEW_DIR**: `us_market_preview/output/` — _OUTPUT_DIR 심링크 (동일 데이터)
- 프론트엔드 TS 인터페이스와 Flask 변환 로직 동기화 필수
- `_load_preview_json()` 캐시 TTL 30초 — 즉시 반영 필요 시 `_preview_cache.clear()` 호출

### 비동기 패턴
- 엔진 전체 `async/await` 기반
- 뉴스 + DART 공시: `asyncio.gather(return_exceptions=True)` 병렬
- Multi-AI 스크리닝: `asyncio.gather()` + `wait_for(timeout=60)` 병렬
- KRX 데이터: `asyncio.to_thread()` 동기→비동기 래핑

### JSON 호환성
- `claude_picks` 키 이름 유지 (프론트엔드 하위 호환) — 실제 Multi-AI Consensus
- `jongga_v2_latest.json` + `jongga_v2_results_YYYYMMDD.json` 이중 저장

### 에러 핸들링
- LLM: 폴백 체인 (Perplexity→Gemini→Claude→OpenAI→키워드)
- DART: 실패 시 빈 결과 (점수 0)
- Multi-AI: 한쪽 실패해도 나머지 결과 생성
- 수집기: `return_exceptions=True` 병렬 에러 격리

---

## 12. 스케줄러 실행 (고정 경로)

### 메인 스케줄러 (scheduler.py)
```bash
# 데몬 모드 (전체 스케줄 자동 실행)
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" scheduler.py --daemon

# 종가베팅 V2만 즉시 실행
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" scheduler.py --jongga-v2

# 전체 US+KR 즉시 실행
cd "$PROJECT" && PYTHONIOENCODING=utf-8 "$PYTHON" scheduler.py --now
```

### 스케줄 (KST)
| 시간 | 마켓 | 작업 |
|------|------|------|
| 04:00 | US | 전체 데이터 갱신 + Smart Money Top5 |
| 09:30 | US | Track Record 스냅샷 |
| 15:10 | KR | 종가베팅 V2 실행 → S/A급 텔레그램 |
| 16:00 | KR | 가격/수급/VCP/AI/리포트 |
| 매4시간 | Crypto | 전체 파이프라인 |

### 경로 설정
```python
Config.BASE_DIR     = /c/bitman_service          # __file__ 기반
Config.DATA_DIR     = /c/bitman_service/data
Config.PYTHON_PATH  = /c/bitman_service/.venv/Scripts/python.exe  # venv 우선
Config.LOG_DIR      = /c/bitman_service/logs
```

---

## 13. Stock Analyzer / ProPicks (Investing.com 스크래핑)

### 개요
Investing.com ProPicks 분석 결과(적극 매수/매수/중립/매도/적극 매도)를 종목별로 스크래핑하는 도구.
**대시보드 통합 완료** — 사이드바 ProPicks + ⌘K CommandPalette에서 접근 가능.

### 파일 구조
| 파일 | 역할 |
|------|------|
| **대시보드 통합** | |
| `app/routes/stock_analyzer.py` | Blueprint API (search, analyze, export) |
| `app/routes/__init__.py` | Blueprint 등록 (`/api/stock-analyzer`) |
| `frontend/src/app/dashboard/stock-analyzer/page.tsx` | 전용 분석 페이지 |
| `frontend/src/components/layout/CommandPalette.tsx` | ⌘K 검색 → 페이지 리다이렉트 |
| `frontend/src/components/layout/Sidebar.tsx` | ProPicks 네비 항목 |
| `frontend/src/components/layout/Header.tsx` | ⌘K 단축키 + CommandPalette 연동 |
| `frontend/next.config.ts` | API 프록시 (`/api/stock-analyzer/*` → Flask) |
| **독립 실행형** | |
| `app.py` | Flask 단독 웹앱 (포트 5000, UI 서빙) |
| `stock_info.py` | 일괄 스크래핑 스크립트 (2,500개 전체) |
| `stock_data.xlsx` | 종목 목록 (순번, 종목명, URL) 2,500건 |
| `templates/index.html` | 단독 웹 UI |

### API 엔드포인트
| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/stock-analyzer/search?q=삼성` | 종목 검색 (최대 20건) |
| POST | `/api/stock-analyzer/analyze` | 단건 스크래핑 (`{url, name}`) |
| POST | `/api/stock-analyzer/export` | 조회 기록 Excel 변환 (`{records}`) |

### 독립 실행 (v2.6.0에서 삭제됨)
> `app.py` (단독 웹앱)과 `stock_info.py` (일괄 스크래핑)은 v2.6.0에서 삭제.
> 기능은 `app/routes/stock_analyzer.py` Blueprint로 대시보드에 통합됨.

---

## 14. 변경 이력

### v2.7.0 (2026-03-03) — Spring Boot Backend Migration (Phase 1)
**Spring Boot 프로젝트 생성:**
- `backend/` 디렉토리에 Spring Boot 3.4.3 + Java 21 + Gradle (Kotlin DSL) 프로젝트 생성
- 3개 Summary Dashboard 엔드포인트 구현: `/api/us/market-briefing`, `/api/kr/market-gate`, `/api/crypto/dominance`
- US market-briefing: JSON 파일 직접 읽기 (Flask 로직 완전 이식)
- KR market-gate, Crypto dominance: Flask(5001) 폴백 방식 (라이브 연산은 Flask 유지)
- Caffeine 30초 TTL 캐시 (Flask `_CACHE_TTL=30` 동일)
- NaN/Infinity → null 변환 커스텀 Jackson 시리얼라이저

**프론트엔드 라우팅 분기:**
- `next.config.ts`: Summary 3개 엔드포인트 → Spring Boot(8080), 나머지 → Flask(5001)
- `.env.local`: `SPRING_BOOT_URL=http://localhost:8080` 추가

**아키텍처 전환 전략:**
- Phase 1 (현재): Summary 3개 엔드포인트만 Spring Boot
- Phase 2+: 추가 엔드포인트 점진적 마이그레이션, Flask 폴백 제거

### v2.6.0 (2026-02-27) — Codebase Cleanup + Scoring Fix
**Dead Code 제거 (~4.5GB):**
- 대형 디렉토리 6개 삭제: korean market(2.9GB), us-market-pro(930MB), closing-bet-api(390MB), backups(139MB), __MACOSX(81MB), claude-trading-skills(38MB)
- Root Python 6개 삭제: app.py, stock_info.py, update_us.py, stock_data.xlsx, start-local.sh, fix_path_issue.bat
- us_market_preview/ Python 스크립트 36개 삭제, output/ 심링크로 대체
- api.ts 미사용 함수 19개 삭제, DisclaimerBanner 컴포넌트 삭제
- bcryptjs 미사용 npm 패키지 제거

**문서 정정:**
- 점수 체계: 14점 → 17점 만점 (analyst:3 누락 수정)
- US 데이터 경로: us_market_preview → us_market/output 통일

**설정 정리:**
- next.config.ts 미사용 rewrite prefix 제거 (scheduler, portfolio)

### v2.5.0 (2025-02-25) — US Dashboard Endpoints + Structural Optimization
**엔드포인트 구현/수정:**
- `/market-briefing`: ai_analysis 구조화, VIX/Fear&Greed 추출, smart_money.picks 매핑
- `/heatmap-data`: sector_groups → series: SectorSeries[] 변환
- `/earnings-impact`: earnings_analysis.json 병합으로 upcoming_earnings 보강
- `/ai-summary/<ticker>`: PREVIEW_OUTPUT_DIR 우선 → US_DATA_DIR 폴백
- `/decision-signal`: 포트 5002→5001 수정

**구조 최적화:**
- 불필요 파일 삭제: login_output.txt, test_analyze.py, run_flask.py, start-frontend.sh
- kr_market_package/ 삭제 (123MB 중복)
- dead `/sector-heatmap` 라우트 삭제 (11개 yfinance 호출, 프론트엔드 미사용)
- api.ts에서 getSectorHeatmap 제거

**성능 개선:**
- `_load_preview_json()` 30초 TTL 인메모리 캐시 추가
- Cache-Control 정책: 정적 JSON → `max-age=30`, 실시간만 `no-cache`
- sync-vercel.sh 포트 5002→5001 수정

**환경 수정:**
- `.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:4000` 추가
- api.ts 포트 코멘트 5002→5001 수정

### v2.4.0 — Stock Analyzer Dashboard Integration
### v2.3.0 — DART + Multi-AI Consensus
### v2.2.0 — Signal 모델 완성
### v2.0.0 — 종가베팅 V2 엔진

---

## 15. 개발 도구 통합 (로컬 환경)

### 설치된 도구 및 CLI 활용법

| 도구 | 용도 | CLI 명령 |
|------|------|---------|
| **Everything** | 초고속 파일 검색 | `es.exe <검색어>` (CLI 버전) |
| **Postman** | API 테스트 | GUI 또는 `newman run <collection.json>` |
| **DB Browser for SQLite** | `.db` 파일 조회 | `sqlite3 data/users.db ".tables"` |
| **DevToys** | JSON 포맷팅, 인코딩 | GUI 도구 |
| **ngrok** | 로컬 서버 외부 노출 | `ngrok http 5001` (Flask) / `ngrok http 4000` (Next.js) |
| **Vercel CLI** | 프론트엔드 배포 | `cd frontend && vercel --prod` |
| **GitHub Desktop** | 소스 관리 GUI | GUI 도구 |
| **Cursor** | AI 코드 에디터 | GUI 도구 |
| **Notion** | 프로젝트 문서 관리 | GUI 도구 |

### 스킬 8: ngrok으로 로컬 서버 외부 공유
```bash
# Flask API 외부 노출 (모바일 테스트, 외부 공유용)
ngrok http 5001

# Next.js 대시보드 외부 노출
ngrok http 4000
```

### 스킬 9: SQLite DB 조회
```bash
PROJECT="/c/bitman_service"
sqlite3 "$PROJECT/data/users.db" ".tables"
sqlite3 "$PROJECT/data/users.db" "SELECT * FROM users LIMIT 10;"
```

### 스킬 10: Vercel 프론트엔드 배포
```bash
PROJECT="/c/bitman_service"
cd "$PROJECT/frontend" && vercel --prod
```

### 스킬 11: API 일괄 테스트 (curl 기반)
```bash
PROJECT="/c/bitman_service"
echo "=== API Health Check ==="
endpoints=(
  "http://localhost:5001/api/kr/jongga-v2/latest"
  "http://localhost:5001/api/kr/market-gate"
  "http://localhost:5001/api/us/market-briefing"
  "http://localhost:5001/api/us/heatmap-data"
  "http://localhost:5001/api/us/earnings-impact"
  "http://localhost:5001/api/us/decision-signal"
)
for ep in "${endpoints[@]}"; do
  status=$(curl -s -o /dev/null -w "%{http_code}" "$ep")
  echo "  [$status] $ep"
done
echo "=== Done ==="
```
