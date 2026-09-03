# MarketFlow 전체 리뷰 & 개선 우선순위 로드맵 — 2026-09-02

> 목적: 구독 서비스로서 MarketFlow 를 "분석력·검색력이 증명되는 앱"으로 바꾸기 위해,
> 코드 전체(Python 약 154k LOC, React 약 49k LOC, Flask 라우트 353개, 프론트 페이지 40+)를
> 6개 축으로 리뷰하고 **근거(file:line) 있는 개선안**을 영향/노력 기준으로 정렬한 문서.
> Phase 0 항목은 이 문서와 같은 PR 에 구현·테스트 포함.

---

## 0. 한 페이지 요약

### 진단
| 축 | 현재 상태 | 한 줄 결론 |
|---|---|---|
| 분석력 | 5개 독립 채점기(종가베팅 20점 / 주도주 100점 / VCP 100점 / Wave / Alpha 100점), 가중치 전부 수기 상수, 결과 피드백은 ranking_delta 에만 ±2 | **채점 체계는 많은데 "맞았는지"가 점수로 돌아오지 않는다** |
| 검색력 | 초성·별칭·퍼지 리졸버가 있는데 CommandPalette 는 substring 만 사용, 뉴스 파이프라인 3개가 서로 dedup 공유 안 함, 관심종목/알림 0 | **좋은 부품이 연결돼 있지 않다** |
| 회원/구독 | 수동 계좌이체 + 관리자 수동 승인, 만료 알림은 관리자에게만, Stripe 코드는 dead, 무료 티저 0, 퍼널 이벤트 0 | **성장 병목 = 운영자의 손** |
| 앱 관리 | 스케줄러 4,588줄 단일 파일, status API 가 실제 데몬을 안 봄, .env.example 7개 vs 코드 참조 256개, 63MB exe 커밋 | **재구축 불가능한 저장소** |
| API 효율/경제성 | 인증 GET 전부 no-store(캐시 분기 dead), gzip/ETag 0, 5초 폴링, LLM 토큰/비용 집계 0, TradingAgents 종목당 12~13회 호출 | **대역폭·LLM 지출 모두 계측 없이 새고 있다** |
| 디자인/UX | 8개 브랜드(Claw/주도주LIVE/종가베팅/Wave/AI Brain/Goodrich/ProPicks/MiroFish), 네비 5벌, 종목 허브 페이지 없음, 성과 증명은 유료벽 뒤 | **"오늘 뭘 사야 하는지"가 첫 화면에 없다** |

### 최우선 10개 (영향 ÷ 노력)
| # | 개선 | 축 | 영향 | 노력 | 상태 |
|---|---|---|---|---|---|
| 1 | 검색 도구 없는 브리핑 경로에서 "Google Search 뉴스" 요구 제거 (환각 표면 제거) | 분석 | ★★★★★ | ★ | **Phase 0 완료** |
| 2 | 인증 GET 캐시 dead-branch 수정 + ETag/304 + gzip | 효율 | ★★★★ | ★ | **Phase 0 완료** |
| 3 | 사용자 대상 승인/만료 알림 (현재 관리자에게만) | 구독 | ★★★★★ | ★★ | Phase 1 |
| 4 | 공개 Track Record 페이지 (유료벽 밖 성과 증명) | 구독/UX | ★★★★★ | ★★ | Phase 1 |
| 5 | 종목 허브 `/dashboard/stock/:market/:code` (decision_brief 11소스 재사용) | 검색/UX | ★★★★★ | ★★★ | Phase 1 |
| 6 | 초성/별칭/퍼지 검색을 CommandPalette 에 연결 | 검색 | ★★★★ | ★ | **Phase 0 완료** |
| 7 | 신호별 feature snapshot 저장 → 가중치 캘리브레이션 전제 | 분석 | ★★★★★ | ★★ | Phase 1 |
| 8 | LLM 토큰/비용 계측 + 응답 캐시 + 프롬프트 캐싱 | 경제성 | ★★★★ | ★★ | **계측 Phase 0 완료**, 캐시 Phase 1 |
| 9 | "오늘" 홈: 상단 3카드(오늘의 픽 / 시장 게이트 / 어제와 달라진 것) | UX | ★★★★ | ★★★ | Phase 2 |
| 10 | 스케줄러 잡 상태 보드 + 재실행 버튼 (status 는 Phase 0 에서 데몬 연결) | 운영 | ★★★★ | ★★ | **status Phase 0 완료**, UI Phase 1 |

---

## 1. 리뷰 범위와 방법

- 저장소: `point10890-crypto/marketflow-react` @ `9f08a81` (2026-09-02)
- 6개 영역별 코드 탐색(전수 grep + 핵심 파일 정독) → 각 항목에 `file:line` 근거 → 영향/노력 채점 → 통합 랭킹
- 기준 검증: Python 전체 스위트, 프론트 vitest 221개 / lint / build 모두 green 에서 시작
- 이전 리뷰(`docs/full_code_endpoint_review_2026_07_15.md`, PR #2 P0 보안)와 중복되는 항목은 제외하고 **아직 남은 것**만 다룬다

---

## 2. 현재 앱 진단

### 강점 (유지·강화)
- **데이터 정직성 문화**: `kis_screener.py:812-833` 는 거래량 분모를 지어내지 않고, `briefing_generator._fallback_morning` 은 `confidence:0.3` + "AI 분석 불가" 를 명시. 이전 리뷰에서 허위 백테스트(+5%/-3%)도 제거됨.
- **Omni 뉴스 원장** (`app/services/omni/*`): sha256 dedup, 출처 등급(S/A/B/C), corroboration 카운트, append-safe 병합 — 국내 개인 서비스 수준을 넘는 설계.
- **Lookahead-safe 아웃컴 추적**: `scripts/backtest_alpha_signals.py:182-188` 성숙 컷오프, `edge_map.py:36`, `hypothesis_replay.py` IC-gain 게이트.
- **운영 방어선**: heartbeat 전용 스레드(`scheduler.py:3120-3136`), 원자적 run-record, KIS rate-limit 백오프(`kis_screener.py:270-307`), 관리자 감사로그 + 원자적 승인(`admin.py:1178-1199`).
- **decision_brief**: 11개 신호 소스 + 뉴스 + 레짐 + 무효화 조건을 이미 한 곳에서 합성 (`decision_brief.py:315-642, 799`). 종목 허브의 백엔드는 사실상 완성돼 있다.

### 구조적 약점 (이 로드맵의 표적)
1. **좋은 부품이 연결돼 있지 않다** — 리졸버↔검색, decision_brief↔종목 페이지, Stripe↔결제 UI, outcome_tracker↔점수, number_guard↔구독자 텍스트, /api/scheduler/status↔실제 데몬.
2. **계측 부재** — LLM 비용, 퍼널 전환, 잡 성공률, 응답 크기. 개선했는지 알 방법이 없다.
3. **브랜드/채점기/네비/문서의 다중화** — 같은 것을 5벌씩 유지하며 운영자 시간을 소모.
4. **성장 경로가 수동** — 입금 확인·승인·갱신·문의 전부 사람.

---

## 3. 영역별 발견사항

### 3.1 분석 파이프라인 / 분석력 강화

**파이프라인 지도**
```
pykrx/FDR/Naver(collectors.py) · KIS(kis_screener.py) · OpenDART · yfinance · Kiwoom · TradingView MCP
   → 5개 채점기 (jongga 20 / leading 100 / VCP 100 / wave / alpha 100)
   → alpha_scanner._score_symbol 만이 유일한 집계자 (screener/100*20, vcp/100*13+2, jongga/15*10)
   → ranking = alpha − 0.55·risk + conviction + mcp_delta        (alpha_scanner.py:1882)
   → LLM 층: llm_analyzer(뉴스 0~3) · briefing_generator · leading_enricher · deepseek rerank · TradingAgents
   → JSON 아티팩트 → React (KrClosingBetPage / KrLeadingStocksPage / KrVcpPage / BriefingPortal / aibain/*) + Telegram
```

**결함 (근거)**
| 결함 | 근거 | 왜 구독자에게 보이나 |
|---|---|---|
| 브리핑이 검색 도구 없는 모델(DeepSeek/OpenAI)에게 "Google Search 로 찾은 뉴스 3-5개" 를 요구 | `briefing_generator.py:227,306,573-577` | 매일 아침 구독자가 읽는 뉴스 섹션이 창작될 수 있음 → **Phase 0 수정** |
| `number_guard` 가 구독자 텍스트에 미연결 (TradingAgents 만, 그것도 shadow) | `tradingagents/analysts.py:113-122` | 브리핑·주도주 AI 사유·차트 비전 수치가 무검증 |
| LLM 브레이커가 프로세스 수명 동안 영구 비활성 | `engine/llm_analyzer.py:26-44` | 429 한 번 → 이후 전부 키워드 폴백, 화면엔 표시 없음 → **Phase 0 수정** |
| 종가베팅 점수 /15 스케일 (이론 최대 20점) | `alpha_scanner.py:1763` vs `engine/models.py:132` | 15점 이상 셋업이 전부 10점으로 포화. /20 으로 바꾸면 총점 13 셋업이 actionable 임계 미달(기존 테스트 고정) → **상수화·문서화만 Phase 0**, 스케일·임계 재조정은 §8 운영자 결정 |
| `_time_weight()` 가 주도주 100점을 시각(09:15/14:30)에 따라 0.8~1.2배 | `kis_screener.py:949-956, 1724` | 같은 종목 점수가 데이터 변화 없이 흔들림, 순위 이력 비교 불가 |
| `SignalConfig.score_weights` 는 dead, `financial` 항목 누락 | `engine/config.py:51` vs `scorer.py:104` | 문서와 실제 채점 불일치 |
| VCP "상대강도" 가 절대 3개월 수익률 5단계 버킷 | `vcp_enhanced_scanner.py:175-203` | RS 로 표기되지만 RS 가 아님 (진짜 RS 는 `sector_rs.py:34-40`) |
| 아웃컴 피드백이 `ranking_delta` 에만 ±2.0, `alpha_score` 는 불변 | `alpha_scanner.py:1871-1882`, `outcome_tracker.py:225` | 학습이 화면 순위 한 칸에만 영향 |
| 종가베팅/주도주는 원천 피처(뉴스 본문·투자자 행)를 저장하지 않아 재현/백테스트 불가 | `collectors.py:409-464`, `kis_screener.py:772` | 가중치 조정의 효과를 검증할 수 없음 |
| 상장폐지/거래정지 종목이 `skipped` 로 조용히 제외 | `backtest_alpha_signals.py:64, 267` | 적중률 과대 |
| 거래비용(0.23%)이 백테스트·아웃컴 집계에 미적용 | `costs.py:13` vs `backtest_alpha_signals.py:286-302` | 5일 호라이즌에서 기대수익 과대 |
| 703× `except Exception`, 32× bare except, `_run_orphan_file_audit` 중복 정의 | `scheduler.py:3488,3525` | 조용한 실패 |

**개선안 (영향/노력 순)**
1. ✅ 브리핑 프롬프트를 provider 능력에 맞게 분기 (`search_capable` 인자).
2. ✅ 브레이커 쿨다운(15분→2배씩→최대 2h, half-open).
3. ✅ jongga 포화점 상수화(`JONGGA_SCORE_SATURATION=15`, `JONGGA_SCORE_THEORETICAL_MAX=20`) — 동작 변경 없음.
4. **feature snapshot 저장** — `outcome_tracker._feature_snapshot`(`:416`) 패턴을 `jongga_v2_results_*.json`, `screener_leading_*` 에 미러. 컴포넌트 점수·뉴스 ID·투자자 행을 신호 시점에 기록. (모든 캘리브레이션의 전제, 실행당 write 1회)
5. **number_guard enforce** — `analysts.py:113-118` shadow→enforce, `briefing_generator._save` 와 `leading_enricher` 에 `guard_output` 연결, contradicted≥1 이면 결정론 템플릿으로 폴백.
6. **`_time_weight` 를 곱셈에서 표시 필드(`time_context`)로** — 점수 의미를 시각 불변으로.
7. **비용 반영 아웃컴** — `costs.net_return_pct` 를 `backtest_alpha_signals._metrics` 와 `outcome_tracker.evaluate_result_outcome` 에 적용, gross/net 병기.
8. **skipped 사유 버킷** — 사라진 종목을 별도 카테고리로 보고.
9. **VCP RS 교체** — `sector_rs.compute_weighted_return` 백분위 사용, benchmark None 시 절대수익 분기 삭제.
10. **아웃컴 → 컴포넌트** — `hypothesis_replay.replay_tag_delta` 를 태그를 만든 컴포넌트에 라우팅, PerformanceCard 에 컴포넌트별 실현 적중률 노출 (구독자가 "자신감"이 아니라 "캘리브레이션"을 봄).
11. **채점기 통합 설계** — 5개 채점기의 공통 피처(거래대금·거래량·52주고가)가 2~3중 계산됨(`_score_trading_value` vs alpha `liquidity`). 장기적으로 "피처 레이어 1개 + 전략별 가중치" 구조로.

### 3.2 검색력 강화

**현황 인벤토리**
| 엔드포인트 | 매칭 | 문제 |
|---|---|---|
| `GET /api/stock-analyzer/search` (`stock_analyzer.py:649-703`) | lowercase substring, CSV 순서, 20건 컷 | CommandPalette·StockAnalyzerPage 가 쓰는 **유일한** 사용자 검색인데 초성/오타/별칭 불가 → **Phase 0 에서 리졸버 병합** |
| `GET /api/kr/decision/search` → `decision_brief.search_symbols` | ticker→GraphRAG 리졸버(초성 0.85/접두 0.8/퍼지 0.5~0.8)→CSV | 가장 좋은 검색이지만 팔레트에 미노출 |
| `live_data.search_target_candidates` (admin) | 세 번째 독립 랭킹 | 관리자 전용 |
| manual-stock-analysis `/search-index`, `/history` | 클라이언트 substring / 매 조회마다 전체 run JSON 스캔 (`:2183-2188`) | O(runs×records) |
| `GET /api/community/search` (`community.py:1005-1050`) | `ILIKE %q%` 풀스캔, created_at 정렬 | 관련도 없음 |

**검증된 공백**: 전문/벡터 인덱스 0 (`fts5|faiss|chromadb|pgvector` 검색 결과 없음), 관심종목/저장검색/사용자 알림 0 (`watchlist|관심종목|favorite` 0건), 통합검색 없음, 종목 360 페이지 없음, US 유니버스 50개 하드코딩, `data/admin_mirofish/graphrag/entities.db` 미생성 시 리졸버가 빈 결과.

**분석측 리트리벌**: 뉴스 경로 3개(Omni RSS 원장 / `EnhancedNewsCollector` Naver 스크랩 무캐시·제목정규화 dedup / Google News RSS 5건)가 dedup 네임스페이스를 공유하지 않음. DART 는 `report_nm` 제목 키워드만 분류(`dart_collector.py:304`), 본문 미파싱.

**개선안**
1. ✅ 팔레트 검색에 리졸버 병합 + 요청 취소(AbortController).
2. **`resolver.populate_from_sources()` 를 스케줄러 부팅 태스크로** (`resolver.py:163-260`) — 운영에서 초성/퍼지 코드가 살아나는 전제.
3. **종목 허브 페이지** — `build_decision_brief` 를 Pro 라우트로 렌더, 모든 리스트 행(종가베팅/주도주/VCP/Claw)에서 딥링크. 가장 적은 신규 코드로 가장 큰 체감.
4. **관심종목 + 알림** — `watchlists` 테이블 + `/api/kr/watchlist`; decision-cache 키(`kr_market.py:1875-1884`)와 `service_guard.py:330-372` 의 전이/쿨다운 로직 재사용해 상태 전이를 텔레그램으로.
5. **SQLite FTS5 통합 인덱스** — `omni.db` 에 `news_fts`, community `Post` 에 FTS5, `/api/search?q=` 가 종목/뉴스/커뮤니티/분석이력을 fan-out.
6. **EnhancedNewsCollector → omni.ledger** 로 합류 (`funnel.content_hash` + `save_events`) — 파이프라인 간 재사용, 재스크랩 제거.
7. **근사중복 dedup + 시간감쇠** — 제목 정규화 대신 shingle/SimHash, `funnel.importance_score` 에 recency 항.
8. **DART 구조 파싱** — 계약금액/지분율/증자규모 필드 추출 → `document_ingestor.chunk_text` 로 그래프에 투입.

### 3.3 회원 관리 워크플로우 / 구독력

**현재 여정**: `/signup` → `/plan-select` → `/payment-request`(계좌이체, 입금자명) → 관리자 텔레그램 → `/admin` 승인 → 30일. 만료는 시간당 스윕(`app/__init__.py:526-562`) 이 **관리자에게만** D-3/D-1 알림. Stripe 라우트(`stripe_routes.py`)는 등록돼 있으나 호출처 0.

**보안/정합성**: bcrypt OK, HMAC 토큰(32hex 절단, 30일, 서버측 폐기 없음, `/logout` 없음), 토큰 localStorage, 인메모리 rate-limit(재시작 시 소실), 이메일 인증/비밀번호 찾기 없음, 게이트가 denylist(`_GATED_PREFIXES`, `app/__init__.py:263-271`) — 새 블루프린트는 기본 무보호, `ai-chart-image` 예외.

**전환 공백(검증)**: 무료 티어·체험·티저 0, `FunnelGate` 가 가입한 미구독자를 `/`, `/pricing`, `/community` 에서 쫓아냄(`App.tsx:120-124`), 승인 통보가 사용자에게 안 감(30초 폴링으로 발견), 연/분기 플랜 없음(50k→1.2M 사이 공백), 쿠폰/추천 0, 퍼널 이벤트 계측 0.

**리텐션 공백**: 사용자별 텔레그램/이메일 0 (`User` 에 `telegram_chat_id` 없음, "텔레그램 알림"을 Pro 기능으로 판매 중 `billingInfo.ts:52`), 온보딩 0, 구독자 ROI 페이지 없음, 이탈 예측 신호 `last_login_at` 뿐.

**개선안**
1. **사용자 대상 알림** — `User.telegram_chat_id`(+이메일) 추가, `admin.py:1288-1290` 승인 시와 `pro_expiry.py:63` 스윕에서 본인에게 전송. `aibain_notify.py:47-79` 재사용. 30일 침묵 이탈 → 3터치 dunning.
2. **입금 자동 매칭** — `payment_events` 테이블 + (오픈뱅킹 API 또는 관리자 CSV 붙여넣기) → `depositor_name`+`amount` 유일 매칭 시 기존 approve 경로 자동 호출.
3. **읽기전용 티저 티어** — `FunnelGate` 완화 + `_GATED_PREFIXES` 에 teaser 모드(T-1 신호, top 1/5 블러).
4. **공개 Track Record** — `TrackRecordPage` 를 `/track-record` 로 승격, 지연·마스킹 버전 API.
5. **퍼널 이벤트** — signup/plan-select/payment-request/approve 4지점 → `funnel_events` + 관리자 차트.
6. **Stripe 자동갱신 연결** — 웹훅(`stripe_routes.py:47-131`)은 이미 tier/만료를 세팅. 카드 결제 버튼 + `STRIPE_PRICE_ID` 만 부족.
7. **비밀번호 찾기 + 이메일 인증** — `set_password` 가 세션 회전 처리(`user.py:66-71`).
8. **연간/분기 SKU** — `billingInfo.ts:36`, `admin.py:1268-1272` 의 `timedelta(days=30)` 매핑화.
9. **온보딩 체크리스트** — `approved_at` 기준 3~5단계 카드.
10. **게이트 allowlist 화 + 공유 rate-limit 저장소**.

### 3.4 앱 관리 워크플로우 (운영)

**운영 지도**: miniPC(Windows, Task Scheduler) 에 Flask :5003(터널) + Flask :5001(producer) + `scheduler.py` 데몬(~30잡) + cloudflared. 워치독은 5분마다 `git pull` + heartbeat(180s) + 파일 해시 재시작. 실패는 텔레그램 ~60곳 직접 호출(집계·dedup 없음). Flask 로그 회전 없음(`run_flask.bat:23`).

**위생 (측정)**: `cloudflared.exe` 63MB 추적, `data/` 하위 699파일(~40MB, 사용자 업로드 이미지 포함, `data(minipc): sync` 커밋으로 런타임 상태가 main 에 역류), `backend/` Spring 38파일 + Spring 용 `Dockerfile` + 미사용 `docker-compose.yml`(하드코딩 비밀번호), `crypto-analytics/` 7.8MB 중복 스택, `docs/` 80개 + `superpowers/` 51개, `requirements.txt` 전부 `>=`/무제약, `scheduler.py` 4,588줄.

**CI/테스트**: 전체 스위트만 실행, `slow`/`integration` 마커 선언만 되고 0회 사용, 19개 테스트 파일이 네트워크 의존, job timeout 없음, `npm run lint` CI 미실행 → **Phase 0 에서 timeout + lint 추가**.

**운영 레버 부재**: `/api/scheduler/status` 가 Flask 내부 `schedule` 레지스트리만 봄(`app/utils/scheduler.py:926-945`) → **Phase 0 에서 데몬 heartbeat + last_run 연결**; 트리거 5개/30잡; 비용 대시보드 0; 부팅 시 설정 검증 0; `.env.example` 7개 vs 코드 256개 → **Phase 0 에서 인벤토리 생성**.

**개선안**
1. ✅ status 에 `daemon.alive/stale_seconds/last_runs[]`.
2. ✅ `.env.example` 인벤토리(249개) + `scripts/gen_env_inventory.py`.
3. ✅ CI timeout + lint.
4. **잡 상태 보드 탭** — `pages/admin/tabs/` 에 status.daemon 소비, 잡별 red/green + 경과.
5. **트리거 30잡 확장** — `data/scheduler_trigger_request.json` 을 데몬이 폴링(heartbeat 파일 패턴 미러).
6. **의존성 핀** — `pip-compile requirements.in`, pytest 류는 `requirements-dev.txt` 로.
7. **부팅 설정 검증** — `config.py` 에 `REQUIRED=[...]` 검사, 누락 시 이름과 함께 실패.
8. **백업 태스크 검증/모니터** — `install_durable_backup_task.ps1` 이 실제 등록됐는지, `data/backup_last_run.json` 을 보드에.
9. **저장소 정리(운영자 결정 필요)** — `cloudflared.exe`·`data/**` untrack, `backend/`·`Dockerfile`·`docker-compose.yml`·`screener_test/` 삭제, docs 아카이브. ⚠ 워치독이 miniPC 에서 `git pull` 하므로 `git rm --cached cloudflared.exe` 는 **워킹트리에서 exe 를 지운다** → 먼저 exe 를 저장소 밖 경로로 옮기고 `start_cloudflared.vbs` 를 수정한 뒤 진행.
10. **Flask 로그 회전** — `scheduler.py:502-516` 의 RotatingFileHandler 복제.

### 3.5 API 효율성 · 경제성

**낭비 (근거)**
| 낭비 | 근거 | 조치 |
|---|---|---|
| 인증 응답 전부 no-store → `private,max-age=30` 분기 dead | `app/__init__.py:222-244` | ✅ Phase 0 |
| gzip/br 0, ETag/304 0 | requirements·`__init__.py`·routes grep 0건 | ✅ Phase 0 (flask-compress 옵셔널 + weak ETag) |
| `/api/kr/screener/leading` 5초 폴링, `/api/kr/claw/overview` 5초 | `KrLeadingStocksPage.tsx:327`, `ClawLiveCard.tsx:37` | 304 로 본문 0 → 다음: SSE 또는 통합 `/overview` |
| 관리자 1s/1.2s 폴링 | `AdminEndpointsPage.tsx:2270,2359` | 5s 로 |
| `json.load` 61곳 vs `load_json_cached` 21곳 | `us_market.py` 38곳 | 기계적 치환 |
| `/realtime-prices` 가 매 요청 106KB CSV pandas 파싱 + 1분봉 다운로드 | `kr_market.py:1240,1259` | 모듈 캐시 + 30s TTL |
| `us_market.py:466` picks 집계 O(dates×picks×rows) | | 스케줄러가 `picks_summary.json` 사전계산 |
| `get_sector()` 캐시 미스마다 yfinance + 캐시 전체 rewrite | `cache.py:120,130` | 요청 경로 밖으로 |
| Werkzeug dev 서버 단일 프로세스, gunicorn 미사용 | `flask_app.py:77` | Windows 에선 waitress 권장 |
| react-query 1/177 파일만 사용, 나머지 setInterval | `main.tsx:15` | 훅 통합 |

**LLM 경제성**: 모델 11종 혼재(`gpt-5.5` 18곳, `gemini-2.5-flash` 22곳 …), 라우팅 DeepSeek→OpenAI→Gemini 는 건전. 그러나 **토큰/비용 집계 0** (`llm_client.py:394-401` 에 usage 없음, `auto_runner.py:120` 은 고정 $0.07) → ✅ Phase 0 에서 `usage`+`est_cost_usd` 를 메타데이터에 추가(`llm_pricing.py`). JSON 파싱 실패 시 같은 프롬프트를 더 비싼 provider 로 재지불(`llm_client.py:378-386`), 재시도/백오프 0, 프롬프트 캐싱 0. TradingAgents 종목당 12~13회 호출에 동일 bundle 을 매번 재전송(`analysts.py:319`).

**개선안**: ① ✅ gzip ② ✅ ETag ③ ✅ 캐시 분기 ④ `load_json_cached` 전면 ⑤ picks 사전계산 ⑥ **LLM 응답 캐시**(sha256(provider|model|system|prompt|temp) → SQLite, 단계별 TTL) ⑦ ✅ 비용 계측 → 예산 가드를 실측 기반으로 ⑧ TradingAgents bundle 프롬프트 캐싱 ⑨ invalid_json 시 로컬 repair/동일 provider 1회 재시도 후 폴백 ⑩ 폴링 통합/완화 + waitress.

### 3.6 앱 디자인 / UX

**IA**: 8개 브랜드가 한 사이드바에(`Sidebar.tsx:30-89`), 네비 정의 5벌(Sidebar/BottomTabBar/MobileDashboardRail/MobileSubNav/Header PAGE_NAMES) 라벨 불일치, `kr/claw` 는 모바일 네비에 없음, 종목 상세 라우트 없음(`StockDetailModal` 은 US 만), Track Record 는 3단계 깊이 + 유료벽.

**시각/상태**: 공유 프리미티브 3개뿐(`components/ui/`), `StatCard` 6벌·`ScoreBar` 6벌·`Metric` 5벌, `.claw-theme` 가 `[class*="bg-[#13151f]"]` 속성 정규식으로 임의 카드 재도색(`index.css:834-858`), 다크 전용, 스켈레톤/빈 상태/에러 페이지별 임의, 16개 테이블이 `min-w-[640px]` 가로 스크롤, aria-label 43/108.

**공개 페이지**: 랜딩 콘솔이 `화면 예시 · 실제 종목 아님`(`LandingPage.tsx:240-275`), 적중률/샘플 신호/사용자 수 0, 가격 충격(₩50k/₩90k/₩1.2M) + 계좌이체, CTA "무료 계정 만들기" 와 "승인 후 이용" 이 한 버튼에서 충돌.

**죽은/중복**: `KrChatbotPage` 11줄 스텁인데 Pro 기능으로 판매(`billingInfo.ts:48`), VCP 화면 4벌, 주식분석 도구 2개가 사이드바에 "AI 주식분석" 으로 두 번, `MobileTopPicksHero.tsx`·`AuthImage.tsx` 미참조.

**개선안**
1. **"오늘" 홈** — `DashboardClient.tsx`(1,353줄) 상단을 3카드로: 오늘의 픽(이름·등급·진입/손절 근거) / 시장 게이트 / 어제와 달라진 것. 나머지는 접기.
2. **종목 허브** (3.2-3 와 동일).
3. **공개 Track Record** (3.3-4 와 동일).
4. **UI 프리미티브 5개** — `Card/StatCard/Badge/DataTable/StateBlock`, 복제 17벌 삭제.
5. **디자인 토큰** — 표면/경계/텍스트 CSS 변수화, `.claw-theme` 속성 정규식 제거.
6. **네이밍 1체계** — 4동사(Watch/Screen/Decide/Verify)로 8브랜드 흡수, 라벨 소스 1개를 5개 네비가 소비.
7. **모바일 카드화** — `DataTable` 이 `md` 미만에서 행→카드.
8. **중복 정리** — 분석 도구 2→1, VCP 4→`/screener?market=`, 챗봇 스텁 삭제 또는 판매문구 삭제.
9. **모바일 홈 이중 렌더** — `DashboardClient.tsx:715-1350` 이 모바일 콘솔 뒤에 데스크톱 섹션을 그대로 반복. 콘솔에 없는 섹션(AI Brain 배너·커뮤니티)을 어디에 둘지 결정 후 `hidden md:block` 적용 (제품 결정 필요해 Phase 0 제외).
10. **티저 티어** (3.3-3 와 동일).

---

## 4. 통합 우선순위 매트릭스

영향(구독자 체감 + 매출 + 위험감소) 1~5, 노력 1~5(1=반나절, 5=수주). 점수 = 영향² / 노력.

| 순위 | 항목 | 영향 | 노력 | 점수 | Phase |
|---|---|---|---|---|---|
| 1 | 브리핑 검색 요구 제거 | 5 | 1 | 25 | 0 ✅ |
| 2 | 캐시 분기 + ETag + gzip | 4 | 1 | 16 | 0 ✅ |
| 3 | 팔레트 검색 리졸버 연결 | 4 | 1 | 16 | 0 ✅ |
| 4 | LLM 브레이커 쿨다운 | 4 | 1 | 16 | 0 ✅ |
| 5 | 사용자 대상 승인/만료 알림 | 5 | 2 | 12.5 | 1 |
| 6 | 공개 Track Record | 5 | 2 | 12.5 | 1 |
| 7 | feature snapshot 저장 | 5 | 2 | 12.5 | 1 |
| 8 | LLM 응답 캐시 + 실측 예산 가드 | 4 | 2 | 8 | 1 |
| 9 | 잡 상태 보드 + 트리거 확장 | 4 | 2 | 8 | 1 |
| 10 | 종목 허브 페이지 | 5 | 3 | 8.3 | 1 |
| 11 | 리졸버 DB 부팅 생성 | 3 | 1 | 9 | 1 |
| 12 | number_guard enforce | 4 | 2 | 8 | 1 |
| 13 | 퍼널 이벤트 계측 | 4 | 2 | 8 | 1 |
| 14 | `load_json_cached` 전면 + picks 사전계산 | 3 | 1 | 9 | 1 |
| 15 | 의존성 핀 + 부팅 설정 검증 | 3 | 1 | 9 | 1 |
| 16 | 입금 자동 매칭 | 5 | 3 | 8.3 | 2 |
| 17 | 관심종목 + 개인 알림 | 5 | 3 | 8.3 | 2 |
| 18 | "오늘" 홈 | 4 | 3 | 5.3 | 2 |
| 19 | 티저 티어 + FunnelGate 완화 | 4 | 3 | 5.3 | 2 |
| 20 | UI 프리미티브 + 토큰 + 네이밍 1체계 | 4 | 3 | 5.3 | 2 |
| 21 | 비용 반영 아웃컴 + skipped 버킷 + VCP RS | 4 | 2 | 8 | 2 |
| 22 | `_time_weight` 표시필드화 | 3 | 1 | 9 | 2 (운영자 확인) |
| 23 | Stripe 자동갱신 + 연간 SKU | 5 | 3 | 8.3 | 2 |
| 24 | FTS5 통합검색 + 뉴스 원장 합류 | 4 | 3 | 5.3 | 3 |
| 25 | 아웃컴→컴포넌트 캘리브레이션 + 채점기 통합 | 5 | 5 | 5 | 3 |
| 26 | 저장소 정리(exe/data untrack, dead stack 삭제) | 3 | 2 | 4.5 | 운영자 결정 |
| 27 | TradingAgents 프롬프트 캐싱 + JSON repair | 3 | 2 | 4.5 | 3 |
| 28 | DART 구조 파싱 | 4 | 4 | 4 | 3 |

---

## 5. 실행 로드맵

### Phase 0 — 이 PR (완료, 테스트 포함)
| 변경 | 파일 | 검증 |
|---|---|---|
| 캐시 dead-branch 수정, weak ETag + 304, flask-compress 옵셔널 | `app/__init__.py`, `requirements.txt` | `test_review_quick_wins.py::test_authenticated_get_json_is_privately_cacheable_with_etag` 등 + 기존 `test_security_regressions` |
| LLM 브레이커 쿨다운/half-open, `is_api_available()` | `engine/llm_analyzer.py` | `test_llm_breaker_*` |
| 브리핑 프롬프트 `search_capable` 분기 | `briefing_generator.py` | `test_briefing_prompt_never_asks_for_search_on_non_grounded_path` |
| jongga 포화점 상수화 + 이론 최대와 대조 (동작 불변) | `app/services/mirofish/alpha_scanner.py` | `test_alpha_scanner_jongga_scale_is_documented_against_score_detail_max` |
| 검색: 리졸버(초성·별칭·퍼지) 병합 + 응답에 `match/confidence` | `app/routes/stock_analyzer.py` | `test_search_*` 3개 |
| CommandPalette 요청 취소 | `frontend-react/src/components/layout/CommandPalette.tsx` | vitest/lint/build |
| LLM usage + `est_cost_usd` 메타데이터, 단가표 | `app/services/mirofish/llm_client.py`, `llm_pricing.py` | `test_llm_metadata_carries_usage_and_cost` 등 |
| 스케줄러 status 에 데몬 heartbeat + last_runs | `app/utils/scheduler.py` | `test_scheduler_status_*` |
| `.env.example` 인벤토리 249개 + 생성 스크립트 | `.env.example`, `scripts/gen_env_inventory.py` | — |
| CI timeout + lint | `.github/workflows/test.yml` | CI |

**배포 시 주의**
- miniPC 에서 `pip install -r requirements.txt` (flask-compress). 미설치여도 앱은 뜬다(옵셔널 import). 압축을 끄려면 `MARKETFLOW_COMPRESS=0`.
- Flask 5003 은 코드 변경만으로 재시작되지 않는다. `git pull` 후 `New-Item data\flask_restart.request` 를 만들면 `flask_watchdog_v2.ps1` 이 5분 내 재기동한다(또는 `MarketFlow-Flask` 태스크 재시작). 이후 `scripts\minipc_post_deploy_check.ps1` §7 이 flask-compress 설치·ETag/304·데몬 heartbeat 를 검증한다.
- Cache-Control 변경으로 인증 GET 데이터가 브라우저에 30초 private 캐시된다. 즉시 반영이 필요한 실시간 라우트는 이미 자체 `no-store` 를 지정하고 있어 영향 없음(`kr_claw.py`, alpha dashboard 등 테스트로 고정).

### Phase 1 — 2주: "연결하기"
1. 사용자 대상 알림(승인/D-3/D-1/만료) — `telegram_chat_id` 컬럼 + 마이그레이션.
2. 공개 Track Record 라우트 + 지연 API.
3. feature snapshot 저장(종가베팅·주도주).
4. 종목 허브 페이지(decision_brief 렌더) + 리스트 행 딥링크.
5. 리졸버 DB 부팅 생성 태스크.
6. number_guard enforce (브리핑·주도주 사유).
7. LLM 응답 캐시 + 실측 예산 가드(auto_runner 의 $0.07 → 실측 합).
8. 잡 상태 보드 탭 + 트리거 30잡.
9. 퍼널 이벤트 4지점.
10. `load_json_cached` 전면, picks 사전계산, 의존성 핀, 부팅 설정 검증.

### Phase 2 — 4~6주: "자동화·증명"
입금 자동 매칭, 관심종목+개인 알림, "오늘" 홈, 티저 티어, UI 프리미티브/토큰/네이밍, 비용 반영 아웃컴, Stripe 자동갱신 + 연간 SKU, `_time_weight` 표시필드화(운영자 확인 후).

### Phase 3 — 분기: "학습·검색 심화"
FTS5 통합검색, 뉴스 원장 합류 + 근사중복, 아웃컴→컴포넌트 캘리브레이션, 채점기 통합(피처 레이어 1개), TradingAgents 프롬프트 캐싱, DART 구조 파싱, 저장소 정리.

---

## 6. 구독력 전략 (제품 관점)

**포지셔닝 한 문장**: "매일 15:10, 검증 가능한 근거와 사후 성적표가 붙은 한국 주식 후보 3개" — 예측이 아니라 **관찰 우선순위 + 검증**을 판다. 이미 AGENTS.md 의 미션과 랜딩 카피가 이 방향이며, 부족한 것은 **증명의 노출**이다.

**가치 증명 루프 (Prove → Notify → Retain)**
1. Prove: 공개 Track Record(지연) → 종목 허브에서 근거 11소스 → PerformanceCard 에 컴포넌트별 실현 적중률.
2. Notify: 승인/만료/신호 전이/관심종목을 **본인** 텔레그램으로.
3. Retain: 온보딩 체크리스트, "어제와 달라진 것" 카드, 갱신 D-7 배너 + D-3/D-1 개인 알림, 연간 SKU.

**가격 구조 제안** (운영자 결정): Free(티저: T-1 신호·상위 1개) → Pro ₩50k/월 → Pro 연간(2개월 할인) → Pro+AI Brain ₩90k → Ultra Pro 평생. 50k→1.2M 사이의 공백을 연간으로 메우고, 계좌이체와 카드(Stripe) 병행.

**금기 유지**: 수치는 API/파일/결정론 계산에서만(number_guard), 약한 신호(소셜/검색량)는 단독 매수 신호 금지, 백테스트에 진입일·호라이즌·비용·FP/FN 명시 — AGENTS.md 규칙 그대로.

---

## 7. 측정 지표 (개선 전/후 비교용)

| 지표 | 측정 위치 | 목표 |
|---|---|---|
| 데이터 GET 중 304 비율 / 평균 응답 바이트 | Cloudflare 애널리틱스 또는 Flask 로그 | 5초 폴링 페이지 304 ≥ 80%, 바이트 −80% |
| LLM 일일 비용(USD) / 실행당 비용 | `llm_calls[].est_cost_usd` 합 → 관리자 보드 | 실측 기준 예산 가드 |
| 브레이커 half-open 재시도 성공률 | `is_api_available` 로그 | 키워드 폴백 비율 감소 |
| 검색 → 종목 진입률, 무결과 검색 비율 | 팔레트 이벤트 | 무결과 −50% |
| 퍼널 전환(signup→plan→request→approved), 승인 리드타임 | `funnel_events` | 리드타임 < 1h |
| 30일 갱신율, 만료 후 7일 내 복귀율 | `pro_expiry` 스윕 | 갱신율 +10%p |
| 컴포넌트별 실현 적중률(비용 반영) | outcome_tracker | 캘리브레이션 오차 축소 |
| 잡 성공률/지연, 데몬 stale 이벤트 | `/api/scheduler/status.daemon` | 무인 실패 0 |

---

## 8. 이번 PR 에서 의도적으로 하지 않은 것 (운영자 결정 필요)

1. **`cloudflared.exe`/`data/**` untrack** — miniPC 워치독 `git pull` 이 워킹트리를 갱신하므로 exe 가 삭제되어 터널이 죽을 수 있다. exe 를 저장소 밖으로 옮기고 `deploy/start_cloudflared.vbs` 경로를 바꾼 뒤 진행.
2. **`_time_weight` 제거** — S등급 텔레그램 임계치와 순위 이력의 의미가 바뀐다. 표시 필드로 남기는 안을 권장하되 운영자 확인 후.
3. **모바일 홈 이중 렌더 수정** — 데스크톱 섹션을 숨기면 AI Brain 배너·커뮤니티 요약이 모바일에서 사라진다. 콘솔에 흡수할 항목 결정 후 적용.
4. **가격/티어 변경, 무료 티저** — 매출 정책.
5. **저장소 dead stack 삭제**(`backend/`, `Dockerfile`, `docker-compose.yml`, `crypto-analytics/`) — 타 프로젝트 참조 여부 확인 필요.
6. **jongga → alpha 환산 스케일(15 vs 20)** — /20 으로 바꾸면 총점 13 인 셋업의 alpha 기여가 8.7→6.5 로 내려가 `actionable` 임계를 못 넘는다(`test_alpha_scanner_advanced_analysis_penalizes_single_day_spikes`). 변별력을 살리려면 `_signal_quality` 임계와 함께 조정해야 하므로 Phase 2 캘리브레이션 작업과 묶는다.
