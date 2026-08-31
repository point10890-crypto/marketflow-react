# AI Brain 서비스 가드 설계 — 알파 스캐너 · AI 펀드매니저 · 판단 조회 지속성

작성: 2026-09-01 (서비스 정식 운영 개시일) · 상태: 구현과 동시 진행
전제: 인프라 생존은 기존 자산(플라스크/스케줄러/터널/Claw 워치독, `app/utils/diagnostics.py` 자가진단)이 담당한다.
이 설계는 그 위 **서비스 수준** — "구독자가 지금 이 기능을 쓸 수 있는가" — 만 다룬다.

## 1. 보호 대상과 실패 정의

| 서비스 | 정상 정의 | 실패 신호 |
|---|---|---|
| 알파 스캐너 | 장중(09:00~16:30) 최신 run ≤ 90분, 장외엔 최근 세션 run 존재. alert-required 소스 fresh. 모니터 상태파일 갱신 | run 부재/노후, blocked_freshness 지속 |
| AI 펀드매니저(Goodrich) | goodrich-tradingos(127.0.0.1:8000) 5초 내 응답, 원장(goodrich_ledger.jsonl) 최근 항목 ≤ 24h(영업일) | 503/504/타임아웃, 원장 정체 |
| 판단 조회(decision) | 인프로세스 프로브(회전 핫 심볼) 웜 ≤ 5s(warn)/20s(fail), 소스별 timings_ms ≤ 5s, decision_cache 쓰기 가능 | 프로브 초과·예외, 캐시 쓰기 실패 |

## 2. 구성요소

1. **`app/services/mirofish/service_guard.py`** — 읽기전용 체커 3개 + `run_guard(send_fn)`:
   - 결과 `{generated_at, overall: ok|warn|fail, services: {scanner|goodrich|decision: {status, detail, checked_ms}}}`
   - `data/admin_mirofish/service_guard_latest.json`(atomic) + `service_guard_history.jsonl`(일 단위 append, 30일 보존은 후속)
   - **상태전이 알림만**: 서비스별 직전 상태를 state 파일에 저장, `ok→warn/fail` 1회, `→ok` 복구 1회, 동일 상태 재알림 쿨다운 30분. 발송은 주입된 send_fn(개인봇) — 서비스 모듈은 텔레그램을 모른다.
2. **남용 차단(보안책)** — `POST /api/kr/decision/<symbol>/analyze` 에 사용자별 일일 쿼터:
   - `decision_cache` DB에 `deep_quota(day, user_id, count)` — 기본 20회/일(`DECISION_DEEP_DAILY_QUOTA`, 0=무제한), admin 면제, 초과 시 429 `{error: quota_exceeded, remaining: 0, limit}` (캐시 적중은 차감하지 않음 — 재조회는 무료)
   - 근거: 심층분석 1회 = LLM 8~12콜. 유료 사용자라도 무제한이면 비용·경합 폭주.
3. **판단 캐시 프리웜** — `service_guard.prewarm_decision_cache(limit=12)`:
   - 핫셋 = 최신 스캐너 후보 + Goodrich 원장 최근 심볼 + 주도주 S/A (중복 제거, limit)
   - 각 심볼 `build_decision_brief` → `decision_cache.cache_put` (이미 오늘 캐시면 스킵)
   - 효과: 구독자의 "첫 조회 수십 초" 자체를 소멸(백그라운드에서 미리 데움). db1eb4e 근본수정과 상보적.
4. **관리 API** — `GET /api/admin/mirofish/service-guard` (`@admin_or_aibain_required`, no-cache): latest JSON 반환. FE 카드는 후속.
5. **스케줄러 배선** (`AIBRAIN_GUARD_ENABLED`, 기본 true):
   - 가드: 평일 08:40~16:40 10분 주기(`AIBRAIN_GUARD_TIMES` 대신 interval)
   - 프리웜: 평일 08:25(조간 전) · 15:05(종가베팅 직후) — `AIBRAIN_PREWARM_TIMES`
6. **수동 CLI** — `scripts/aibrain_guard.py [--prewarm] [--json]`: 운영자가 즉석 점검.

## 3. 비-목표 (이번 범위 밖)
- 워커 경합 자체의 구조 해소(판단 계산 프로세스 분리) — 후속 아키텍처 과제
- 심층분석의 Cloudflare 100초 한계(job+poll 전환) — 후속
- FE 관리 카드 / 히스토리 보존정책 — 후속

## 4. 검증
- 단위: 각 체커 픽스처(신선/노후/부재), 전이 알림(1회·쿨다운·복구), 쿼터(차감·면제·429·캐시적중 무차감), 프리웜(핫셋 구성·캐시 채움·이미 캐시 스킵)
- 통합: 로컬 실행 `aibrain_guard.py --json`, 기존 decision/scanner 스위트 회귀
- 배포: miniPC pull + Flask 재부팅(스케줄러 재시작 포함), 가동 후 첫 가드 알림 확인

## 5. 후속 이행 (같은 날 2차)

- **심층분석 job+poll 전환 완료** — §3에서 미뤘던 Cloudflare ~100초 한계 해소.
  `decision_jobs.py`(스레드 잡, 동일 종목 합류, 동시 상한 `DECISION_JOB_MAX_CONCURRENT`=2, 실패 미캐시),
  `POST /analyze` = 캐시 200 / 잡 시작·합류 202 / 한도·busy 429, `GET /analyze/status` 폴링.
  쿼터는 잡을 실제 시작할 때만 차감. FE는 시작→3초 폴링(최대 8분, 진행 문구)이며 구백엔드
  동기 응답과 호환(analysts 포함 응답은 즉시 렌더) → **FE 먼저 배포해도 안전**.
  한계(기록): 잡은 프로세스 메모리 상주 — Flask 재시작 시 진행 중 분석 유실(폴링이 none 안내). 영속화는 후속.
- **서비스 가드 카드(FE)** — AI Brain 상세 영역 `ServiceGuardCard`(60초 갱신, 권한/미배포 시 미렌더).
- 남은 후속: 판단 계산 프로세스 분리(워커 경합 구조 해소), 잡 영속화, 가드 히스토리 보존정책.
