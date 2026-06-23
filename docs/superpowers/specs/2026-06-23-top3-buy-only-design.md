# BUY-only TOP3 검출 — 설계 스펙

- **날짜**: 2026-06-23
- **상태**: 승인됨 (brainstorming)
- **요청**: "CIO 판정이 매수(BUY)인 종목만 TOP3에 올리기." 매수 종목이 없으면 빈 결과 + "오늘 매수 판정 종목 없음".
- **관련**: [[project_top3_metrics]], [[project_learning_activation]]

## 1. 배경 / 문제
TOP3는 `final_score` 순 상단을 그대로 노출(`workflow.py:714-715` `top3 = ranked[:top_n]`)하므로, 분석 후보가 적은 날 **CIO 판정이 매도(SELL)/보유(HOLD)인 종목도 TOP3에 검출**된다(예: 남화토건 매도 78% #2). 점수에 `action_bonus={BUY:+20,HOLD:+4,SELL:-30}`가 있으나 하드 필터가 아니라 보장되지 않는다.

요구: **검출(TOP3) = CIO verdict.action == 'BUY' 인 종목만.**

## 2. 비범위 (YAGNI)
- 점수 공식(`_score_breakdown`)·action_bonus 변경 — 하지 않음(필터만 추가)
- 스캐너 action 임계(BUY_CANDIDATE) 변경 — 하지 않음
- 신규 UI — 기존 소비처가 단일 진실원천(workflow.top3)을 그대로 사용

## 3. 핵심 변경 (단일 지점, `app/services/mirofish/workflow.py`)
`_complete_workflow`의 선별부:
```python
ranked = sorted(results, key=lambda item: item.get('final_score', -999), reverse=True)
require_buy = _require_buy(workflow)
eligible = [r for r in ranked if _verdict_is_buy(r)] if require_buy else ranked
top3 = eligible[:top_n]
```
헬퍼:
```python
def _verdict_is_buy(run):
    return str((run.get('verdict') or {}).get('action') or '').upper() == 'BUY'
```
- **`analysis_runs`(ranked)는 전체 분석 보존** — 투명성/evidence/outcome 평가용. `top3`만 BUY 한정.
- 모든 소비처(텔레그램·share·aibain 대시보드·outcome)가 `workflow.top3`를 읽으므로 자동 일관.

## 4. 설정 (가역적, 기본 ON)
- `DEFAULT_REQUIRE_BUY = True`.
- `_require_buy(workflow)` 우선순위: payload→filters에 저장된 `require_buy` > env `MIROFISH_TOP3_REQUIRE_BUY`(`'false'`면 끔) > 기본 True.
- 워크플로우 생성 시 `filters['require_buy']`에 기록(`start_workflow_from_scanner_events` payload `require_buy` 수용).

## 5. 매수 0개 처리
- `top3 = []`. `_workflow_decision_summary`(또는 summary)에 메타 추가:
  `{'require_buy': True, 'analyzed_count': len(ranked), 'buy_count': len([...BUY...])}`.
- `build_workflow_top3_telegram_message` / `_build_scanner...`의 빈 분기:
  - `require_buy` & ranked 비어있지 않음 & top3 비어있음 → **"오늘 매수 판정 종목 없음 (분석 N개)"**.
  - 그 외(분석 자체 0) → 기존 "후보 없음".
- 전송 게이팅(`should_send_workflow_top3`)은 빈 top3를 기존대로 걸러 매수 0개면 알림 미발송(스팸 방지).

## 6. 영향 점검
- `outcome_tracker.refresh_workflow_outcomes`/`summarize_outcomes`가 빈/축소 top3에서 안전(매수만 평가 → top3_metrics 더 정확, 긍정적).
- `_workflow_quality_summary.buy_count_top3` == len(top3) 가 됨(정상).

## 7. 테스트 (TDD)
`tests/test_admin_mirofish_workflow.py`(또는 신규 `test_mirofish_workflow_buy_filter.py`):
- 혼합 판정 results → top3에 BUY만, final_score 내림차순.
- 매수 0개 → top3 빈 배열, summary `buy_count==0`, `analyzed_count` 보존, analysis_runs 전체 유지.
- `require_buy=False` → 기존 동작(전체 top_n).
- 텔레그램: 매수 0개(분석>0) → "오늘 매수 판정 종목 없음" 문구.

## 8. 검증
- 단위 + 전체 mirofish 회귀 0 + CLAUDE.md Skill 4.
- miniPC 실데이터: 새 워크플로우 top3 전부 `verdict.action=='BUY'` 실증; 매수 0개 케이스 메시지 확인.
- diff 가드: `_score_breakdown`/action_bonus 미변경.

## 9. 롤아웃 / 안전
- 머지→푸시→miniPC pull→스케줄러 재기동.
- 되돌림: env `MIROFISH_TOP3_REQUIRE_BUY=false` 즉시 원복.
