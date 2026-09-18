"""MiroFish 자연어 채팅 에이전트 — DeepSeek V4 function calling 으로 안전한 read-only MCP 도구 호출.

DeepSeek-first 중앙 라우팅과 승인된 OpenAI 1회 fallback을 사용합니다.

설계 원칙:
- 안전성 우선: 14개 MCP tool 중 read-only 8개만 채팅에 노출 (run_*, send_*, refresh_* 제외)
- 한국어 응답
- 최대 5회 함수 호출 루프 (무한 루프 방지)
- 도구 실패 시 graceful — '데이터 없음' 안내
- LLM 미설정 / 오류 시 helpful fallback

사용:
    from app.services.mirofish.chat_agent import run_chat
    result = run_chat(user_message='이번 TOP 3 알려줘', history=[])
    # result = {'reply': str, 'tool_calls': [{name, args, result_preview}], 'iterations': int}
"""

from __future__ import annotations

import json
import logging
import os
import hashlib
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.services.ai_routing.budget import BudgetManager
from app.services.ai_routing.contracts import (
    AnalysisStatus,
    Operation,
    ProviderErrorClass,
    RoutingRequest,
    RoutingResult,
)
from app.services.ai_routing.providers import (
    AdapterResponse,
    ProviderCallError,
    classify_exception,
    normalize_openai_usage,
)
from app.services.ai_routing.router import AIRouter
from app.services.ai_routing.store import default_store

from app.services.mirofish import autonomous_mcp, live_data, technical_analysis, workflow
from app.services.mirofish.llm_system_prompt import (
    SYSTEM_INSTRUCTION,
    SYSTEM_PROMPT_SHA256,
    SYSTEM_PROMPT_VERSION,
    get_system_prompt_status,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
_DEFAULT_CHAT_ENVELOPE_MAX_BYTES = 28_000


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _safe_tool_error(exc: Exception) -> dict[str, str]:
    return {'error': f'tool_failed: {type(exc).__name__}'}


# ─── Tool registry — 안전한 read-only 도구 ──────────────────────────

def _get_top3_summary(workflow_id: str = '') -> dict[str, Any]:
    wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
    if not wf:
        return {'error': 'workflow not found', 'hint': '아직 스캔 분석이 완료되지 않았습니다.'}
    try:
        payload = workflow.build_share_payload(wf)
    except Exception as exc:
        return _safe_tool_error(exc)
    top_items = payload.get('top_items', [])
    return {
        'workflow_id': payload.get('workflow_id'),
        'completed_at': payload.get('completed_at'),
        'top_count': len(top_items),
        'top_items': top_items,
        'one_liner': ' / '.join(
            f"#{t['rank']} {t['name']} {t['action']} {t['confidence_pct']}%" for t in top_items
        ),
    }


def _get_workflow_share(workflow_id: str = '', rank: int | None = None) -> dict[str, Any]:
    wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
    if not wf:
        return {'error': 'workflow not found'}
    try:
        return workflow.build_share_payload(wf, rank=rank)
    except Exception as exc:
        return _safe_tool_error(exc)


def _resolve_target(target: str) -> dict[str, Any]:
    try:
        resolved = live_data.resolve_target(target)
        # 검색 결과도 일부 포함
        candidates = live_data.search_target_candidates(target, limit=5)
        return {'resolved': resolved, 'candidates': candidates}
    except Exception as exc:
        return _safe_tool_error(exc)


TOOL_REGISTRY: dict[str, Any] = {
    'get_market_clock': lambda **_kw: autonomous_mcp.get_market_clock(),
    'get_autonomous_status': lambda **_kw: autonomous_mcp.get_autonomous_status(),
    'get_repository_state': lambda **_kw: autonomous_mcp.get_repository_state(),
    'list_recent_workflows': lambda limit=10, **_kw: autonomous_mcp.list_recent_workflows(limit=int(limit)),
    'list_recent_scanner_runs': lambda limit=10, **_kw: autonomous_mcp.list_recent_scanner_runs(limit=int(limit)),
    'get_top3_summary': lambda workflow_id='', **_kw: _get_top3_summary(workflow_id=workflow_id),
    'get_workflow_share': lambda workflow_id='', rank=None, **_kw: _get_workflow_share(
        workflow_id=workflow_id, rank=int(rank) if rank else None,
    ),
    'resolve_target': lambda target='', **_kw: _resolve_target(target=target),
    'analyze_levels': lambda target='', **_kw: technical_analysis.analyze_target_with_levels(target=target),
    'get_llm_system_prompt_status': lambda **_kw: get_system_prompt_status(),
}


# ─── Gemini function declarations ─────────────────────────────────

FUNCTION_DECLARATIONS = [
    {
        'name': 'get_market_clock',
        'description': '한국 시장 (KST) 시간 + 현재 세션 상태 (pre_open / regular / lunch / after_hours) 반환',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_autonomous_status',
        'description': 'MiroFish 자동화 컨트롤플레인 상태 — 스캐너/워크플로우/학습 가동 여부, 마지막 실행 시각',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'get_repository_state',
        'description': 'git branch / HEAD / dirty 상태 (코드 변경 여부 확인용)',
        'parameters': {'type': 'object', 'properties': {}},
    },
    {
        'name': 'list_recent_workflows',
        'description': '최근 MCP scan-analyze 워크플로우 실행 목록. 사용자가 "최근 분석", "지난 워크플로우" 등 요청 시.',
        'parameters': {
            'type': 'object',
            'properties': {'limit': {'type': 'integer', 'description': '반환 개수 (1-20)', 'default': 10}},
        },
    },
    {
        'name': 'list_recent_scanner_runs',
        'description': '최근 알파 스캐너 실행 목록. "스캐너 실행 이력", "최근 스캔 결과" 등.',
        'parameters': {
            'type': 'object',
            'properties': {'limit': {'type': 'integer', 'default': 10}},
        },
    },
    {
        'name': 'get_top3_summary',
        'description': (
            '최신 (또는 지정 workflow_id) MCP TOP 3 종목 요약 — 5인 페르소나 인용 + CIO reasoning + 검증 결과 포함. '
            '"이번 TOP 3", "오늘 추천 종목", "MCP 결과" 같은 질의에 사용.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'description': '빈 문자열이면 최신', 'default': ''},
            },
        },
    },
    {
        'name': 'get_workflow_share',
        'description': (
            '카카오톡 공유용 풍부한 페이로드 — 특정 종목 단일 공유는 rank=1|2|3, 전체는 rank 생략. '
            '"카톡 공유 정보", "X 종목 공유 데이터" 같은 질의.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'workflow_id': {'type': 'string', 'default': ''},
                'rank': {'type': 'integer', 'description': '1|2|3 (단일 종목) 또는 비워두면 TOP 3 전체'},
            },
        },
    },
    {
        'name': 'resolve_target',
        'description': (
            '종목명/티커를 분석 대상으로 해석. "삼성전자" → 005930, "AAPL" 등 모두 처리. '
            '사용자가 특정 종목에 대한 정보 / 후보를 묻기 시작할 때 호출.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {'target': {'type': 'string', 'description': '한국 종목명, 티커, 또는 키워드'}},
            'required': ['target'],
        },
    },
    {
        'name': 'analyze_levels',
        'description': (
            '한국 종목의 추세 분석 + 매수가/목표가/손절가 자동 제안. '
            'SMA5/20/60/120 정배열 여부, ATR(14) 변동성, 20일 고/저점을 계산해서 '
            'Mark Minervini SEPA + swing 트레이딩 규칙으로 entry / target1 / target2 / stop 가격을 산출. '
            '"삼성전자 매수가 알려줘", "X 종목 손절 어디?", "추세 어때?" 같은 질의에 사용.'
        ),
        'parameters': {
            'type': 'object',
            'properties': {
                'target': {'type': 'string', 'description': '한국 종목명 또는 6자리 코드'}
            },
            'required': ['target'],
        },
    },
    {
        'name': 'get_llm_system_prompt_status',
        'description': (
            'MiroFish LLM MCP 고정 시스템 프롬프트의 버전, 해시, 6-Agent 모드 상태를 확인. '
            '전체 프롬프트 원문은 노출하지 않음.'
        ),
        'parameters': {'type': 'object', 'properties': {}},
    },
]


def _response_metadata() -> dict[str, str]:
    return {
        'prompt_version': SYSTEM_PROMPT_VERSION,
        'prompt_hash': SYSTEM_PROMPT_SHA256[:12],
    }


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_value(value: object) -> object:
    return getattr(value, 'value', value)


class _ChatToolsAdapter:
    """OpenAI-compatible native tool serializer behind the central router."""

    endpoint = 'chat.completions.tools'
    request_timeout_seconds = 90.0

    def __init__(self, provider: str, client_factory, *, extra_body: dict | None = None):
        self.provider = provider
        self.client_factory = client_factory
        self.extra_body = dict(extra_body or {})

    def generate(
        self,
        request: RoutingRequest,
        *,
        model: str,
        max_output_tokens: int,
    ) -> AdapterResponse:
        client = self.client_factory()
        if client is None:
            raise ProviderCallError(ProviderErrorClass.CLIENT_UNAVAILABLE)
        try:
            envelope = json.loads(request.prompt)
            messages = envelope['messages']
            tools = envelope['tools']
        except (KeyError, TypeError, json.JSONDecodeError):
            raise ProviderCallError(ProviderErrorClass.INVALID_JSON) from None

        kwargs: dict[str, Any] = {
            'model': model,
            'messages': messages,
            'tools': tools,
        }
        if model.startswith(('gpt-5', 'o1', 'o3', 'o4')):
            kwargs['max_completion_tokens'] = max_output_tokens
        else:
            kwargs['temperature'] = request.temperature
            kwargs['max_tokens'] = max_output_tokens
        if self.extra_body:
            kwargs['extra_body'] = self.extra_body
        try:
            response = client.chat.completions.create(**kwargs)
            message = response.choices[0].message
            tool_calls = []
            for tool_call in (_field(message, 'tool_calls') or []):
                function = _field(tool_call, 'function')
                tool_calls.append({
                    'id': str(_field(tool_call, 'id') or ''),
                    'name': str(_field(function, 'name') or ''),
                    'arguments': _field(function, 'arguments') or '{}',
                })
            payload = {
                'content': str(_field(message, 'content') or ''),
                'tool_calls': tool_calls,
            }
            return AdapterResponse(
                text=json.dumps(payload, ensure_ascii=False, separators=(',', ':')),
                usage=normalize_openai_usage(_field(response, 'usage')),
                endpoint=self.endpoint,
            )
        except ProviderCallError:
            raise
        except Exception as exc:
            raise ProviderCallError(classify_exception(exc)) from None


def _chat_envelope_validator(payload: object) -> ProviderErrorClass | None:
    if not isinstance(payload, dict):
        return ProviderErrorClass.INVALID_JSON
    if not isinstance(payload.get('content'), str):
        return ProviderErrorClass.INVALID_JSON
    tool_calls = payload.get('tool_calls')
    if not isinstance(tool_calls, list):
        return ProviderErrorClass.INVALID_JSON
    if not payload.get('content', '').strip() and not tool_calls:
        return ProviderErrorClass.EMPTY
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            return ProviderErrorClass.INVALID_JSON
        if not all(key in tool_call for key in ('id', 'name', 'arguments')):
            return ProviderErrorClass.INVALID_JSON
        if not isinstance(tool_call.get('arguments'), (str, dict)):
            return ProviderErrorClass.INVALID_JSON
    return None


def _build_chat_router() -> AIRouter:
    from app.services.mirofish.llm_client import (
        deepseek_extra_body,
        get_deepseek_client,
        get_openai_client,
    )

    store = default_store()
    return AIRouter(
        adapters={
            'deepseek': _ChatToolsAdapter(
                'deepseek', get_deepseek_client, extra_body=deepseek_extra_body()
            ),
            'openai': _ChatToolsAdapter('openai', get_openai_client),
        },
        budget=BudgetManager(store, pool='chat'),
        store=store,
    )


def _chat_profile(explicit: str | None = None) -> tuple[str, int]:
    profile = (explicit or os.getenv('MIROFISH_CHAT_PROFILE', 'compat')).strip().lower()
    if profile != 'compact':
        return 'compat', MAX_ITERATIONS
    iterations = _int_env('MIROFISH_CHAT_COMPACT_ITERATIONS', 2)
    return 'compact', max(1, min(3, iterations))


def _bounded_history(history: list[dict] | None, profile: str) -> list[dict[str, str]]:
    limit = 4 if profile == 'compact' else 10
    char_limit = 500 if profile == 'compact' else 1_200
    bounded: list[dict[str, str]] = []
    for message in (history or [])[-limit:]:
        if not isinstance(message, dict):
            continue
        role = 'user' if message.get('role') == 'user' else 'assistant'
        content = str(message.get('content') or '').strip()
        if content:
            bounded.append({'role': role, 'content': content[:char_limit]})
    return bounded


def _chat_envelope_max_bytes() -> int:
    # Keep deterministic headroom for the router's JSON-mode reservation
    # suffix/overhead under the 30k chat-pool input cap.
    return max(
        22_000,
        min(
            28_000,
            _int_env(
                'MIROFISH_CHAT_ENVELOPE_MAX_BYTES',
                _DEFAULT_CHAT_ENVELOPE_MAX_BYTES,
            ),
        ),
    )


def _truncate_utf8(value: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ''
    encoded = value.encode('utf-8')
    if len(encoded) <= max_bytes:
        return value
    marker = '…[truncated]'
    marker_bytes = marker.encode('utf-8')
    if max_bytes <= len(marker_bytes):
        return encoded[:max_bytes].decode('utf-8', errors='ignore')
    prefix = encoded[:max_bytes - len(marker_bytes)].decode('utf-8', errors='ignore')
    return prefix + marker


def _serialize_chat_envelope(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> str | None:
    """Bound the actual reserved native envelope while preserving tool pairs."""
    limit = _chat_envelope_max_bytes()
    # All current message fields are JSON-native. Round-tripping produces a
    # private copy that can be compacted without corrupting the next iteration.
    working = json.loads(json.dumps(messages, ensure_ascii=False, default=str))

    def serialize() -> str:
        return json.dumps(
            {'messages': working, 'tools': tools},
            ensure_ascii=False,
            separators=(',', ':'),
        )

    def size() -> int:
        return len(serialize().encode('utf-8'))

    latest_user = max(
        (index for index, message in enumerate(working) if message.get('role') == 'user'),
        default=-1,
    )
    if latest_user < 0:
        return None

    # History is expendable oldest-first; the current user turn is never
    # removed. This also keeps compact/compat behavior deterministic.
    while size() > limit and latest_user > 1:
        del working[1]
        latest_user -= 1

    # Bound previous native tool transcripts. IDs and assistant/tool pairing
    # are retained, while already-executed arguments and evidence prose are
    # compacted for subsequent reasoning.
    if size() > limit:
        for message in working[latest_user + 1:]:
            if message.get('role') == 'assistant':
                message['content'] = _truncate_utf8(
                    str(message.get('content') or ''), 256
                )
                for call in message.get('tool_calls') or []:
                    function = call.get('function') if isinstance(call, dict) else None
                    if not isinstance(function, dict):
                        continue
                    arguments = str(function.get('arguments') or '{}')
                    if len(arguments.encode('utf-8')) > 1_024:
                        function['arguments'] = '{}'
            elif message.get('role') == 'tool':
                try:
                    evidence = json.loads(str(message.get('content') or '{}'))
                except (TypeError, json.JSONDecodeError):
                    evidence = {'summary': 'tool_evidence_unavailable'}
                if isinstance(evidence, dict):
                    evidence['summary'] = _truncate_utf8(
                        str(evidence.get('summary') or ''), 256
                    )
                    evidence['truncated'] = True
                    message['content'] = json.dumps(
                        evidence,
                        ensure_ascii=False,
                        separators=(',', ':'),
                    )

    # If multiple completed tool rounds remain, discard only whole oldest
    # assistant+tool groups. The newest native pair is kept for the answer.
    while size() > limit:
        assistant_indexes = [
            index
            for index in range(latest_user + 1, len(working))
            if working[index].get('role') == 'assistant'
            and working[index].get('tool_calls')
        ]
        if len(assistant_indexes) <= 1:
            break
        start = assistant_indexes[0]
        end = assistant_indexes[1]
        del working[start:end]

    # Allocate the remaining bytes to the latest user content. The JSON
    # escaping overhead is measured, not guessed.
    user_message = working[latest_user]
    original_content = str(user_message.get('content') or '')
    user_message['content'] = ''
    base_size = size()
    available = max(0, limit - base_size - 32)
    user_message['content'] = _truncate_utf8(original_content, available)
    prompt = serialize()
    return prompt if len(prompt.encode('utf-8')) <= limit else None


def _tool_error_code(value: Any) -> str:
    """Collapse arbitrary upstream error text to a non-sensitive reason code."""
    text = str(value or "").strip().casefold()
    if text.startswith("tool_failed:"):
        return "tool_failed"
    if "malformed" in text and "argument" in text:
        return "malformed_arguments"
    if "unknown_tool" in text:
        return "unknown_tool"
    if "not found" in text or "not_found" in text:
        return "not_found"
    return "upstream_error"


def _looks_sensitive_tool_text(value: str) -> bool:
    folded = value.casefold()
    markers = (
        "authorization:",
        "bearer ",
        "api_key",
        "apikey",
        "token=",
        "password=",
        "secret=",
        "sk-",
        ".env",
    )
    return any(marker in folded for marker in markers)


def _sanitize_tool_result(value: Any, *, field: str = "", depth: int = 0) -> Any:
    """Recursively remove provider exception detail before any exposure/hash."""
    if depth > 12:
        return "bounded_structure"
    field_name = field.casefold()
    if any(marker in field_name for marker in ("error", "exception", "traceback")):
        if value is None or isinstance(value, (bool, int, float)) or value == "":
            return value
        return _tool_error_code(value)
    if isinstance(value, dict):
        return {
            str(key): _sanitize_tool_result(item, field=str(key), depth=depth + 1)
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_tool_result(item, depth=depth + 1)
            for item in list(value)[:100]
        ]
    if isinstance(value, str) and _looks_sensitive_tool_text(value):
        return "redacted_sensitive_value"
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(type(value).__name__)


def _tool_evidence(tool_result: Any) -> dict[str, Any]:
    tool_result = _sanitize_tool_result(tool_result)
    try:
        raw = json.dumps(tool_result, ensure_ascii=False, default=str, sort_keys=True)
    except Exception:
        raw = str(tool_result)
    return {
        'evidence_id': 'tool:' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16],
        'summary': raw[:600],
        'truncated': len(raw) > 600,
    }


def _usage_payload(usage: Any) -> dict[str, Any]:
    return {
        'input_tokens': usage.input_tokens,
        'cached_input_tokens': usage.cached_input_tokens,
        'output_tokens': usage.output_tokens,
        'reasoning_tokens': usage.reasoning_tokens,
        'total_tokens': usage.total_tokens,
        'usage_estimated': usage.usage_estimated,
        'raw_total_tokens': usage.raw_total_tokens,
        'mapping_version': usage.mapping_version,
        'mapping_status': usage.mapping_status,
    }


def _billable_records(result: RoutingResult) -> list[tuple[Any, Decimal | None]]:
    attempts = [
        attempt
        for attempt in result.attempts
        if attempt.status in {'success', 'failed'}
    ]
    if attempts:
        return [(attempt.usage, attempt.estimated_cost_usd) for attempt in attempts]
    return [(result.usage, result.estimated_cost_usd)]


def _aggregate_billing(results: list[RoutingResult]) -> tuple[dict[str, Any], dict[str, Any]]:
    records = [record for result in results for record in _billable_records(result)]
    usages = [usage for usage, _cost in records]

    def known_total(field: str) -> int:
        return sum(
            int(value)
            for value in (getattr(usage, field) for usage in usages)
            if value is not None
        )

    complete = bool(usages) and all(
        usage.input_tokens is not None
        and usage.output_tokens is not None
        and not usage.usage_estimated
        for usage in usages
    )
    optional_complete = {
        field: bool(usages) and all(getattr(usage, field) is not None for usage in usages)
        for field in ('cached_input_tokens', 'reasoning_tokens')
    }
    usage_payload = {
        'input_tokens': known_total('input_tokens') if complete else None,
        'cached_input_tokens': (
            known_total('cached_input_tokens')
            if optional_complete['cached_input_tokens']
            else None
        ),
        'output_tokens': known_total('output_tokens') if complete else None,
        'reasoning_tokens': (
            known_total('reasoning_tokens')
            if optional_complete['reasoning_tokens']
            else None
        ),
        'total_tokens': (
            known_total('input_tokens') + known_total('output_tokens')
            if complete
            else None
        ),
        'known_input_tokens': known_total('input_tokens'),
        'known_cached_input_tokens': known_total('cached_input_tokens'),
        'known_output_tokens': known_total('output_tokens'),
        'known_reasoning_tokens': known_total('reasoning_tokens'),
        'known_total_tokens': (
            known_total('input_tokens') + known_total('output_tokens')
        ),
        'usage_estimated': not complete,
        'complete': complete,
        'mapping_version': 'chat-attempt-aggregate-v1',
        'mapping_status': 'valid' if complete else 'incomplete',
    }

    costs = [cost for _usage, cost in records]
    known_costs = [Decimal(cost) for cost in costs if cost is not None]
    cost_complete = bool(costs) and len(known_costs) == len(costs)
    billing_payload = {
        'estimated_cost_usd': (
            str(sum(known_costs, Decimal('0'))) if cost_complete else None
        ),
        'known_estimated_cost_usd': (
            str(sum(known_costs, Decimal('0'))) if known_costs else None
        ),
        'cost_complete': cost_complete,
    }
    return usage_payload, billing_payload


def _attempt_payload(attempt: Any) -> dict[str, Any]:
    return {
        'request_id': attempt.request_id,
        'provider': attempt.provider,
        'model': attempt.model,
        'status': attempt.status,
        'selected': attempt.selected,
        'error_class': _enum_value(attempt.error_class),
        'usage': _usage_payload(attempt.usage),
        'estimated_cost_usd': (
            str(attempt.estimated_cost_usd)
            if attempt.estimated_cost_usd is not None
            else None
        ),
        'pricing_version': attempt.pricing_version,
        'breaker_state': attempt.breaker_state,
    }


def _terminal_error(result: RoutingResult | None) -> object:
    if result is None or result.text:
        return None
    for attempt in reversed(result.attempts):
        if attempt.status == 'failed' and attempt.error_class is not None:
            return _enum_value(attempt.error_class)
    return _enum_value(result.fallback_reason)


def _routing_summary(results: list[RoutingResult], *, run_id: str, profile: str) -> dict[str, Any]:
    last = results[-1] if results else None
    fallback_result = next(
        (item for item in reversed(results) if item.fallback_used),
        None,
    )
    retry_result = next(
        (item for item in reversed(results) if item.retry_reason is not None),
        None,
    )

    usage, billing = _aggregate_billing(results)
    return {
        'run_id': run_id,
        'profile': profile,
        'budget_pool': 'chat',
        'primary_provider': last.primary_provider if last else 'deepseek',
        'actual_provider': last.actual_provider if last else None,
        'model': last.model if last else None,
        'fallback_used': any(item.fallback_used for item in results),
        'fallback_reason': (
            _enum_value(fallback_result.fallback_reason) if fallback_result else None
        ),
        'retry_reason': _enum_value(retry_result.retry_reason) if retry_result else None,
        'terminal_error': _terminal_error(last),
        'usage': usage,
        **billing,
        'attempt_count': sum(len(item.attempts) for item in results),
        'logical_calls': len(results),
        'calls': [
            {
                'iteration': index,
                'analysis_status': item.analysis_status.value,
                'actual_provider': item.actual_provider,
                'model': item.model,
                'fallback_used': item.fallback_used,
                'fallback_reason': _enum_value(item.fallback_reason),
                'retry_reason': _enum_value(item.retry_reason),
                'terminal_error': _terminal_error(item),
                'usage': _aggregate_billing([item])[0],
                **_aggregate_billing([item])[1],
                'attempt_count': len(item.attempts),
                'attempts': [_attempt_payload(attempt) for attempt in item.attempts],
            }
            for index, item in enumerate(results, 1)
        ],
    }


def run_chat(
    user_message: str,
    history: list[dict] | None = None,
    *,
    profile: str | None = None,
    router: AIRouter | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run one cost-bounded DS-first/OA-once function-calling turn.

    Args:
        user_message: 사용자 입력
        history: [{'role': 'user'|'assistant', 'content': str}] 이전 대화

    Returns:
        {'reply': str, 'tool_calls': [...], 'iterations': int,
         'method': 'llm'|'llm_degraded'|'llm_error'|'fallback'}
    """
    user_message = (user_message or '').strip()
    selected_profile, max_iterations = _chat_profile(profile)
    logical_run_id = run_id or f'chat:{uuid4()}'
    if not user_message:
        return {
            'reply': '메시지를 입력해 주세요.',
            'tool_calls': [],
            'iterations': 0,
            'method': 'fallback',
            'analysis_status': AnalysisStatus.DEGRADED.value,
            'error_class': 'empty_input',
            'routing': _routing_summary(
                [], run_id=logical_run_id, profile=selected_profile
            ),
            **_response_metadata(),
        }

    if router is None and not (os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')):
        return {
            'reply': 'AI API가 설정되지 않아 채팅을 사용할 수 없습니다. 관리자에게 문의해 주세요.',
            'tool_calls': [],
            'iterations': 0,
            'method': 'fallback',
            'analysis_status': AnalysisStatus.DEGRADED.value,
            'error_class': ProviderErrorClass.CLIENT_UNAVAILABLE.value,
            'routing': _routing_summary(
                [], run_id=logical_run_id, profile=selected_profile
            ),
            **_response_metadata(),
        }
    return _run_chat_routed(
        user_message,
        history,
        profile=selected_profile,
        max_iterations=max_iterations,
        router=router or _build_chat_router(),
        run_id=logical_run_id,
    )


def _run_chat_routed(
    user_message: str,
    history: list[dict] | None,
    *,
    profile: str,
    max_iterations: int,
    router: AIRouter,
    run_id: str,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [
        {'role': 'system', 'content': SYSTEM_INSTRUCTION},
        *_bounded_history(history, profile),
        {'role': 'user', 'content': user_message},
    ]
    tools = [{'type': 'function', 'function': spec} for spec in FUNCTION_DECLARATIONS]
    tool_calls_log: list[dict[str, Any]] = []
    tool_results_log: list[dict[str, Any]] = []
    routed_results: list[RoutingResult] = []
    tool_error_count = 0

    for iteration in range(1, max_iterations + 1):
        prompt = _serialize_chat_envelope(messages, tools)
        if prompt is None:
            routing = _routing_summary(
                routed_results, run_id=run_id, profile=profile
            )
            routing['tool_error_count'] = tool_error_count
            return {
                'reply': '채팅 입력이 안전한 처리 한도를 초과했습니다.',
                'tool_calls': tool_calls_log,
                'iterations': iteration - 1,
                'method': 'llm_error',
                'analysis_status': AnalysisStatus.DEGRADED.value,
                'error_class': 'input_too_large',
                'routing': routing,
                **_response_metadata(),
            }
        openai_fallback_allowed = not any(
            result.actual_provider == 'openai' for result in routed_results
        )
        routed = router.route_text(
            RoutingRequest(
                operation=Operation.INTERACTIVE_TEXT,
                prompt=prompt,
                run_id=run_id,
                request_id=f'{run_id}:iteration:{iteration}',
                json_mode=True,
                max_output_tokens=1200,
                caller_endpoint='/api/admin/mirofish/chat',
                domain_validator=_chat_envelope_validator,
                openai_fallback_allowed=openai_fallback_allowed,
            )
        )
        routed_results.append(routed)
        routing = _routing_summary(routed_results, run_id=run_id, profile=profile)
        routing['tool_error_count'] = tool_error_count
        if not routed.text:
            error_class = routing['terminal_error'] or 'provider_exhausted'
            return {
                'reply': 'AI 공급자 호출이 모두 실패해 답변을 완료하지 못했습니다.',
                'tool_calls': tool_calls_log,
                'iterations': iteration,
                'method': 'llm_error',
                'analysis_status': routed.analysis_status.value,
                'error_class': error_class,
                'routing': routing,
                **_response_metadata(),
            }
        try:
            envelope = json.loads(routed.text)
        except (TypeError, json.JSONDecodeError):
            return {
                'reply': 'AI 응답 형식이 올바르지 않아 답변을 완료하지 못했습니다.',
                'tool_calls': tool_calls_log,
                'iterations': iteration,
                'method': 'llm_error',
                'analysis_status': AnalysisStatus.DEGRADED.value,
                'error_class': ProviderErrorClass.INVALID_JSON.value,
                'routing': routing,
                **_response_metadata(),
            }

        tool_calls = envelope.get('tool_calls') or []
        if not tool_calls:
            reply = str(envelope.get('content') or '').strip()
            if not reply:
                return {
                    'reply': 'AI 응답이 비어 있어 답변을 완료하지 못했습니다.',
                    'tool_calls': tool_calls_log,
                    'iterations': iteration,
                    'method': 'llm_error',
                    'analysis_status': AnalysisStatus.DEGRADED.value,
                    'error_class': ProviderErrorClass.EMPTY.value,
                    'routing': routing,
                    **_response_metadata(),
                }
            reply = _append_grounded_tool_summary(reply, tool_results_log)
            if tool_error_count:
                return {
                    'reply': reply,
                    'tool_calls': tool_calls_log,
                    'iterations': iteration,
                    'method': 'llm_degraded',
                    'analysis_status': AnalysisStatus.DEGRADED.value,
                    'error_class': 'tool_failure',
                    'routing': routing,
                    **_response_metadata(),
                }
            return {
                'reply': reply,
                'tool_calls': tool_calls_log,
                'iterations': iteration,
                'method': 'llm',
                'analysis_status': routed.analysis_status.value,
                'routing': routing,
                **_response_metadata(),
            }

        assistant_calls = []
        prepared_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []
        for index, tool_call in enumerate(tool_calls, 1):
            call_id = str(tool_call.get('id') or f'{run_id}:{iteration}:{index}')
            name = str(tool_call.get('name') or '')
            raw_arguments = tool_call.get('arguments') or '{}'
            if isinstance(raw_arguments, dict):
                arguments = raw_arguments
                serialized_arguments = json.dumps(arguments, ensure_ascii=False)
                arguments_valid = True
            else:
                serialized_arguments = str(raw_arguments)
                try:
                    parsed = json.loads(serialized_arguments)
                    arguments_valid = isinstance(parsed, dict)
                    arguments = parsed if arguments_valid else {}
                except json.JSONDecodeError:
                    arguments = {}
                    arguments_valid = False
            native_call = {
                'id': call_id,
                'type': 'function',
                'function': {'name': name, 'arguments': serialized_arguments},
            }
            assistant_calls.append(native_call)
            prepared_calls.append((native_call, arguments, arguments_valid))
        messages.append({
            'role': 'assistant',
            'content': str(envelope.get('content') or ''),
            'tool_calls': assistant_calls,
        })

        for native_call, arguments, arguments_valid in prepared_calls:
            name = native_call['function']['name']
            if not arguments_valid:
                tool_result = {'error': 'malformed_arguments'}
            elif name not in TOOL_REGISTRY:
                tool_result: Any = {'error': f'unknown_tool: {name}'}
            else:
                try:
                    tool_result = TOOL_REGISTRY[name](**arguments)
                except Exception as exc:
                    logger.warning('[chat_agent] tool %s failed: %s', name, type(exc).__name__)
                    tool_result = {'error': f'tool_failed: {type(exc).__name__}'}
            tool_result = _sanitize_tool_result(tool_result)
            tool_failed = isinstance(tool_result, dict) and bool(tool_result.get('error'))
            if tool_failed:
                tool_error_count += 1
            evidence = _tool_evidence(tool_result)
            tool_calls_log.append({
                'name': name,
                'args': arguments,
                'argument_status': 'valid' if arguments_valid else 'invalid',
                'result_preview': evidence['summary'],
                'evidence_id': evidence['evidence_id'],
            })
            tool_results_log.append({
                'name': name,
                'args': arguments,
                'result': tool_result,
                'evidence_id': evidence['evidence_id'],
            })
            messages.append({
                'role': 'tool',
                'tool_call_id': native_call['id'],
                'content': json.dumps(evidence, ensure_ascii=False, separators=(',', ':')),
            })

    routing = _routing_summary(routed_results, run_id=run_id, profile=profile)
    routing['tool_error_count'] = tool_error_count
    return {
        'reply': '도구 호출 한도에 도달해 답변을 완료하지 못했습니다.',
        'tool_calls': tool_calls_log,
        'iterations': max_iterations,
        'method': 'llm_error',
        'analysis_status': AnalysisStatus.DEGRADED.value,
        'error_class': 'iteration_limit',
        'routing': routing,
        **_response_metadata(),
    }


def _run_chat_deepseek(user_message: str, history: list[dict] | None) -> dict[str, Any]:
    """Compatibility wrapper for callers of the former provider-specific path."""
    return run_chat(user_message, history)


def _run_chat_gemini(user_message: str, history: list[dict] | None) -> dict[str, Any]:
    """Compatibility wrapper; interactive policy remains DeepSeek-first."""
    return run_chat(user_message, history)


def _append_grounded_tool_summary(reply: str, tool_results_log: list[dict[str, Any]]) -> str:
    """Append deterministic MCP price/level numbers after model prose."""
    level_results = [
        item.get('result')
        for item in tool_results_log
        if item.get('name') == 'analyze_levels'
        and isinstance(item.get('result'), dict)
        and not item.get('result', {}).get('error')
    ]
    if not level_results:
        return reply

    summary = technical_analysis.format_grounded_levels_summary(level_results[-1])
    if not summary or '### MCP 가격 기준' in reply:
        return reply
    return f'{reply.rstrip()}\n\n---\n{summary}'
