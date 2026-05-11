# MarketFlow MiroFish MCP — Claude Desktop 통합 가이드

**최종 검증**: 2026-05-12
**MCP 패키지**: `mcp 1.27.1` (Anthropic 공식 SDK)
**서버 위치**: `mirofish_mcp_server.py` (project root)
**전송 방식**: stdio (Claude Desktop 호환), streamable-http (원격)

---

## 0. 개요

MarketFlow MiroFish 시스템의 핵심 기능을 **Claude Desktop / Cursor / Cline** 에서 직접 호출할 수 있는 MCP 서버입니다.

### 노출되는 도구 14개

| 카테고리 | 도구 | 기능 |
|---|---|---|
| **상태/메타** | `get_autonomous_status` | 자동화 컨트롤플레인 상태 |
| | `get_market_clock` | KST 시장 세션 + 스캐너 스케줄 |
| | `get_mcp_security_policy` | MCP 보안 정책 / allowlist |
| | `get_repository_state` | git branch / HEAD / dirty 상태 |
| **조회** | `list_recent_scanner_runs` | 최근 알파 스캐너 run 목록 |
| | `list_recent_workflows` | 최근 workflow run 목록 |
| | `list_safe_artifacts` | allowlist 산출물 목록 |
| | `read_safe_artifact` | allowlist 산출물 한 건 읽기 |
| **자동화 실행** | `run_candidate_detection_alert` | 신규 알파 후보 탐지 (선택 텔레그램) |
| | `run_autonomous_scan_analysis` | scan → GraphRAG → 학습 → 알림 |
| | `refresh_learning_feedback` | 룩어헤드 안전 outcome 재계산 |
| **전파/공유** | `send_latest_workflow_telegram` | 최신 workflow Top-N 텔레그램 |
| | `get_top3_summary` ⭐ | TOP 3 핵심 + 5인 페르소나 인용 |
| | `get_workflow_share_payload` ⭐ | 카카오톡 공유용 풍부한 페이로드 |

### 노출되는 리소스 7개

```
mirofish://autonomous/status      자동화 상태 (redacted)
mirofish://autonomous/security    보안 정책
mirofish://autonomous/learning    학습 피드백
mirofish://market/clock           KST 시장 세션
mirofish://scanner/latest         최신 스캐너 run
mirofish://workflows/latest       최신 workflow
mirofish://workflows/share        ⭐ 최신 workflow 카카오톡 공유 페이로드
```

---

## 1. 사전 준비

1. **Python 가상환경** — `.venv/Scripts/python.exe` (Windows) 또는 venv (macOS/Linux)
2. **의존성 설치** — `pip install -r requirements.txt` (mcp ≥ 1.23.0 포함)
3. **`.env` 파일** — `OPENAI_API_KEY` / `GEMINI_API_KEY` 등 설정
4. **MarketFlow 데이터** — `data/admin_mirofish/runs/` 와 `data/admin_mirofish/workflows/` 존재 (이미 운영 중)

검증:
```bash
cd C:\bitman_marketfloww
.venv\Scripts\python.exe mirofish_mcp_server.py --transport stdio
```
프롬프트가 빈 줄로 멈추면 정상 (stdio 대기 중).

---

## 2. Claude Desktop 등록

### macOS / Linux

`~/Library/Application Support/Claude/claude_desktop_config.json` (mac)
`~/.config/Claude/claude_desktop_config.json` (linux)

### Windows

`%APPDATA%\Claude\claude_desktop_config.json`

### 설정 내용

```json
{
  "mcpServers": {
    "marketflow-mirofish": {
      "command": "C:\\bitman_marketfloww\\.venv\\Scripts\\python.exe",
      "args": ["C:\\bitman_marketfloww\\mirofish_mcp_server.py", "--transport", "stdio"],
      "env": {
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
```

> macOS/Linux 인 경우 `command` 와 `args` 의 경로를 자기 환경에 맞게 수정.

저장 후 **Claude Desktop 재시작**.

---

## 3. 사용 예시 (Claude Desktop)

### 자연어 → MCP tool 자동 호출

```
사용자: "이번 주 MarketFlow TOP 3 알려줘"
  → Claude 가 자동으로 get_top3_summary() 호출
  → 응답:
     #1 한일단조 BUY 75%
     #2 대한전선 HOLD 70%
     #3 실리콘투 HOLD 70%

사용자: "한일단조 분석 카톡으로 보낼 정보 줘"
  → get_workflow_share_payload(rank=1) 호출
  → 박모멘텀(BUY 90%) 인용 + CIO reasoning + 리스크 시나리오 모두 포함

사용자: "지금 한국 장 열려 있어?"
  → get_market_clock() 호출
  → "KST 08:23, pre_open 상태 (09:00 정규장 시작 예정)"

사용자: "최근 스캐너 5개 run 보여줘"
  → list_recent_scanner_runs(limit=5) 호출

사용자: "scan-analyze 실행 dry-run 으로"
  → run_autonomous_scan_analysis(dry_run=true) 호출
```

---

## 4. 검증 — 직접 호출 (Python)

`scripts/mcp_smoke_test.py` 를 실행하면 14개 tool 중 5개를 자동 호출해 검증:

```bash
.venv\Scripts\python.exe scripts\mcp_smoke_test.py
```

기대 출력:
```
[1] initialize... server: MarketFlow MiroFish Autonomous MCP v1.27.1
[2] list_tools() 총 14 tools
[3] list_resources() 총 7 resources
[4] call_tool(get_market_clock) ✅
[5] call_tool(get_autonomous_status) ✅ mode=scanner_workflow_learning_telegram_control_plane
[7] call_tool(get_top3_summary) ✅ one_liner=#1 한일단조 BUY 75% / ...
[8] call_tool(get_workflow_share_payload rank=1) ✅ 박모멘텀(BUY 90%) 인용
[9] read_resource(mirofish://workflows/share) ✅
```

---

## 5. 원격 호스팅 (선택 사항)

stdio 외에 streamable-http transport 도 지원합니다 (여러 클라이언트 동시 접속 가능):

```bash
python mirofish_mcp_server.py --transport streamable-http --host 0.0.0.0 --port 8766 --path /mcp
```

Cloudflared tunnel 로 https 노출하면 Cursor/Cline/Goose 같은 다른 MCP 클라이언트도 원격 접속 가능.

---

## 6. 보안 / 안전 장치

- **읽기 전용 도구** (get_*, list_*, read_*) — confirmation 불필요
- **실행 도구** (run_*, send_*) — `dry_run=true` 기본값 + `confirmation` 문구 / `api_key` 필요
- **safe artifact allowlist** — `read_safe_artifact` 는 허용된 경로만 접근
- **Telegram 전송** — `confirmation=CONFIRM_SEND_PHRASE` + api_key 검증 통과해야 실제 전송

---

## 7. 자주 사용하는 시나리오

| 시나리오 | Claude 자연어 | MCP 호출 |
|---|---|---|
| TOP 3 즉시 확인 | "이번 TOP 3 알려줘" | `get_top3_summary` |
| 카카오톡 공유 카드 | "1등 종목 카톡 공유 정보 줘" | `get_workflow_share_payload(rank=1)` |
| 시장 시간 확인 | "장 열려 있어?" | `get_market_clock` |
| 신규 후보 자동 탐지 | "신규 알파 후보 dry-run 으로 점검" | `run_candidate_detection_alert(dry_run=true)` |
| 산출물 직접 읽기 | "최신 workflow JSON 보여줘" | `read_safe_artifact('data/admin_mirofish/workflows/<id>/workflow.json')` |
| 학습 피드백 갱신 | "outcome 재계산해" | `refresh_learning_feedback` |

---

## 8. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| Claude Desktop 에 mirofish 미노출 | config 경로 / JSON syntax | claude_desktop_config.json 정확한 위치 + JSON validator |
| `mcp package is not installed` | venv 활성화 안됨 | `command` 경로를 `.venv/Scripts/python.exe` 절대 경로로 |
| tool 호출 시 encoding 에러 | UTF-8 미설정 | `env`에 `PYTHONIOENCODING=utf-8` 추가 (위 예시에 이미 포함) |
| `workflow not found` | data/admin_mirofish/workflows/ 비어 있음 | MarketFlow 에서 scan-analyze 한 번 실행 후 재시도 |
| stdio 서버 행 (hang) | 정상 — stdin 대기 중 | Ctrl+C 로 종료, Claude Desktop 이 자동 spawn 함 |

---

## 9. 다음 단계 후보

| 항목 | 상태 |
|---|---|
| `@marketflow/mirofish-mcp` npm 패키지 (TypeScript wrapper) | 미시작 — Cursor / Windsurf 통합 시 필요 |
| Anthropic MCP Registry 등재 | 미시작 — 글로벌 노출 / 마케팅 |
| streamable-http 원격 호스팅 (`mcp.bit-man.net`) | 미시작 — Cloudflared 터널 활용 |
| HMAC API key 기반 multi-user | 미시작 — PRO+MCP 구독 플랜 필수 |
| MCP tool 호출 audit log | 미시작 — `data/admin_mirofish/audit/` |

---

**문서**:
- 본 가이드: `docs/mirofish_mcp_setup_guide.md`
- 검증 스크립트: `scripts/mcp_smoke_test.py`
- MCP 서버 코드: `app/services/mirofish/mcp_server.py`
- Runner: `mirofish_mcp_server.py`
