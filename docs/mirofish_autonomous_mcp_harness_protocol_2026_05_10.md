# MiroFish Autonomous MCP Harness Protocol

작성일: 2026-05-10
목표: 자동 종목검출, 자동 분석, 자동학습 피드백, 자동 Telegram 발송을 MCP control-plane으로 구현한다.

## 1. 팀 구성

| 팀 | 책임 | 산출물 |
|---|---|---|
| Team A: MCP/Protocol | FastMCP 서버, tool/resource 명세, Inspector 검증 | `mcp_server.py`, entrypoint |
| Team B: Alpha Automation | scanner -> workflow -> outcome loop 연결 | autonomous service functions |
| Team C: Learning/Risk | look-ahead 없는 outcome refresh, learning feedback artifact | `learning_feedback.json` |
| Team D: Security/Ops | mutation guard, shared secret, dry-run, audit log, Telegram safety | audit/redaction/confirmation |
| Team E: QA/Release | focused tests, compile, build, commit, deploy verification | test logs, release notes |

## 2. 작업 원칙

1. Alpha objective가 최우선이다.
   - MCP는 장식용 integration이 아니라 MiroFish alpha 탐지 루프의 control-plane이다.
   - 모든 최종 결과는 exact symbol/name/market을 포함해야 한다.

2. 기존 엔진을 재사용한다.
   - 자동 종목검출: `app/services/mirofish/alpha_scanner.py`
   - 자동 분석: `app/services/mirofish/workflow.py`
   - 자동학습 피드백: `app/services/mirofish/outcome_tracker.py`
   - Telegram 발송: 기존 scheduler Telegram sender를 주입형으로 호출

3. Mutation은 기본 차단한다.
   - `dry_run=True`가 기본이다.
   - Telegram 발송, event-state commit, schedule/write 류는 `MIROFISH_MCP_ALLOW_MUTATION=true`가 필요하다.
   - shared secret이 설정되어 있으면 tool payload의 `api_key`가 일치해야 한다.
   - Telegram 발송은 확인 문구 `SEND_MIROFISH_AUTONOMOUS_ALERT` 없이는 실행하지 않는다.

4. 보안 정보는 절대 노출하지 않는다.
   - `.env`, Telegram token, KIS secret, Cloudflare credential, API key는 결과와 audit log에서 redaction한다.
   - audit log는 payload/result의 요약과 상태만 남긴다.

5. 긴 작업은 job/result 패턴을 따른다.
   - MCP tool은 workflow id와 resource link를 반환한다.
   - full sync 분석은 명시적으로 요청할 때만 수행한다.

## 3. 구현 범위

### Phase 1: 이번 작업

- Autonomous MCP service module 추가
- FastMCP server entrypoint 추가
- MCP tools:
  - `get_autonomous_status`
  - `run_autonomous_scan_analysis`
  - `refresh_learning_feedback`
  - `send_latest_workflow_telegram`
  - `list_recent_scanner_runs`
  - `list_recent_workflows`
- MCP resources:
  - `mirofish://autonomous/status`
  - `mirofish://autonomous/learning`
  - `mirofish://scanner/latest`
  - `mirofish://workflows/latest`
- Security:
  - mutation guard
  - shared secret check
  - Telegram confirmation phrase
  - redacted audit log

### Phase 2: 후속 작업

- 사용자별 API key/quota DB
- remote OAuth 2.1 resource server
- 사용자별 schedules/webhooks
- paid tier quota enforcement
- MCP Inspector CI smoke script

## 4. 검증 루프

반복 순서:

```text
scope -> edit -> focused tests -> fix -> compile -> broader tests -> build -> commit -> deploy -> health check
```

중단 조건:

- 외부 secret/credential 부재
- production host 접근 불가
- 공식 API/SDK 장애
- 사용자가 중지 요청

그 외 실패는 에러 출력을 근거로 수정하고 다시 실행한다.

## 5. 최소 성공 기준

- `pytest tests/test_mirofish_autonomous_mcp.py -q` 통과
- 기존 MiroFish scanner/workflow focused tests 통과
- `python -m compileall app/services/mirofish/autonomous_mcp.py app/services/mirofish/mcp_server.py mirofish_mcp_server.py` 통과
- frontend 변경이 있으면 `npm run build` 통과
- commit은 의도한 파일만 stage
- deploy 후 `/healthz`와 `/api/health` 확인
