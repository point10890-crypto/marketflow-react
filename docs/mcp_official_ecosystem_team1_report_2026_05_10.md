# MCP 공식 생태계와 서버 구현 패턴 조사 보고서

작성일: 2026-05-10
역할: 딥리서치 팀 1
범위: MCP 공식 스펙, Python/TypeScript SDK, 공식/준공식 서버 예제, 인증/툴/리소스 설계 패턴
제외: 금융 데이터 공급원, 알파 팩터, 개별 시장 데이터 API

## 1. Executive Summary

MarketFlow/MiroFish에 붙일 MCP endpoint는 **Python SDK의 `FastMCP` 기반 Streamable HTTP sidecar**가 1순위다.

- MarketFlow의 운영 백엔드는 Flask지만, 공식 Python SDK의 HTTP 서버 패턴은 ASGI/Starlette 중심이다. Flask 라우트에 직접 끼우기보다 별도 프로세스 `mirofish_mcp_server.py`를 두는 편이 안전하다.
- 최초 버전은 read-only로 시작한다. MiroFish run artifact는 `resources`, 조회/랭킹/검증 함수는 `tools`, 반복 워크플로 템플릿은 선택적으로 `prompts`에 둔다.
- 로컬 endpoint 후보는 `http://127.0.0.1:8765/mcp` 같은 별도 포트를 권장한다. Flask `5001`, Vite `5173`, 금지된 `8080`과 충돌시키지 않는다.
- 운영 노출 시 Streamable HTTP + OAuth 2.1 resource server 패턴을 따라야 한다. `MCP-Session-Id`는 세션 식별용이지 인증 수단이 아니다.
- 검증은 `MCP Inspector`로 `tools/list`, `resources/list`, `resources/read`, `tools/call`, 오류 케이스를 smoke test한다.

## 2. 공식 기준 링크

| 항목 | 링크 | MarketFlow 적용 포인트 | 주의점 |
|---|---|---|---|
| MCP 최신 스펙 | [Specification latest](https://modelcontextprotocol.io/specification/latest) | JSON-RPC 2.0, host/client/server, resources/tools/prompts 기준선 | 조사 시점 latest는 `2025-11-25`; 구현 시 프로토콜 버전 고정 |
| Architecture | [Architecture](https://modelcontextprotocol.io/specification/2025-11-25/architecture) | 서버는 집중된 capability를 독립 제공 | MCP 서버가 전체 대화나 다른 서버 상태를 보지 않도록 설계 |
| Transports | [Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) | 로컬은 `stdio`, 원격/운영은 `Streamable HTTP` | HTTP endpoint는 Origin 검증, localhost bind, 인증 필요 |
| Authorization | [Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | MCP 서버를 OAuth 2.1 resource server로 취급 | token passthrough 금지, audience/scope 검증 필요 |
| Tools | [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) | 계산, 랭킹, 검증, run trigger 후보는 tool | human-in-the-loop, JSON Schema, structured output 필요 |
| Resources | [Resources](https://modelcontextprotocol.io/specification/2025-11-25/server/resources) | run artifact, evidence, schema, report는 resource | URI 검증, 접근 제어, binary encoding 필요 |
| Security | [Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices) | confused deputy, SSRF, token passthrough, scope 최소화 대응 | proxy성 tool은 특히 위험 |
| SDK 목록 | [Official SDKs](https://modelcontextprotocol.io/docs/sdk) | Python/TypeScript는 Tier 1 | SDK major/version 변화 감시 |
| Inspector | [MCP Inspector](https://modelcontextprotocol.io/docs/tools/inspector) | 개발/검증 표준 도구 | invalid input, missing args, concurrent call까지 확인 |
| Registry | [Official MCP Registry](https://registry.modelcontextprotocol.io/) | 외부 서버 후보 탐색 경로 | 등록 서버가 곧 production-safe라는 뜻은 아님 |

## 3. SDK 후보

| repo명 | 링크 | 소스코드 후보 | 적용 포인트 | 주의점 |
|---|---|---|---|---|
| `modelcontextprotocol/python-sdk` | [GitHub](https://github.com/modelcontextprotocol/python-sdk) | [`fastmcp_quickstart.py`](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/fastmcp_quickstart.py), [`streamable_config.py`](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_config.py), [`streamable_http_basic_mounting.py`](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/streamable_http_basic_mounting.py), [`oauth_server.py`](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/snippets/servers/oauth_server.py) | Python 서비스와 가장 잘 맞음. `@mcp.tool`, `@mcp.resource`, lifespan context, progress/logging, Streamable HTTP 지원 | README 기준 v1.x stable, v2는 pre-alpha. 버전 pin 필요 |
| `modelcontextprotocol/typescript-sdk` | [GitHub](https://github.com/modelcontextprotocol/typescript-sdk) | [`docs/server.md`](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/server.md), [`examples/server`](https://github.com/modelcontextprotocol/typescript-sdk/blob/main/examples/server/README.md) | Zod input/output schema, `structuredContent`, `resource_link`, Express/Hono HTTP 패턴 참고 | MiroFish 핵심이 Python이므로 TS 서버는 운영 경계가 늘어남 |

권장 선택: **Python SDK `FastMCP("MarketFlow MiroFish", stateless_http=True, json_response=True)`**. 공식 README도 Streamable HTTP production 배포에는 `stateless_http=True`, `json_response=True` 조합을 확장성 관점에서 권장한다.

## 4. 공식/준공식 서버 예제

| repo/source | 링크 | 적용 포인트 | 주의점 |
|---|---|---|---|
| `modelcontextprotocol/servers` | [GitHub](https://github.com/modelcontextprotocol/servers) | steering group reference server 모음 | README가 reference/demo 성격을 명시. 그대로 production 복붙 금지 |
| `server-everything` | [src/everything](https://github.com/modelcontextprotocol/servers/tree/main/src/everything) | tools/resources/prompts/logging/progress/tasks/sampling 종합 샘플. MiroFish MCP contract test fixture로 적합 | 유용한 서버가 아니라 client builder용 test server |
| `server-filesystem` | [src/filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) | allowed directories, Roots, path sandbox 패턴. `data/admin_mirofish/runs` 노출 설계에 참고 | write/edit/delete tool은 기본 제외. read-only부터 시작 |
| `server-fetch` | [src/fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) | `max_length`, `start_index`, markdown conversion, robots/user-agent 패턴 참고 | SSRF, private IP, redirect, credential leak 방어 필요 |
| `server-memory` | [src/memory](https://github.com/modelcontextprotocol/servers/tree/main/src/memory) | entity/relation/observation 기반 knowledge graph 모델 참고 | 관측값마다 source/fetched_at/confidence 없으면 MiroFish evidence로 부적합 |
| `server-git` | [src/git](https://github.com/modelcontextprotocol/servers/tree/main/src/git) | `status`, `diff`, `log`, `search`처럼 분석 결과를 tool화하는 명명 패턴 참고 | mutation성 git tool은 MarketFlow MCP 기본 범위에서 제외 |

## 5. MiroFish Endpoint 후보

### Resources

| URI | 내용 | 적용 포인트 |
|---|---|---|
| `mirofish://runs/latest` | 최신 run 요약 | admin UI와 동일한 최신 상태를 MCP에서 조회 |
| `mirofish://runs/{run_id}/summary` | run metadata, status, source freshness, fallback 여부 | 재현성과 fallback 표시 |
| `mirofish://runs/{run_id}/candidates` | 후보 목록, rank, score components | LLM이 전체 후보를 읽을 때 사용 |
| `mirofish://runs/{run_id}/evidence/{symbol}` | 특정 종목 evidence bundle | 최종 verdict의 exact target 확인 |
| `mirofish://runs/{run_id}/artifacts/{name}` | JSON artifact 원문 | backtest/replay/debug용 |
| `mirofish://schemas/run-artifact` | artifact schema | tool 결과와 resource 구조를 고정 |

설계 원칙: resource는 side effect가 없는 읽기 전용 context다. 큰 artifact는 직접 본문에 다 넣지 말고 resource link 또는 pagination/chunking을 쓴다.

### Tools

| tool명 | 입력 | 출력 | 적용 포인트 |
|---|---|---|---|
| `list_mirofish_runs` | `limit`, `status?`, `since?` | run id 목록과 metadata | MCP client가 탐색 시작 |
| `get_mirofish_candidate` | `run_id`, `symbol` | 후보 상세 JSON | exact symbol/name/market 고정 |
| `rank_mirofish_candidates` | `run_id`, `metric`, `limit` | 정렬된 후보와 score breakdown | alpha 후보 비교 |
| `validate_mirofish_candidate` | `run_id`, `symbol`, `horizon?` | risk/evidence/entry timing 검증 | LLM은 숫자를 발명하지 않고 서비스 계산만 해석 |
| `explain_mirofish_run` | `run_id`, `focus?` | structured summary + resource links | 긴 artifact를 요약하되 원문 링크 유지 |
| `create_mirofish_run` | `universe`, `mode`, `dry_run=true` | run request/result | 2단계 이후, 별도 scope와 human confirmation 필요 |

설계 원칙: tool은 결정적 계산, 조회, 검증 중심으로 둔다. 외부 live call, run 생성, 파일 쓰기, 배포성 동작은 read-only MCP가 안정화된 뒤 별도 scope로 분리한다.

### Prompts

| prompt명 | 목적 |
|---|---|
| `mirofish_candidate_review` | 특정 후보의 evidence, risk, timing을 검토하는 표준 프롬프트 |
| `mirofish_run_postmortem` | run 결과와 false positive/negative를 되짚는 표준 프롬프트 |
| `mirofish_alpha_hypothesis` | 후보군에서 검증 가능한 alpha 가설을 정리 |

Prompts는 필수 1차 범위가 아니다. 초기 구현은 resources/tools만으로 충분하다.

## 6. 구현 패턴 제안

추천 파일 구조:

```text
app/services/mirofish/mcp_contract.py       # artifact loader, schema, pure functions
app/services/mirofish/mcp_server.py         # FastMCP resources/tools registration
mirofish_mcp_server.py                      # sidecar entrypoint
tests/test_mirofish_mcp_contract.py         # loader/tool contract focused tests
```

초기 코드 후보:

```python
from __future__ import annotations

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

RUNS_DIR = Path("data/admin_mirofish/runs").resolve()

mcp = FastMCP(
    "MarketFlow MiroFish",
    stateless_http=True,
    json_response=True,
)


def _safe_run_dir(run_id: str) -> Path:
    path = (RUNS_DIR / run_id).resolve()
    if RUNS_DIR not in path.parents and path != RUNS_DIR:
        raise ValueError("invalid run_id")
    if not path.exists():
        raise FileNotFoundError(run_id)
    return path


@mcp.resource("mirofish://runs/{run_id}/summary")
def read_run_summary(run_id: str) -> str:
    summary_path = _safe_run_dir(run_id) / "summary.json"
    return summary_path.read_text(encoding="utf-8")


@mcp.tool()
def list_mirofish_runs(limit: int = 20) -> dict:
    run_dirs = sorted(
        [p for p in RUNS_DIR.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[: max(1, min(limit, 100))]
    return {"runs": [{"run_id": p.name} for p in run_dirs]}


@mcp.tool()
def get_mirofish_candidate(run_id: str, symbol: str) -> dict:
    candidates = json.loads((_safe_run_dir(run_id) / "candidates.json").read_text(encoding="utf-8"))
    matches = [row for row in candidates if row.get("symbol") == symbol]
    return {"run_id": run_id, "symbol": symbol, "matches": matches}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

주의: 위 코드는 구현 방향을 보이는 skeleton이다. 실제 파일명은 현재 run artifact 구조에 맞춰 확인해야 하며, SDK 버전에 맞춰 host/port 설정 방식을 고정해야 한다.

## 7. 인증/보안 설계

| 영역 | 권장 패턴 | 주의점 |
|---|---|---|
| 로컬 개발 | `127.0.0.1` bind, read-only, Inspector 검증 | `0.0.0.0` bind 금지 |
| HTTP 운영 | Streamable HTTP + OAuth 2.1 resource server | Protected Resource Metadata, `WWW-Authenticate`, scope challenge 구현 |
| Token 검증 | Python SDK `TokenVerifier` 패턴 | issuer, audience, expiration, scope 검증. token passthrough 금지 |
| Scope | `mirofish:runs:read`, `mirofish:evidence:read`, `mirofish:analysis:run`, `mirofish:admin:write` | 처음에는 read scope만 |
| Resource URI | custom scheme `mirofish://...` | path traversal 방지, run_id/symbol allowlist 검증 |
| Secrets | `.env`, KIS token cache, Cloudflare credential 미노출 | resource/tool 결과에 secret path나 env dump 금지 |
| SSRF | fetch/proxy tool 기본 제외 | 외부 URL tool을 만들 경우 allowlist와 private IP 차단 |
| Prompt injection | tool description과 resource text를 untrusted로 취급 | tool chaining으로 파일 쓰기/외부 전송이 되지 않게 제한 |

## 8. 구현 로드맵

| 단계 | 기간 | 산출물 | 검증 |
|---|---|---|---|
| Phase 0 spike | 0.5일 | Python SDK pin, `FastMCP` hello endpoint | Inspector 연결, `tools/list` 통과 |
| Phase 1 read-only | 1-2일 | run/candidate/evidence resources, list/get/rank tools | mocked artifact 기반 pytest, Inspector smoke |
| Phase 2 auth | 1-2일 | bearer/OAuth resource server, scope 분리 | no-token 401, wrong-scope 403, read-scope success |
| Phase 3 controlled actions | 이후 | `create_mirofish_run(dry_run=true)` 등 mutation tool | human confirmation, audit log, admin UI 표시 |

## 9. 최종 권고

1. 첫 구현은 **Python SDK `FastMCP` sidecar + read-only resources/tools**로 시작한다.
2. MiroFish의 알파 목적에 맞춰 MCP는 “새 신호 생성기”가 아니라 **run artifact와 검증 계산을 안전하게 외부 AI client에 노출하는 표준 인터페이스**로 정의한다.
3. official `server-filesystem`, `server-fetch`, `server-memory`, `server-everything`은 직접 의존보다 설계 패턴 참고와 contract test fixture로 쓰는 편이 적합하다.
4. 운영 공개 전에는 OAuth resource server, scope, Origin 검증, secret redaction, artifact schema 고정을 완료해야 한다.
5. 금융 데이터 team의 결과와 합칠 때도 data source는 MCP `resource`/`tool` 뒤에 숨기고, numeric value는 반드시 파일/API/계산 결과에서만 오게 한다.
