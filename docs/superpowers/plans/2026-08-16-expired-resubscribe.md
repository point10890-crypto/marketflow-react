# 만료 회원 재구독 파이프라인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 구독 만료를 "계정 정지"가 아닌 "재구독 유도" 상태로 통일하고, 굳어버린 만료 회원을 복구하며, 관리자 페이지에서 만료·재구독을 한눈에 관리한다.

**Architecture:** 만료 스윕 로직을 `app/services/pro_expiry.py` 로 추출해 테스트 가능하게 만들고 결과를 `status='expired'`(tier 보존)로 통일. 프론트는 이미 있는 expired 리다이렉트 인프라를 재사용하고, 관리자 API 에 `expired_members`/이탈 지표 갈래를 추가한 뒤 탭 UI 를 확장한다.

**Tech Stack:** Flask + SQLAlchemy + pytest / React(Vite) + TypeScript / 배포: CF Pages + miniPC.

**Spec:** `docs/superpowers/specs/2026-08-16-expired-resubscribe-design.md`

---

### Task 1: 만료 스윕 추출 + suspended→expired 통일

**Files:**
- Create: `app/services/pro_expiry.py`
- Modify: `app/__init__.py` (`_alert`/`_expiry_loop` 본문을 서비스 호출로 교체, 만료 문구에 재구독 링크)
- Modify: `app/routes/stripe_routes.py:116` (`suspended` → `expired`)
- Test: `tests/test_expiry_pipeline.py`

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_expiry_pipeline.py`

```python
# -*- coding: utf-8 -*-
"""만료 스윕 회귀 테스트 — 만료는 '정지'가 아니라 '재구독 유도' 상태다.

2026-08-16 이전: _expiry_loop 가 만료 Pro 를 tier=None + status='suspended' 로
만들어 로그인 자체가 403 으로 막히고(수동 정지와 동일 취급) 재구독 경로가
차단됐다. 게이트 경로(status='expired', tier 보존)와 결과를 통일한다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import create_app
from app.models import db
from app.models.user import User
from app.services.pro_expiry import run_expiry_sweep


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f"sqlite:///{tmp_path/'t.db'}",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()


def _mk_user(email, **kw):
    u = User(email=email, name=email.split('@')[0], status='approved', tier='pro', role='user')
    u.set_password('pw12345678')
    for k, v in kw.items():
        setattr(u, k, v)
    db.session.add(u)
    db.session.commit()
    return u


def test_expired_pro_becomes_expired_not_suspended(app):
    with app.app_context():
        past = datetime.now(timezone.utc) - timedelta(days=2)
        u = _mk_user('gone@example.com', pro_expires_at=past)
        run_expiry_sweep(notify=lambda *a, **k: None)
        db.session.refresh(u)
        assert u.status == 'expired'          # suspended 가 아니다
        assert u.tier == 'pro'                # 플랜 이력 보존
        assert u.pro_expires_at is not None   # 만료일 보존
        assert u.pro_expiry_alert_stage == 'expired'


def test_active_pro_untouched(app):
    with app.app_context():
        future = datetime.now(timezone.utc) + timedelta(days=10)
        u = _mk_user('alive@example.com', pro_expires_at=future)
        run_expiry_sweep(notify=lambda *a, **k: None)
        db.session.refresh(u)
        assert u.status == 'approved' and u.tier == 'pro'


def test_paused_pro_skipped(app):
    with app.app_context():
        past = datetime.now(timezone.utc) - timedelta(days=2)
        u = _mk_user('paused@example.com', pro_expires_at=past,
                     pro_paused_at=datetime.now(timezone.utc))
        run_expiry_sweep(notify=lambda *a, **k: None)
        db.session.refresh(u)
        assert u.status == 'approved'


def test_d3_d1_stages_advance_once(app):
    with app.app_context():
        soon = datetime.now(timezone.utc) + timedelta(hours=12)
        u = _mk_user('d1@example.com', pro_expires_at=soon)
        calls = []
        run_expiry_sweep(notify=lambda user, stage, when: calls.append(stage))
        run_expiry_sweep(notify=lambda user, stage, when: calls.append(stage))
        db.session.refresh(u)
        assert u.pro_expiry_alert_stage == 'd1'
        assert calls == ['d1']  # 두 번째 스윕은 중복 알림 없음


def test_expired_alert_message_contains_resubscribe_link(app):
    from app.services.pro_expiry import build_expiry_alert_message
    msg = build_expiry_alert_message(
        name='홍길동', email='u@example.com', user_id=7,
        stage='expired', when='2026-08-16T00:00:00',
    )
    assert 'plan-select?resubscribe=1' in msg
    assert '정지' not in msg
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_expiry_pipeline.py -q` → `ModuleNotFoundError: app.services.pro_expiry`

- [ ] **Step 3: `app/services/pro_expiry.py` 구현** — `app/__init__.py` 의 `_expiry_loop` 본문(만료/D-1/D-3 세 쿼리)을 이 모듈의 `run_expiry_sweep(notify)` 로 이식. 만료 분기만 다음으로 교체:

```python
for user in expired:
    when = user.pro_expires_at.isoformat() if user.pro_expires_at else '?'
    if user.pro_expiry_alert_stage != 'expired':
        notify(user, 'expired', when)
    # '정지'가 아니라 '만료' — tier/만료일 보존, 재구독 플로우가 이 정보를 쓴다.
    user.status = 'expired'
    user.pro_expiry_alert_stage = 'expired'
db.session.commit()
```

`build_expiry_alert_message(...)` 는 기존 `_alert` 문구를 옮기되 expired 단계에
`🔁 재구독: https://bit-man.net/plan-select?resubscribe=1` 줄 추가.

- [ ] **Step 4: `app/__init__.py` 스레드를 서비스 호출로 교체** — `_expiry_loop` 내부를 `from app.services.pro_expiry import run_expiry_sweep, build_expiry_alert_message` + `run_expiry_sweep(notify=_alert)` 호출로, `_alert` 는 메시지 빌더 사용.

- [ ] **Step 5: `stripe_routes.py` 통일** — `user.status = 'suspended'` → `user.status = 'expired'` (주석: 만료는 재구독 유도 상태).

- [ ] **Step 6: 전체 테스트** — `pytest tests/test_expiry_pipeline.py tests/test_auth_subscription_workflow.py tests/test_security_regressions.py -q` → PASS (기존 테스트 중 suspended 를 기대하는 것이 있으면 스펙 변경에 맞춰 수정).

- [ ] **Step 7: Commit** — `fix(auth): expire, don't suspend — unify expiry pipeline for resubscribe`

---

### Task 2: 소급 복구 스크립트

**Files:**
- Create: `scripts/restore_expired_members.py`
- Test: `tests/test_restore_expired_members.py`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# -*- coding: utf-8 -*-
"""suspended 로 굳은 '만료' 회원 복구 선별 테스트.

기준: status='suspended' AND pro_expiry_alert_stage='expired'
      AND 관리자 set_status→suspended audit 기록 없음.
관리자가 수동 정지한 회원은 절대 건드리지 않는다.
"""
from datetime import datetime, timezone

import pytest

from app import create_app
from app.models import db
from app.models.user import User, AdminAuditLog, SubscriptionRequest
from scripts.restore_expired_members import find_restorable, restore


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f"sqlite:///{tmp_path/'t.db'}",
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()


def _mk(email, status, stage=None, tier=None):
    u = User(email=email, name=email.split('@')[0], status=status,
             tier=tier, role='user', pro_expiry_alert_stage=stage)
    u.set_password('pw12345678')
    db.session.add(u)
    db.session.commit()
    return u


def test_selects_only_expiry_suspended(app):
    with app.app_context():
        loop_victim = _mk('victim@example.com', 'suspended', stage='expired')
        manual = _mk('manual@example.com', 'suspended', stage='expired')
        db.session.add(AdminAuditLog(admin_id=1, target_user_id=manual.id,
                                     action='set_status',
                                     after='{"status": "suspended"}'))
        normal = _mk('ok@example.com', 'approved', tier='pro')
        db.session.commit()

        ids = {u.id for u in find_restorable()}
        assert loop_victim.id in ids
        assert manual.id not in ids
        assert normal.id not in ids


def test_restore_sets_expired_and_recovers_tier(app):
    with app.app_context():
        u = _mk('victim2@example.com', 'suspended', stage='expired')
        db.session.add(SubscriptionRequest(user_id=u.id, from_tier='none',
                                           to_tier='premium', status='approved'))
        db.session.commit()
        restore([u], apply=True)
        db.session.refresh(u)
        assert u.status == 'expired'
        assert u.tier == 'premium'          # 마지막 승인 요청에서 복원
        assert u.pro_expires_at is not None  # is_pro_expired 판정 가능


def test_dry_run_changes_nothing(app):
    with app.app_context():
        u = _mk('dry@example.com', 'suspended', stage='expired')
        restore([u], apply=False)
        db.session.refresh(u)
        assert u.status == 'suspended'
```

- [ ] **Step 2: 실패 확인** — `pytest tests/test_restore_expired_members.py -q` → import error

- [ ] **Step 3: 스크립트 구현** — `find_restorable()` (위 기준 쿼리, audit 은 `AdminAuditLog.action=='set_status'` + after 에 `"suspended"` 포함 여부로 제외), `restore(users, apply)` (tier 복원 우선순위: 마지막 approved SubscriptionRequest.to_tier → audit set_tier before → 'pro'; `pro_expires_at = now - 1s`; `_record_audit` 대신 AdminAuditLog 직접 기록 action='restore_expired'), `main()` 은 `--apply` 플래그 + 대상 리포트 출력.

- [ ] **Step 4: 통과 확인 + Commit** — `feat(auth): one-shot restore of expiry-suspended members`

---

### Task 3: 관리자 API — 만료 갈래 + 이탈 지표 + expired 필터

**Files:**
- Modify: `app/routes/admin.py` (`list_subscriptions` 확장, `list_users` status 화이트리스트, `admin_stats` 지표)
- Test: `tests/test_admin_expired_members.py`

- [ ] **Step 1: 실패하는 테스트 작성** — admin 토큰으로:
  - `GET /api/admin/subscriptions` 응답에 `expired_members` 배열 (만료 유저: id/email/name/tier/pro_expires_at/days_since_expiry/last_login_at 포함, 재구독 pending 요청 있는 유저는 제외 — requests 갈래에 이미 있음)
  - `GET /api/admin/users?status=expired` 가 expired 유저만 반환 (기존엔 400 또는 무시)
  - `GET /api/admin/stats` 에 `churn` 객체: `{expiring_d3, expired_unrenewed, resubscribed_this_month}`

```python
def test_subscriptions_exposes_expired_members(admin_client):
    r = admin_client.get('/api/admin/subscriptions')
    body = r.get_json()
    assert 'expired_members' in body
    emails = [m['email'] for m in body['expired_members']]
    assert 'lapsed@example.com' in emails
    m = next(x for x in body['expired_members'] if x['email'] == 'lapsed@example.com')
    assert m['tier'] == 'pro' and m['days_since_expiry'] >= 1
```

(fixture 는 `tests/test_auth_subscription_workflow.py` 의 admin_client 패턴 재사용)

- [ ] **Step 2: 실패 확인 → 구현** — `list_subscriptions` 에 `User.status=='expired'` 조회 추가(만료일 내림차순, pending 재구독 요청 보유자 제외), `admin.py:327` status 화이트리스트에 `'expired'` 추가, stats 에 churn 계산(D-3: `pro_expires_at` 3일 이내 활성, unrenewed: status='expired', resubscribed: 이번 달 approved 요청 중 from_tier!=none 또는 사용자 status 가 expired 였던 건 — 근사치로 `request_type` 활용).

- [ ] **Step 3: 통과 + Commit** — `feat(admin): surface expired members and churn metrics`

---

### Task 4: 보안 점검 + 수정

**Files:**
- Modify: 발견분에 따라 `app/routes/auth.py`, `app/routes/admin.py`, `app/__init__.py`
- Test: `tests/test_security_regressions.py` (추가)

- [ ] **Step 1: 점검 스크립트 실행** — admin 블루프린트 전 라우트의 데코레이터 목록화:

```bash
"$PYTHON" - << 'EOF'
from app import create_app
app = create_app()
import inspect
for rule in app.url_map.iter_rules():
    if not rule.rule.startswith('/api/admin'): continue
    fn = app.view_functions[rule.endpoint]
    src = inspect.getsource(fn)
    guarded = 'admin_required' in src or 'admin_or_aibain_required' in src
    if not guarded:
        print('UNGUARDED:', rule.rule, rule.endpoint)
EOF
```

- [ ] **Step 2: 체크리스트 점검** (각 항목 결과를 커밋 메시지에 기록):
  1. `@admin_required` 누락 라우트 → 발견 시 데코레이터 추가
  2. self-service 라우트(`/profile`, `/change-password`, `/subscription/request`)가 `request.current_user` 외의 user_id 입력을 받는지 (IDOR)
  3. `register` / `subscription/request` rate limit — login 의 `_check_login_rate_limit` 패턴 재사용해 register 에 IP 기준 제한 추가 (부재 확인 시)
  4. 토큰 검증이 `password_changed_at` 을 확인하는지 (b16ed74 에서 구현 — 회귀 확인만)
  5. `_GATED_PREFIXES` 밖의 Pro 데이터 blueprint 가 있는지: `app/routes/__init__.py` 의 등록 prefix 전수 대조, pro 데이터인데 게이트/`pro_required` 둘 다 없는 라우트 목록화 → 발견 시 `pro_required` 부착
  6. `register` 입력 검증: email 형식/길이, name 길이, password 최소 길이 (기존 코드 확인, 미비 시 보강)
- [ ] **Step 3: 발견분 수정 + 각 항목 회귀 테스트를 `test_security_regressions.py` 에 추가** (예: expired 유저가 게이트 밖 라우트로 Pro 데이터 접근 시 403)
- [ ] **Step 4: 전체 테스트 + Commit** — `fix(security): audit findings — <요약>`

---

### Task 5: 프론트 — 재구독 UX (PlanSelectPage)

**Files:**
- Modify: `frontend-react/src/pages/auth/PlanSelectPage.tsx`

- [ ] **Step 1: resubscribe 모드 강화** — `isResubscribe` 일 때:
  - 상단 배너: `구독이 만료되었습니다 — 이어서 이용하시려면 플랜을 선택하세요. 승인 즉시 30일이 새로 시작됩니다.`
  - `user.tier` 와 일치하는 플랜 카드에 `이전 플랜` 배지 + 강조 보더 + 기본 포커스
  - CTA 문구: `다시 시작하기`
- [ ] **Step 2: 빌드 확인** — `cd frontend-react && npx tsc --noEmit && npm run build`
- [ ] **Step 3: Commit** — `feat(auth-ui): resubscribe-aware plan selection`

---

### Task 6: 프론트 — SubscriptionsTab 만료 섹션 + 타입

**Files:**
- Modify: `frontend-react/src/pages/admin/tabs/SubscriptionsTab.tsx`
- Modify: `frontend-react/src/lib/api.ts` (`AdminSubscriptions` 인터페이스에 `expired_members` 추가)

- [ ] **Step 1: api.ts 타입 추가**

```typescript
export interface ExpiredMember {
    id: number; email: string; name: string;
    tier: string | null; pro_expires_at: string | null;
    days_since_expiry: number; last_login_at: string | null;
}
// 기존 subscriptions 응답 타입에 expired_members: ExpiredMember[] 추가
```

- [ ] **Step 2: 섹션 추가** — 순서 고정: ①대기 중 ②**만료 · 재구독 대기** ③가입만 완료 ④처리 이력. 만료 섹션 행: 이름/이메일/이전 플랜/만료 N일 경과/최근 로그인 + 액션 버튼 `Pro 재부여`(setUserTier 'pro'), `연장 +30d`(extendPro). 기존 섹션 컴포넌트 패턴 그대로.
- [ ] **Step 3: 빌드 + Commit** — `feat(admin-ui): expired members section in subscriptions tab`

---

### Task 7: 프론트 — UsersTab 필터 + DashboardTab 이탈 지표

**Files:**
- Modify: `frontend-react/src/pages/admin/tabs/UsersTab.tsx` (status 필터 옵션에 `expired` 추가)
- Modify: `frontend-react/src/pages/admin/tabs/DashboardTab.tsx` (churn 카드 3종)

- [ ] **Step 1: UsersTab 필터에 `expired`** 추가 (기존 필터 셀렉트 옵션 + 뱃지 색: amber 계열)
- [ ] **Step 2: DashboardTab 카드 3종** — stats.churn 사용: `만료 임박 D-3`, `만료 후 미재구독`, `이번 달 재구독`. 기존 카드 그리드 패턴.
- [ ] **Step 3: 빌드 + Commit** — `feat(admin-ui): churn metrics and expired filter`

---

### Task 8: 프론트 — 관리자 탭 디자인 정리

**Files:**
- Modify: `frontend-react/src/pages/admin/tabs/*.tsx`, `frontend-react/src/pages/admin/AdminPage.tsx`

- [ ] **Step 1: 표준 다크 시스템 적용** — 로직 무변경 프레젠테이션 정리:
  - 카드: `bg-[#0e0e11]` + 헤어라인 보더(`border-white/[0.06]`) + rounded-xl + 코너 글로우 포인트
  - 섹션 헤더: FA 아이콘 + 좌측 액센트 바, 상태 뱃지 팔레트 통일(pending=sky, approved=emerald, expired=amber, suspended=rose)
  - 테이블 행 hover, 모바일 카드 폴백(기존 패턴 유지)
  - UsersTab(944줄)의 인라인 스타일 중복은 공통 뱃지/버튼 헬퍼로 축소 (파일 분리는 비범위)
- [ ] **Step 2: 빌드 + 로컬 브라우저 확인** (`npm run dev` → /admin 각 탭 스크린샷)
- [ ] **Step 3: Commit** — `style(admin-ui): unify admin tabs with app dark system`

---

### Task 9: 통합 검증 + 배포

- [ ] **Step 1: 백엔드 전체 테스트** — `pytest tests/ -q -x -k "auth or admin or expiry or security or restore"` → PASS
- [ ] **Step 2: 프론트 빌드** — `npx tsc --noEmit && npm run build` → PASS
- [ ] **Step 3: 로컬 E2E** — 로컬 Flask 기동, 테스트 유저를 만료시키고: 로그인 → `/plan-select?resubscribe=1` 리다이렉트 → 재구독 신청 → admin 승인 → 대시보드 접근 복구 확인
- [ ] **Step 4: push + CF Pages 배포** — `git push origin main` → `cd frontend-react && npm run deploy` → bit-man.net 번들 해시 확인
- [ ] **Step 5: miniPC 동기화** — ssh pull. Flask 코드 활성화는 재부팅 경로(사용자 확인 후).
- [ ] **Step 6: 프로덕션에서 소급 복구 실행** — miniPC 에서 `restore_expired_members.py` dry-run → 리포트 확인 → `--apply` → 결과 보고
- [ ] **Step 7: 프로덕션 검증** — bit-man.net 200, marketflow-api healthz 200, admin subscriptions 응답에 expired_members 확인
