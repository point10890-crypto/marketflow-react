# Claw LIVE 대시보드 설계

작성: 2026-08-22 (KST) · 대상 시스템: `marketflow_claw/` Phase 1 (origin/main `a030586`)
상태: 설계 + 실데이터 프로토타입 완료, React/Flask 구현은 승인 대기
프로토타입(실제 `claw.db` 데이터 렌더): `docs/superpowers/specs/2026-08-22-claw-dashboard-preview.html`

---

## 1. 목적과 원칙

이 화면의 단 하나의 일: **"지금 장에서 주도주가 어떻게 움직이고 있고, Claw가 그걸 제대로 보고 있는가"를 5초 안에 읽게 한다.**

| 원칙 | 구현 방식 |
|---|---|
| 시안성(視認性) | 상단 4타일이 상태를 색으로 먼저 말한다(정상=청록, 보류=앰버, 장외=회색). 숫자보다 형태가 먼저 읽히게 칩·바·점으로 인코딩 |
| 편리함 | 페이지 1장, 스크롤 최소. 가장 자주 보는 것(주도주·이벤트)이 첫 화면 안에. 세부(시스템·원장)는 접힘 |
| 간단함 | 카드 4종만: 상태 스트립 / 주도주 / 이벤트 / 브리핑(+접힌 시스템). 점수 분해·수급 같은 밀도 높은 정보는 주도주LIVE 페이지에 위임하고 링크 |
| 비율 | 데스크톱 12컬럼 그리드: 주도주 **7** : 이벤트 **5** (황금비 근사 1.4:1). 하단 브리핑 **8** : 시스템 **4**. 카드 내부 여백 20px, 카드 간격 16px, 최대폭 1200px |

기존 앱과의 정합: 페이지 배경 `#09090b`, 카드 `bg-[#13151f] border-white/[0.06] rounded-2xl`, FA 아이콘, 등급 색은 주도주LIVE 페이지의 `GRADE_STYLE`(S=rose, A=amber, B=blue) 재사용, 등락은 KRX 관례(상승 빨강·하락 파랑). AiBain 대시보드의 "요약 먼저, 상세는 접기" 패턴을 그대로 따른다.

## 2. 정보 구조 (위→아래 = 중요도 순)

```
┌─ 헤더: ● Claw LIVE  · 마지막 틱 14:02:05 · [주도주LIVE 열기] ───────────────────────┐
├─ 상태 스트립 (4타일, 각 3col) ──────────────────────────────────────────────────┤
│  루프/시장      │  레짐            │  오늘 이벤트        │  발송                    │
│  ● 장중 · 3s    │  NEUTRAL 54      │  9 · NEW2 UP4 DROP2 │  3/3 · @bitman75 DM      │
├─ 주도주 (7col) ───────────────────────┬─ 이벤트 타임라인 (5col) ─────────────────┤
│  S 금호건설 71 ████████░ +30.0% 386억  │  09:41 NEW  금호건설 –→S  ✓               │
│     NEW 09:41 · 유지 4h21m             │  09:41 UP   기가레인 B→A  ✓               │
│  A 티웨이홀딩스 63 ██████░░ +29.9%     │  10:12 UP   티웨이홀딩스 B→A ✓            │
│  …                                     │  13:04 HALT kis_token_failed x3           │
│  ▸ B등급 6종목 보기                     │  [전체] [NEW] [UP] [DROP] [VOL] [HIGH]     │
├─ 브리핑 (8col) ───────────────────────┬─ 시스템 (4col, 접힘 기본) ──────────────┤
│  [조간 08:20 ✓] [정오 11:30 ✓] [마감 –] │  heartbeat 3s · source file(4s)           │
│  말풍선 미리보기 (최근 1건)             │  KIS 0회 · 스냅샷 3,612 · DB 1.2MB        │
└────────────────────────────────────────┴──────────────────────────────────────────┘
```

모바일(<768px): 같은 순서로 1열 스택. 상태 스트립은 2×2. 이벤트 타임라인은 최근 8건만 보이고 "더 보기".

## 3. 컴포넌트 명세

### 3.1 상태 스트립 `StatusStrip`
- **루프/시장**: 상태 점(청록 pulse=장중 틱 중 / 회색=장외 idle / 앰버=HALT / 빨강=하트비트 180s 초과) + "장중 · 마지막 틱 n초 전". 클릭 없음.
- **레짐**: `RISK_ON / NEUTRAL / RISK_OFF / UNKNOWN` 대문자 + gate 점수 + breadth%. 색: ON 초록, NEUTRAL 회색, OFF 파랑(하락 관례), UNKNOWN 점선 테두리.
- **오늘 이벤트**: 총계 큰 숫자 + 유형별 작은 칩(NEW/UP/DROP/VOL/HIGH). 0이면 "아직 없음".
- **발송**: `delivered/총 브리핑` + 경로(`@bitman75 DM`) + enabled 꺼짐이면 "dry-run" 배지(앰버).
- **HALT 상태**에서는 스트립 전체가 앰버 테두리로 바뀌고 첫 타일에 사유 1줄이 들어간다. 이때 주도주 카드는 흐려지고(opacity .5) "검출 보류 중 — 방향성 판단 없음" 오버레이.

### 3.2 주도주 `LeadersCard` (7col)
- 정렬: 등급(S>A) → 점수. S/A만 펼침, B는 접힘 행("B등급 n종목 보기").
- 행 구성(한 줄): 등급 칩 · 종목명(굵게) 코드(회색 mono) · 점수 바(0~100, 등급색) + 숫자 · 등락%(KRX 색, tabular) · 거래대금(억) · 오늘 이벤트 태그(`NEW 09:41` 등, 있을 때만) · 유지시간(첫 S/A 틱부터).
- 빈 상태: "현재 S/A 주도주 없음 — 마지막 스냅샷 hh:mm". 장외: 마지막 세션 스냅샷을 그대로 보여주되 헤더에 "전 세션 기준" 배지.
- 행 클릭 → 주도주LIVE 페이지의 해당 종목으로 이동(`/dashboard/kr/leading-stocks#code`). 점수 분해는 거기서.

### 3.3 이벤트 타임라인 `EventsCard` (5col)
- 최신이 위. 행: 시각(mono) · 유형 칩 · 종목명 · `from→to` · 발송 ✓/–.
- 유형 칩 색: NEW 청록, UP 초록, DROP 파랑, VOL 보라, HIGH 주황, HALT 앰버. 칩은 글자+연한 배경(테두리 없음) — 주도주 등급 칩(테두리형)과 시각적으로 구분.
- 상단 필터 칩(전체/NEW/UP/DROP/VOL/HIGH) — 토글식, URL 파라미터 없음(세션 내만).
- 빈 상태: "오늘 전이 없음". 장외에는 "전 세션 이벤트" 라벨.

### 3.4 브리핑 `BriefsCard` (8col)
- 탭 3개: 조간 / 정오 / 마감. 각 탭 라벨에 발송 시각과 ✓(delivered) 또는 `dry-run`.
- 본문: 텔레그램 말풍선 스타일 그대로(HTML 태그 렌더). 최대 12줄, 넘치면 "전체 보기".
- "다시 보내기" 버튼은 **두지 않는다**(발송은 CLI/스케줄만 — 대시보드에서 mutation 금지).

### 3.5 시스템 `SystemCard` (4col, 기본 접힘)
- heartbeat 나이, 소스(file age / kis), 오늘 KIS 직접 호출 수, 스냅샷 수, DB 크기, `drop_confirm_ticks`, 킬스위치 3종 상태. 전부 읽기전용 텍스트. 비밀값 없음.

## 4. 데이터 계약

`GET /api/kr/claw/overview` — `@pro_required` (주도주LIVE와 동일 권한). Flask는 `claw.db`·`heartbeat.json`·`screener_leading_latest.json`을 **읽기만** 한다. 30초 TTL 캐시 대신 `Cache-Control: no-cache`(실시간 카드). 응답:

```json
{
  "generated_at": "2026-08-22T01:21:23",
  "loop": {"state": "idle|running|halt|dead", "market_open": false, "heartbeat_age_s": 3,
           "last_tick_ts": "…", "source": "file", "source_age_s": 4},
  "regime": {"regime": "RISK_OFF", "gate_status": "RED", "gate_score": 70, "breadth_pct": 100,
             "halt": false, "reasons": ["market_gate stale/missing"]},
  "leaders": {"snapshot_ts": "…", "market_status": "closed", "by_grade": {"S":2,"A":7,"B":6},
              "rows": [{"code","name","grade","score","chg","trval_eok","since_ts","today_event":{"type","ts"}}]},
  "events": {"day": "20260822", "counts": {"LEADER_NEW":0,…}, "items": [{"ts","type","code","name","grade_from","grade_to","score","chg","reported_at"}]},
  "briefs": {"items": [{"ts","kind","delivered","error","text"}]},
  "system": {"snapshots_today": 3, "kis_calls_today": 1, "db_bytes": 57344, "drop_confirm_ticks": 3,
             "delivery": {"enabled": false, "mode": "direct-dm", "token_key": "TELEGRAM_CHANNEL_BOT_TOKEN"}}
}
```
- `since_ts`(유지시간)와 `today_event`는 서버가 `events`/`snapshots`에서 계산해 내려준다(클라이언트 계산 금지).
- `text`는 텔레그램용 HTML 그대로. 클라이언트는 `<b>`만 허용하는 sanitizer로 렌더(XSS 방지 — BriefingPortal 리뷰 이슈와 동일 규칙).
- 실패 시 섹션별 `null` + `errors: {section: message}`로 부분 렌더(AiBain `allSettled` 패턴).

## 5. 갱신 정책
- 장중: 5초 폴링(`useAutoRefresh`), 장외: 60초. 탭 비활성 시 중단.
- 스트립의 "마지막 틱 n초 전"은 클라이언트 타이머로 1초마다 증가(서버 재호출 없이 살아있음을 보여줌).

## 6. 라우팅·내비
- 경로 `/dashboard/kr/claw`, 사이드바 KR 그룹에 **Claw LIVE**(색 `bg-teal-500`) — 주도주LIVE 바로 아래.
- `ProGuard`. 파일: `frontend-react/src/pages/dashboard/kr/claw/{KrClawPage,StatusStrip,LeadersCard,EventsCard,BriefsCard,SystemCard}.tsx` + `app/routes/kr_claw.py`(Blueprint `/api/kr/claw`).

## 7. 상태 매트릭스 (모든 화면 상태를 정의)

| 상태 | 스트립 | 주도주 | 이벤트 | 브리핑 |
|---|---|---|---|---|
| 장중·정상 | 청록 pulse | 실시간 행 | 실시간 | 탭 |
| 장중·HALT | 앰버 테두리+사유 | 흐림+오버레이 | HALT 행 강조 | 보류 보고 |
| 장외(idle) | 회색 점 "장외 · 다음 09:00" | "전 세션 기준" 배지 | "전 세션 이벤트" | 탭 |
| 하트비트 끊김(>180s) | 빨강 점 "루프 응답 없음" | 마지막 스냅샷+경고 | 그대로 | 그대로 |
| 최초 로딩 | 스켈레톤 4타일 | 스켈레톤 5행 | 스켈레톤 | 스켈레톤 |
| API 오류 | 빨강 카드 + 다시 시도 | – | – | – |
| 데이터 없음(첫날) | 회색 | "아직 스냅샷 없음" | "아직 이벤트 없음" | "아직 브리핑 없음" |

## 8. 구현 순서 (승인 후)
1. `app/routes/kr_claw.py` overview 엔드포인트 + 테스트(픽스처 DB) — 읽기전용, 비밀값 0
2. React 페이지 6파일 + 사이드바 항목 + 라우트
3. 상태 매트릭스 7행을 Storybook 없이 `?mock=halt|idle|dead|empty` 쿼리로 강제 렌더해 육안 검증
4. `npm run build` → Cloudflare Pages 배포(`feedback_cloudflare_pages_deploy`), miniPC Flask는 런북과 함께 적용
