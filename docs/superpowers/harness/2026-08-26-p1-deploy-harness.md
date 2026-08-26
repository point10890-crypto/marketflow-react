# P1 배포 하네스 — 커밋/푸시/배포/miniPC 최종검증 (2026-08-26)

대상: 마스터 플랜 P1 (정밀도 측정 기반 복구) — 본PC 구현 완료분의 운영 반영
프로토콜: Route→Scope→Plan→Implement→Verify→Repair. 게이트 실패 시 다음 단계 진입 금지, 롤백 계획 외 즉흥 금지.

## 절대 규칙 (이번 런)

1. **커밋 파일 화이트리스트 외 스테이징 금지. `git add -A`/`git add .` 절대 금지** (루트에 untracked `node_modules/`, 데이터 백업, `.codex/` 존재).
2. **8080(JUST BUY) 불가침. 5001 미확인 프로세스 무접촉. Flask SSH 재시작 금지** — 활성화는 재부팅만 (phantom socket boot-loop 이력).
3. FE 배포 없음 (P1은 백엔드 전용 — `npm run deploy` 호출 금지).
4. 비밀값(.env·토큰) 출력·로그·문서 기재 금지. 관리자 토큰은 miniPC 로컬 검증에만 쓰고 폐기.
5. 각 단계는 검증 게이트 통과 후에만 다음으로. 게이트 실패 → 정지·보고 (Repair 는 롤백 계획 범위 내에서만).
6. 운영 데이터 원장 무변경 — 검증은 읽기전용 호출·신규 리포트 생성만.

## 커밋 파일 화이트리스트

- `app/services/mirofish/costs.py` (신규) · `detection_lab.py` · `paper_positions.py` · `agent_actions.py` · `alpha_brain_agent.py` · `intelligence/top3_metrics.py`
- `scripts/detection_lab_run.py`
- `tests/test_p1_precision_measurement.py` (신규) · `tests/test_mirofish_alpha_brain_agent.py`
- `docs/superpowers/specs/2026-08-24-{analysis-core-redesign,alphaclaw-integration-review,goal-definition-master-plan,omnisource-sensor-design}.md` · `2026-08-26-endpoint-attach-design.md` · 본 하네스 문서

제외(명시): `frontend-react/package-lock.json`(로컬 변경 폐기 — miniPC c431e66 이 정본), `data/*`, `.codex/`, `node_modules/`, `tests/` 외 기타 untracked.

## 단계·게이트

| # | 단계 | 게이트 (통과 기준) | 롤백 |
|---|---|---|---|
| G0 | 본PC 프리플라이트 | P1 테스트 14 + 영향권 회귀 전부 green, py_compile OK | — |
| G1 | miniPC 미푸시 6커밋 push | `git rev-list origin/main..HEAD` = 0 (miniPC) | 실패 시 bundle+scp 우회 경로 |
| G2 | 본PC 커밋·rebase·push | push 후 origin/main = 본PC HEAD, 화이트리스트 외 파일 0 | `git reset --hard origin/main` 전 상태 태그 |
| G3 | miniPC pull | miniPC HEAD = origin/main, 백엔드 파일 diff 0 | `git reset --hard <이전 HEAD>` |
| G4 | 재부팅 활성화 | 재부팅 후 healthz 200 + 5003/8765 LISTENING + 태스크 기동 | 워치독 자동복구 대기 → 실패 시 보고 |
| G5 | 기능 검증 | ①agent 사이클 저널에 refresh_intelligence applied ②top3_metrics.json mtime 갱신+실값 ③실행 중 Flask의 paper/overview 에 net_* ④detection_lab 신규 리포트에 net 네이티브 | 코드 revert 커밋 → pull → 재부팅 |
| G6 | 종결 | 회귀(healthz·aibain 401 게이트·claw overview 401) + 문서·메모리 갱신 | — |

## 검증 방법 각주

- G5-①: 23:30 night 사이클 자연 발화 대기(가능 시) 또는 수동 1회 사이클 — dry_run 상태 그대로, LLM 실패해도 maintenance 는 독립 실행됨.
- G5-③: miniPC 로컬에서 관리자 토큰 생성(출력 금지) → `127.0.0.1:5003` 직접 호출 — 실행 중 프로세스가 새 코드임을 증명.
- G5-④: `scripts/detection_lab_run.py` 재실행 → 리포트 아카이브 → R0′ 문서 수치 갱신.
