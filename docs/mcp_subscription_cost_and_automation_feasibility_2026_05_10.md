# MCP 구독 서비스 운영비와 자동화 구현 가능성 보고서

작성일: 2026-05-10
범위: MarketFlow/MiroFish MCP endpoint를 구독형 서비스로 제공할 때의 운영비, 적정 가격, 자동화 구현 가능성
제외: 유료 금융 데이터 라이선스, 거래소/증권사 데이터 재판매 계약, 개별 알파 팩터 성능 검증

## 1. 결론

MCP 자체는 비싼 기능이 아니다. 비용의 대부분은 **AI 분석 호출, 자동 스케줄 실행, 사용자별 저장/알림/지원, 결제 수수료**에서 발생한다.

권장 가격은 다음과 같다.

| 상품 | 월 가격 권장 | 포함 범위 | 판단 |
|---|---:|---|---|
| Free | 0원 | 공개/지연 캐시 일부, MCP 없음 | 유입용 |
| Pro | 29,000원 | 웹 UI, 캐시 기반 분석, 제한적 live 분석 | 현재 서비스 기본 유료층 |
| Pro+MCP | 59,000원 | read-only MCP, API key, 월 30-50회 live explain, 제한 스케줄 | 개인 투자자용 적정가 |
| Ultra+Automation | 129,000원 | 원격 MCP, webhook, 월 150-250회 live 분석, debate/backtest 제한 포함 | 자동화 사용자를 위한 주력 고마진 상품 |
| Advisor/Team | 299,000-499,000원 | 다계정, 높은 quota, 우선 지원, 별도 SLA | B2B/고액 사용자 |

가격 하한은 다음처럼 보는 것이 안전하다.

- **MCP read-only add-on만** 팔면 19,000-29,000원도 가능하다.
- **MCP + 자동 분석/스케줄**을 팔면 49,000원 미만은 위험하다.
- **heavy debate, chart vision, backtest 자동화**까지 포함하면 99,000원 이상이어야 원가와 지원비를 흡수한다.
- 초기 출시가는 **Pro+MCP 59,000원, Ultra+Automation 129,000원**을 권장한다.

## 2. 비용 구조

### 2.1 고정비

현재 MarketFlow 구조는 Cloudflare Pages frontend, Flask API `5001`, Cloudflare Tunnel `marketflow-api.bit-man.net`, scheduler 기반이다. 기존 MiniPC/홈서버를 유지하면 현금 고정비는 낮지만, 구독 서비스에는 장애 대응/SLA 리스크가 있다.

| 항목 | Bootstrap | Production 권장 | 비고 |
|---|---:|---:|---|
| Frontend | $0 | $0-20/월 | Cloudflare Pages 재사용 가능 |
| MCP gateway | $0-5/월 | $5-20/월 | Cloudflare Workers paid plan 또는 tunnel routing |
| Backend host | $0-15/월 | $25-80/월 | MiniPC 전기료 vs Render/Fly/VPS |
| DB/storage | $0 | $20-50/월 | 초기 SQLite 가능, 구독화 후 Postgres 권장 |
| Queue/cache | $0 | $0-20/월 | scheduler로 시작, scale 후 Redis/queue |
| Monitoring/logs | $0 | $0-30/월 | 장애 알림 필수 |
| 결제/메일/알림 | 매출의 3-5% | 매출의 3-5% | PG/카드 수수료 |
| 합계 | $0-50/월 | $70-200/월 | 금융 데이터 비용 제외 |

운영 판단:

- MVP/베타: MiniPC + Cloudflare Tunnel + read-only MCP로 충분하다.
- 유료 구독: 최소한 API key, quota, audit log, backup, 장애 알림은 필요하다.
- 50명 이상 유료화: managed DB와 별도 MCP sidecar host를 권장한다.

### 2.2 AI 호출 변동비

MCP endpoint 자체의 `tools/list`, `resources/read`, JSON artifact 조회는 원가가 거의 없다. 비용은 tool이 LLM 분석을 새로 실행할 때 발생한다.

공식 OpenAI API 가격표 기준으로 GPT-5.4 mini는 입력 $0.75/1M tokens, 출력 $4.50/1M tokens 수준이다. 고급 모델을 쓰면 같은 작업의 원가가 몇 배 오른다.

| 작업 | 토큰 가정 | GPT-5.4 mini 원가 추정 | 비고 |
|---|---:|---:|---|
| 캐시 요약 재해석 | input 5k, output 1k | 약 $0.008 | 거의 무료에 가까움 |
| 단일 후보 live explain | input 25k, output 4k | 약 $0.037 | Pro+MCP에 적합 |
| 후보 검증 + risk breakdown | input 50k, output 8k | 약 $0.074 | quota 필요 |
| multi-agent debate 1회 | input 150k, output 30k | 약 $0.25 | Ultra 이상 권장 |
| 고급 모델 debate | 같은 토큰 | 약 $0.8-$1.7 | 무제한 제공 금지 |

월 원가 예시:

| 사용자 패턴 | 월 AI 원가 | 원화 단순 환산 | 적정 상품 |
|---|---:|---:|---|
| read-only MCP 중심 | $0-1 | 0-1,400원 | Pro+MCP |
| 월 30회 단일 후보 분석 | $1-3 | 1,400-4,200원 | Pro+MCP |
| 월 100회 후보 분석 + 10회 debate | $6-10 | 8,400-14,000원 | Ultra |
| 매일 heavy debate/vision/backtest | $20-60+ | 28,000-84,000원+ | Advisor/Team 또는 종량제 |

주의: 원화 환산은 내부 가격 감 잡기용으로 `1 USD = 1,400 KRW`를 쓴 단순 계산이다. 실제 결제 전에는 환율과 모델 가격을 다시 갱신해야 한다.

## 3. 적정 구독가 산정

### 3.1 시장 가격 앵커

| 서비스 | 공식 가격대 | 시사점 |
|---|---:|---|
| TradingView | Essential/Plus/Premium/Ultimate가 대략 월 $13-$200대 | 차트/알림/기술분석 도구는 월 수만-수십만원 가격을 받을 수 있음 |
| Koyfin | Plus $39, Premium $79, Advisor/Enterprise $200대 이상 | 리서치/데이터 단말형 서비스는 $39-$79가 개인 유료층 기준 |
| Seeking Alpha Premium | 연 $299 내외 | 투자 리서치 구독은 월 $20-$30대가 대중 가격 |
| TrendSpider | 자동화 차트/트레이딩 도구가 월 $60대 이상 | 자동화/전략 도구는 일반 리서치보다 높은 가격 가능 |

MarketFlow/MiroFish는 단순 데이터 단말보다 “AI 분석 + 자동화 + MCP 연동”이 차별점이다. 따라서 대중 Pro는 29,000원, MCP 자동화는 59,000원 이상, heavy automation은 129,000원 이상이 자연스럽다.

### 3.2 권장 상품 구성

| Tier | 가격 | 월 quota | 원가 통제 장치 |
|---|---:|---|---|
| Free | 0원 | 캐시 조회만, live 분석 없음 | 지연 데이터, 공개 후보만 |
| Pro | 29,000원 | live 분석 20회, export 제한 | MCP 없음, debate 없음 |
| Pro+MCP | 59,000원 | MCP read 3,000 calls, live 분석 50회, schedule 5개 | heavy tool 잠금, overage 과금 |
| Ultra+Automation | 129,000원 | MCP read 20,000 calls, live 분석 250회, debate 30회, webhook | 모델 downgrade/cascade, batch/caching |
| Advisor/Team | 299,000원+ | 계약별 | 별도 SLA, seat 과금 |

Overage 권장:

- live explain 추가 10회: 5,000원
- heavy debate 추가 10회: 15,000-25,000원
- chart vision/backtest heavy job: 건당 1,000-5,000원 또는 credit 차감
- webhook/API 초과: 10,000 calls당 5,000원

핵심은 “무제한”이라는 표현을 피하는 것이다. AI/자동화 상품은 반드시 credit, fair-use, rate limit이 있어야 한다.

### 3.3 손익 예시

| 시나리오 | 월 매출 | 월 변동비/고정비 추정 | 마진 감 |
|---|---:|---:|---|
| Pro+MCP 20명 | 1,180,000원 | 150,000-300,000원 | 초기에도 가능 |
| Pro+MCP 50명 | 2,950,000원 | 350,000-700,000원 | 안정적 |
| Pro+MCP 50명 + Ultra 20명 | 5,530,000원 | 800,000-1,500,000원 | 운영 여력 충분 |
| Heavy user 비중 50% 이상 | 매출은 증가 | AI/지원비 급증 | quota/overage 없으면 위험 |

## 4. 자동화 MCP 구현 가능성

결론: **가능하다. 단, MCP 자체가 scheduler가 아니라 “외부 AI client가 MarketFlow 기능을 호출하는 표준 인터페이스”라는 점을 분명히 해야 한다.** 실제 자동 실행은 MarketFlow backend/scheduler/job queue가 맡고, MCP는 job 생성/조회/결과 resource 연결을 제공하는 방식이 맞다.

### 4.1 가능한 구현 옵션

| 옵션 | 구조 | 장점 | 단점 | 권장 |
|---|---|---|---|---|
| A. Local stdio MCP package | 사용자 PC의 Claude/Cursor가 로컬 MCP 서버 실행, 서버가 MarketFlow API 호출 | 운영비 낮음, 사용자별 API key만 필요 | 설치/업데이트 UX 부담 | MVP 보조 |
| B. Remote Streamable HTTP MCP | `https://mcp.bit-man.net/mcp`를 우리가 운영 | 구독 관리, quota, revoke, audit 쉬움 | 인증/인프라 비용 필요 | 유료 서비스 주력 |
| C. Hybrid proxy | 로컬 MCP package가 remote MCP/API로 proxy | 클라이언트 호환성 높음 | local+remote 둘 다 관리 | 현실적 초기 전략 |

권장 순서:

1. 내부용 Python `FastMCP` sidecar read-only 구현
2. API key + quota + audit log 추가
3. local stdio proxy package 또는 remote HTTP endpoint 공개
4. 스케줄/웹훅/자동 run 생성 tool 추가

### 4.2 실제 endpoint 설계

Resources:

| URI | 용도 |
|---|---|
| `mirofish://runs/latest` | 최신 run 요약 |
| `mirofish://runs/{run_id}/summary` | run metadata, fallback, source freshness |
| `mirofish://runs/{run_id}/candidates` | 후보 목록과 score breakdown |
| `mirofish://runs/{run_id}/evidence/{symbol}` | 특정 종목 evidence bundle |
| `mirofish://runs/{run_id}/artifacts/{name}` | 원본 JSON artifact |

Tools:

| tool | 가능 여부 | 비고 |
|---|---|---|
| `list_mirofish_runs` | 즉시 가능 | 파일/DB 조회 |
| `get_mirofish_candidate` | 즉시 가능 | exact symbol/name/market 필수 |
| `rank_mirofish_candidates` | 즉시 가능 | deterministic 계산 |
| `validate_mirofish_candidate` | 가능 | 기존 검증 서비스 wrapping |
| `explain_mirofish_candidate` | 가능하지만 비용 발생 | quota 필요 |
| `create_mirofish_run` | 가능하지만 2단계 권장 | dry_run, rate limit, audit 필수 |
| `create_mirofish_schedule` | 가능 | MCP가 아니라 backend scheduler에 등록 |
| `send_webhook_test` | 가능 | Ultra 이상 |

### 4.3 구현 난이도

| 단계 | 예상 기간 | 구현 내용 | 리스크 |
|---|---:|---|---|
| 내부 read-only MCP | 1-2일 | FastMCP server, resources/tools, Inspector smoke | artifact 파일명 확인 |
| 구독 API key | 2-3일 | key hash, scope, quota, revoke, audit log | 기존 auth와 충돌 방지 |
| Remote HTTP 운영 | 1-2일 | sidecar systemd/service, tunnel/routing, healthcheck | ASGI/Flask 경계 |
| 자동 스케줄 | 3-5일 | schedule table, worker/scheduler integration, delivery | 중복 실행/장애 복구 |
| 결제/상품화 | 5-10일 | billing status, downgrade, quota reset, invoice handling | PG webhook 안정성 |
| 외부 공개/문서화 | 2-4일 | onboarding, Claude/Cursor config, examples | 클라이언트별 MCP 지원 차이 |

실제 구현은 기술적으로 막히는 부분이 없다. 다만 “자동화”를 MCP process 내부에서 오래 붙잡고 실행하면 안 된다. 긴 작업은 job id를 반환하고, 결과는 resource로 조회하게 해야 한다.

## 5. 운영 리스크와 통제

| 리스크 | 영향 | 통제 |
|---|---|---|
| AI 비용 폭증 | 마진 손실 | credit, daily cap, model cascade, cache-first |
| heavy user 집중 | 서버 지연 | queue, concurrency limit, per-user rate limit |
| OAuth/API key 유출 | 데이터 노출 | key hash 저장, revoke, scope, IP/device alert |
| 금융 조언 오해 | 법적/평판 리스크 | 투자자문 아님 고지, 근거/리스크/확률 표현 |
| 데이터 재배포 라이선스 | 상용화 중단 가능 | 원천 데이터 약관 확인, raw data export 제한 |
| MCP prompt injection | 임의 tool 호출/정보 유출 | read-only default, mutation confirmation, tool allowlist |
| 홈서버 장애 | 유료 사용자 불만 | paid tier부터 VPS/managed DB 또는 standby 필요 |

## 6. 출시 권장안

1. **베타 2주**: 내부/초대 사용자만 `Pro+MCP` 기능 제공. 가격은 39,000원 또는 무료 체험, quota는 낮게 둔다.
2. **정식 출시**: `Pro 29,000원`, `Pro+MCP 59,000원`, `Ultra+Automation 129,000원`.
3. **무제한 금지**: 모든 AI 실행, schedule, webhook, export는 quota/credit으로 관리한다.
4. **read-only MCP 먼저**: 유료화 전까지 `create_run`, `schedule`, `webhook` 같은 mutation tool은 admin/베타 전용으로 둔다.
5. **원가 기준 KPI**: 사용자당 AI 원가가 매출의 15%를 넘으면 모델 downgrade, cache, quota 조정을 자동 검토한다.

## 7. 참고 링크

- MCP official specification: https://modelcontextprotocol.io/specification/latest
- MCP transports: https://modelcontextprotocol.io/specification/2025-11-25/basic/transports
- MCP authorization: https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
- MCP security best practices: https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
- Python SDK: https://github.com/modelcontextprotocol/python-sdk
- TypeScript SDK: https://github.com/modelcontextprotocol/typescript-sdk
- MCP Inspector: https://modelcontextprotocol.io/docs/tools/inspector
- Cloudflare Workers pricing: https://developers.cloudflare.com/workers/platform/pricing/
- OpenAI API pricing: https://openai.com/api/pricing
- Stripe pricing: https://stripe.com/pricing
- TradingView pricing: https://www.tradingview.com/pricing/
- Koyfin pricing: https://www.koyfin.com/pricing/
- Seeking Alpha Premium pricing note: https://about.seekingalpha.com/premium-subscription-price-update
- TrendSpider pricing: https://trendspider.com/pricing/
