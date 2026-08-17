# 만료 회원 재구독 파이프라인 + 회원관리 개선 — 설계

2026-08-16 · 승인됨 (소급 자동복구 / 승인일+30일 / 전체 범위 + 관리자 프론트 디자인 포함)

## 문제

구독 만료 처리가 두 경로로 갈라져 서로 다른 결과를 낸다.

| 경로 | 처리 | 유저 경험 |
|------|------|----------|
| API 게이트 `_enforce_pro_access` | `status='expired'`, tier 보존 | 재구독 페이지 리다이렉트 (정상) |
| 만료 스레드 `_expiry_loop` (1h 주기) | `tier=None`, `pro_expires_at=None`, `status='suspended'` | 로그인 403 "계정이 정지되었습니다. 관리자에게 문의하세요" |

만료 시점에 접속해 있지 않은 대부분의 회원은 스레드가 먼저 돌아 suspended 로 굳는다.
로그인이 막히므로 재구독 경로가 차단되고, tier 가 지워져 어떤 플랜이었는지도 유실된다.
재구독 리다이렉트 인프라(프론트 가드, api 인터셉터, `is_expired_resubscribe` 예외)는
이미 구현돼 있으므로, 만료를 "정지"로 바꾸는 경로만 제거하면 전체가 맞물린다.

## 1. 만료 처리 단일화

모든 만료 경로의 결과를 통일한다: **`status='expired'`, `tier`·`pro_expires_at` 보존**.

- `app/__init__.py` `_expiry_loop`: `tier=None`/`pro_expires_at=None`/`status='suspended'` 제거
  → `status='expired'` 만 세팅. `pro_expiry_alert_stage='expired'` 는 유지(중복 알림 방지).
- `app/routes/stripe_routes.py:116`: `suspended` → `expired` 통일.
- 로그인: expired 는 정상 로그인 허용(현행 코드 그대로 — suspended/rejected 만 403).
  suspended 403 메시지는 수동 정지 전용으로 남는다.
- 만료 텔레그램 알림(D-3/D-1/만료): 만료 단계 문구에 재구독 안내와
  `https://bit-man.net/plan-select?resubscribe=1` 링크 포함.

## 2. 소급 복구 (1회성 마이그레이션 스크립트)

`scripts/restore_expired_members.py` (dry-run 기본, `--apply` 로 실행):

- 대상: `status='suspended'` AND `pro_expiry_alert_stage='expired'` AND
  AdminAuditLog 에 `set_status`→suspended 기록이 없는 유저.
- 처리: `status='expired'`, tier 는 마지막 approved SubscriptionRequest 의 `to_tier` 로 복원
  (없으면 audit `set_tier` before 값, 그것도 없으면 'pro').
  `pro_expires_at` 는 복원 시각-1초 (is_pro_expired=True 유지).
- 각 건 `_record_audit('restore_expired', ...)` + 대상/결과 리포트 출력.
- 관리자 수동 정지 회원은 건드리지 않는다.

## 3. 재구독 UX

- `/plan-select?resubscribe=1`: 만료 배너("구독이 만료되었습니다 — 이어서 이용하세요")
  + 기존 플랜 카드 하이라이트 + 원클릭 재신청. payment-request 프리필은 기존 재사용.
- 재구독 신청 시 관리자 텔레그램 + AdminNotification (기존 채널 재사용, 문구에 "재구독" 구분).
- 승인 시 기산점: **승인일 +30일** (현행 approve 로직 그대로 — 변경 없음을 테스트로 고정).

## 4. 관리자 페이지 개선 (프론트 디자인 포함)

- `GET /api/admin/subscriptions` 응답에 `expired_members` 갈래 추가
  (만료일·경과일·최근 로그인·복원 tier). 사각지대 제로 원칙을 만료 회원까지 확장.
- `SubscriptionsTab`: 4섹션 — 대기 중 / **만료 · 재구독 대기(신설)** / 가입만 완료 / 처리 이력.
  만료 섹션에 원클릭 "Pro 재부여" / "기간 연장" 액션.
- `UsersTab`: status 필터에 `expired` 추가 (백엔드 `admin.py` status 화이트리스트에도 추가).
- `DashboardTab`: 이탈 지표 카드 3종 — 만료 임박(D-3 이내), 만료 후 미재구독(경과일별),
  이번 달 재구독 전환율(만료→재승인 비율).
- 디자인: 앱 표준 다크 시스템(#0e0e11 카드, 헤어라인 보더, 카드 그리드, FA 아이콘)으로
  탭 전반 프레젠테이션 정리. 로직 변경 없는 표현 계층 개선.

## 5. 보안 점검

auth/admin 라우트 전수 점검 후 발견분 수정 + `test_security_regressions.py` 회귀 추가:

1. admin 엔드포인트 `@admin_required` 누락 여부 전수 확인
2. IDOR — 타 유저 id 로 접근 가능한 self-service 엔드포인트
3. rate limit 커버리지 — register / subscription/request (login 은 있음)
4. 토큰: 수명, `password_changed_at` 무효화 일관성
5. 게이트 정합성 — `_GATED_PREFIXES` 밖의 pro 데이터 라우트가 pro_required 를 빠뜨려
   expired 유저에게 새는 경로가 있는지
6. mass assignment / 입력 검증 (register, profile)

## 6. 검증·배포

- 회귀 테스트: 만료 스레드가 expired 로 만들고 suspended 를 만들지 않는지 /
  tier 보존 / 마이그레이션 선별 정확성(수동 정지 제외) / expired 로그인 성공 /
  재구독 신청→승인일+30d / admin subscriptions 4갈래 응답.
- 로컬: pytest + 프론트 빌드 + localhost 검증 → 커밋/푸시 →
  `npm run deploy`(CF Pages) → miniPC pull → Flask 활성화는 재부팅 경로 →
  프로덕션(bit-man.net, marketflow-api) 검증.

## 비범위

- Stripe 실결제 연동 변경 (placeholder 유지)
- AI Brain(aibain) 애드온 상태 머신 변경 — 기존 로직 보존
- 이메일 알림 (텔레그램/인앱만)
