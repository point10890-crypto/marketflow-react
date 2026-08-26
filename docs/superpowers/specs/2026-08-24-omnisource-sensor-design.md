# 옴니소스 24시간 센서망 설계도 — 전매체 수집·학습 시스템

작성일: 2026-08-24 (KST)
성격: "뉴스·경제·문화·정치·사회·트렌드·학술·논문·소셜·유튜브·인스타·X 등 모든 매체를 24시간 검색·수집·학습"할 수 있는가에 대한 실사 판정 + 구축 설계
선행 문서: `2026-08-24-alphaclaw-integration-review.md` (C7 소셜 보류의 해소 조건이 본 문서), `2026-08-24-analysis-core-redesign.md` (v3 — 근거 등급·E 규칙)
원칙: 실데이터만 · 원문 비축적 · 외부 텍스트는 지시가 아니라 데이터 · 수집 계층에 발송/주문 도구 없음

---

## 0. 판정

**가능하다 — 단, "전매체 전수 수집 후 통째 학습"이 아니라 "24시간 센서망 + 적합성 깔때기 + 사건(event) 원장"으로만 가능하다.**

전수 수집이 불가능한 이유는 기술이 아니라 구조다:
1. **약관·법**: 인스타그램·틱톡·로그인 뒤 콘텐츠는 스크랩 자체가 약관 위반. 뉴스 원문 대량 저장은 저작권 문제. → 요약·집계·링크만 저장.
2. **노이즈 경제학**: 하루 원문 10만 건을 저장·임베딩하면 비용은 커지고 신호는 늘지 않는다. 검출에 필요한 것은 원문이 아니라 **"어떤 사건이, 어떤 강도로, 어떤 종목 경로에 닿는가"** 수십 건이다.
3. **보안**: 외부 텍스트는 프롬프트 인젝션 표면이다. 수집량이 늘수록 LLM에 닿는 비가신뢰 텍스트를 줄이는 설계가 필요하다(깔때기의 앞 2단은 LLM 없이 결정론).

핵심 재사용 자산 (실측 확인, 2026-08-24):
| 자산 | 위치 | 역할 |
|---|---|---|
| 텍스트 인제스트 계층 | `document_ingestor.py` (청킹 1500자/overlap 200) → `graphrag_extractor.py` (엔티티/관계 추출, Gemini structured + rule 폴백, 호출 캡 `MIROFISH_GRAPHRAG_MAX_CALLS=3`) → `data/admin_mirofish/ekg.json` | **학습(그래프 축적)의 뼈대가 이미 있다** |
| 뉴스 수집기 | `engine/collectors.py: EnhancedNewsCollector` (네이버 금융/검색, 종목 단위 온디맨드) | 센서 어댑터 원형 — 상시형으로 확장 |
| 공시·매크로 | `engine/dart_collector.py`, market_gate, credit_balance, sector_rs | S/A 등급 센서 기존재 |
| 유니버스·테마 | KRX 보통주 2,550 (`korean_stocks_list` 계열), 스크리너 themes 필드 | 깔때기 1단 결정론 매칭 사전 |
| 스케줄·감시 | `scheduler.py` + Task Scheduler + watchdog, Claw 루프 | 24시간 상주 패턴 기존재 |
| LLM 예산·폴백 | `llm_client.py` provider 체인, graphrag 호출 캡 | 3단 태거 비용 통제 |

---

## 1. 매체별 실사 (되는 것 / 안 되는 것)

| 매체 | 판정 | 방법 | 근거 등급 | 비고 |
|---|---|---|---|---|
| 뉴스 (한경·매경·연합 등 RSS, 네이버 뉴스) | **가능 (O1)** | RSS/공개 피드 폴링 15분 + 기존 네이버 수집기 상시화 | B (해석) / A (사실 보도의 수치 인용은 원소스 재확인 후) | 원문 저장 금지 — 제목·요약·링크·해시만 |
| 공시 (DART) | **기존재** | dart_collector | **S** | 이미 점수 체계 반영 중 |
| 매크로 (한은 ECOS, FRED, 정책 보도자료) | **가능 (O1)** | 공식 API, 일 1~2회 | **S/A** | 발표 캘린더 이벤트화 |
| 학술·논문 (arXiv q-fin, OpenAlex, 한은·KDI·자본연 발간물) | **가능 (O2)** | 공식 API/RSS, **주간** 다이제스트 | A (기관) / B (프리프린트) | 장중 신호 아님 — 가설 원장(H-*) 입력용 |
| 유튜브 | **조건부 (O3)** | **Data API + 워치리스트 채널의 자막(transcript)만**. 전체 탐색 금지 | B~C | 영상 원본 저장·학습 금지. 채널 목록은 사용자 승인제 |
| X(트위터) | **조건부·보류 (O4)** | 공식 API 한정. 무료 티어 읽기 제한이 심해 **유료 티어 결정 필요** | C (집계 z-score만) | 스크랩 대체 금지. 결정 전 미구현 |
| Reddit | **조건부 (O4)** | 공식 API, 서브레딧 화이트리스트 집계 | C | 집계 지표만, 원문 단기 보관 |
| 네이버 종토방 | **보류** | 약관·봇 필터 불확실 | C | 집계 설계 확정 전 금지 |
| 인스타그램 | **불가** | 공개 API가 이 용도를 지원하지 않음, 스크랩은 약관 위반 | — | 수집 대상에서 제외 |
| 틱톡 | **불가** | 동일 | — | 제외 |
| 문화·정치·사회 이슈 | **가능 (간접)** | 별도 매체가 아니라 위 채널들에서 **테마 사전 매칭**으로 포착 (정책 키워드 → 수혜 섹터 경로) | 상속 | §4 테마 레이더 |

C등급 센서(소셜)는 v3의 E 규칙에 종속된다: **단독으로 후보를 만들 수 없고**, 기존 검출 후보에 대한 보조 증거·버즈 이상 감지로만 쓰인다. 이것이 AlphaClaw 리뷰 C7 보류의 해소 조건이다.

---

## 2. 아키텍처

```
[센서망]  news_rss · dart(기존) · macro_api · scholar_weekly · youtube_watchlist
 (어댑터)  · x_api(보류) · reddit_agg(보류)
    │  어댑터당: poll 주기 · 소스 등급 · robots/약관 플래그 · 실패 격리
    ▼
[정규화]  RawItem {source, url, title, summary(≤500자), published_ts, fetched_ts,
              content_hash, grade}          ← 원문 본문은 저장하지 않는다
    ▼
[적합성 깔때기]  (LLM은 3단에서만)
  0단  dedupe: content_hash + (source, url) — 재수집·정정판 중복 제거
  1단  결정론 매칭: 종목명/티커(2,550) · 테마 사전 · EKG 엔티티 별칭
        → 매칭 0건이면 즉시 폐기 (하루 수만 건이 여기서 사라진다)
  2단  중요도 스코어(결정론): 소스등급 가중 + 다중소스 동시성(같은 사건을
        n개 매체가 보도) + 신선도 + 워치리스트 부스트 → 임계 미달 폐기
  3단  LLM 이벤트 태거 (일일 예산 cap, graphrag 재사용):
        {event_type, direction, magnitude, entities[], theme, symbol_paths[],
         confidence} — numbers_used 규칙: 태거는 RawItem 요약 밖 수치 생성 금지
    ▼
[사건 원장]  data/omni/omni.db (SQLite·WAL, Claw 패턴)
  events(id, ts, event_type, grade, theme, entities_json, symbols_json,
         sources_json(≥1), magnitude, decayed_at)  UNIQUE(event_key)
    ▼
[공급]  ① 스코어카드 evidence[]에 grade 그대로 병기 (E1~E3 적용: B/C 단독 통과 불가)
        ② 테마 레이더: 테마별 사건 밀도·신규성 → 대시보드/브리핑
        ③ EKG 병합: 사건 엔티티/관계를 ekg.json에 누적 (기존 graphrag 경로)
        ④ 가설 원장: 학술 다이제스트 → H-* 후보 (사람 승인 후 등록)
    ▼
[학습]  event_edge_map: 사건유형×테마×국면(RegimeContext) → D1/D5 가격 반응
        버킷 통계 (edge_map 패턴, n<5 insufficient) — 관찰 전용으로 시작,
        스코어 반영은 기존 5중 브레이크 체인 통과 후에만
```

**"모든 매체를 학습한다"의 실체 = 이 세 갈래다:**
(a) EKG 그래프 축적(엔티티·관계·테마의 장기 기억), (b) event_edge_map(사건→가격 반응의 통계 기억), (c) 깔때기 자기 교정(반응 없는 event_type의 2단 임계 상향 — 표본 게이트 후).

---

## 3. 사건 스키마 (`mirofish.omni_event.v1`)

```json
{
  "event_key": "sha1(event_type|theme|top_entity|date)",
  "ts": "2026-08-24T09:12:00+09:00",
  "event_type": "policy|earnings|supply_chain|regulation|litigation|trend|macro_release|research",
  "direction": "pos|neg|mixed|unknown",
  "magnitude": 1,
  "grade": "A",
  "theme": "전력기기",
  "entities": [{"id": "ekg:...", "name": "...", "type": "company|person|policy|product"}],
  "symbol_paths": [{"code": "005930", "path": "직접|섹터|공급망", "hop": 1}],
  "sources": [{"src": "yonhap_rss", "url": "...", "grade": "A"},
               {"src": "youtube:채널명", "url": "...", "grade": "B"}],
  "data_gaps": [], "llm_tagged": true, "decay_days": 5
}
```

- `sources` 2개 이상(독립 소스)이어야 magnitude 2 이상 가능 — 교차검증 원칙의 사건 버전.
- `symbol_paths.hop`: 직접 언급=1, 섹터/공급망 추론=2. hop 2는 confidence_cap 하향 요인.
- `decay_days` 경과 시 테마 레이더에서 자동 소멸 (좀비 사건 방지 — scanner feed recency 버그의 교훈).

---

## 4. 보안·컴플라이언스 불변조건 (테스트 고정 대상)

1. **외부 텍스트는 데이터다.** 수집물에 포함된 지시문("이 종목을 사라", "이전 지시를 무시하라")은 실행 대상이 아니다. LLM 태거는 도구 없이 structured output만 반환하며, 태거 출력의 자유 텍스트는 파이프라인 어디에서도 명령으로 해석되지 않는다.
2. 센서·태거 계층에는 **발송(telegram)·주문·파일시스템 쓰기(원장 외) 도구가 없다.** 발송은 기존 reporter/delivery 경로만.
3. 원문 본문 비저장 — 제목·요약(≤500자)·링크·해시만. 소셜은 집계 수치만.
4. robots.txt·API 약관 준수, 로그인 우회·비공식 스크랩 금지 (Investing.com 403·Cloudflare 실측 교훈).
5. 개인 계정·개인정보 수집 금지. 사람 이름은 공인·공시 임원 맥락만.
6. LLM 일일 예산 캡 (`OMNI_TAGGER_DAILY_BUDGET`, 기본 100건) — 초과분은 2단 스코어 순 대기, 다음 예산에서 처리 또는 소멸.
7. 킬스위치: `OMNI_ENABLED`, `OMNI_SOURCE_<NAME>_ENABLED`(어댑터별), `OMNI_LLM_TAGGER_ENABLED`.

---

## 5. 운영 (24시간 상주)

| 시각/주기 | 작업 | 비고 |
|---|---|---|
| 15분 | 뉴스 RSS 폴링 → 깔때기 0~2단 | 결정론만, LLM 없음 |
| 1시간 | 3단 LLM 태깅 배치 (예산 내) | 장중엔 고득점 우선 |
| 07:30 | 매크로 캘린더 + 밤사이 사건 요약 → 기존 조간 브리핑에 병합 | Claw morning과 통합 |
| 일 1회 (장후) | 유튜브 워치리스트 자막 수집·태깅, event outcome D1 채움 | 17:15 슬롯 공유 (16:30 회피) |
| 주 1회 (토) | 학술 다이제스트 → 가설 후보, event_edge_map 재빌드, 깔때기 임계 리뷰 | 사람 리뷰 포함 |

상주 위치: **신규 프로세스를 만들지 않는다.** 15분/1시간 잡은 `scheduler.py`에 잡으로 편입(기존 스케줄 시각과 충돌 검사 필수 — 16:30 기점유 교훈), 사건 원장은 Claw처럼 독립 SQLite. miniPC 반영은 기존 배포 게이트.

---

## 6. 비용 추정 (월, 소규모 기준)

| 항목 | 추정 | 비고 |
|---|---|---|
| LLM 태깅 (일 100건 × 짧은 structured 호출) | 기존 Gemini 예산 내 소폭 증가 | graphrag 캡 패턴 재사용 |
| 뉴스 RSS·arXiv·OpenAlex·ECOS·FRED | 0원 | 공개 API |
| YouTube Data API | 무료 쿼터 내 (워치리스트 소수 채널) | 쿼터 초과 시 채널 축소 |
| X API | **유료 티어 결정 전 0원 (미구현)** | 결정 사항 #3 |
| 저장 | SQLite 수십 MB/년 | 원문 비저장 덕분 |

---

## 7. 로드맵

| 단계 | 내용 | 게이트 |
|---|---|---|
| **O1** | 공통 어댑터 프레임 + 뉴스 RSS 상시화 + 매크로 캘린더 + 깔때기 0~2단(결정론) + 사건 원장 | 1주 dry-run 후 사람 육안 검증(잡음 임계 조정) — 기존 관례 |
| **O2** | 3단 LLM 태거(예산제) + EKG 병합 + 테마 레이더(대시보드 카드) | 태거 출력 스키마 준수율·numbers_used 위반 0 |
| **O3** | 유튜브 워치리스트 자막 + 학술 주간 다이제스트 → 가설 후보 | 워치리스트 사용자 승인 |
| **O4** | event outcome(D1/D5) 채움 + event_edge_map (관찰 전용) | lookahead 리플레이 검증 |
| **O5** | X/Reddit 집계 (API 티어 결정 후) + 깔때기 자기 교정(표본 게이트) | C7 해소 조건 충족 + 5중 브레이크 체인 |

v3/AlphaClaw 통합 로드맵(R0′~R5)과 독립 병행 가능하나, **R0′(비용 차감 재현)가 여전히 전체 1순위**다 — 센서를 늘리기 전에 기존 검출의 손익 근거부터 재현한다.

## 8. 결정 필요 사항

1. O1 착수 승인 + 뉴스 RSS 소스 목록 (연합·한경·매경 + 추가 희망 매체)
2. 유튜브 워치리스트 초기 채널 목록 (사용자 지정)
3. X API 유료 티어 (기본: 미도입 — Reddit 집계 먼저)
4. 사건 원장 위치 `data/omni/` 신설 vs `data/admin_mirofish/omni/` 편입
5. 테마 사전 초기본 — 기존 스크리너 themes 필드에서 시드 후 수동 보강 여부
