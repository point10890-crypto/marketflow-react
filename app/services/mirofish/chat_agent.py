"""MiroFish 자연어 채팅 에이전트 — Gemini function calling 으로 안전한 read-only MCP 도구 호출.

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
from typing import Any

from app.services.mirofish import autonomous_mcp, live_data, technical_analysis, workflow
from app.services.mirofish.llm_system_prompt import (
    SYSTEM_INSTRUCTION,
    SYSTEM_PROMPT_SHA256,
    SYSTEM_PROMPT_VERSION,
    get_system_prompt_status,
)

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
MODEL_DEFAULT = 'gemini-2.5-flash'


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


MAX_OUTPUT_TOKENS = max(2048, _int_env('MIROFISH_CHAT_MAX_OUTPUT_TOKENS', 4096))


# ─── Tool registry — 안전한 read-only 도구 ──────────────────────────

def _get_top3_summary(workflow_id: str = '') -> dict[str, Any]:
    wf = workflow.read_workflow(workflow_id) if workflow_id else workflow.read_latest_workflow()
    if not wf:
        return {'error': 'workflow not found', 'hint': '아직 스캔 분석이 완료되지 않았습니다.'}
    try:
        payload = workflow.build_share_payload(wf)
    except Exception as exc:
        return {'error': str(exc)}
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
        return {'error': str(exc)}


def _resolve_target(target: str) -> dict[str, Any]:
    try:
        resolved = live_data.resolve_target(target)
        # 검색 결과도 일부 포함
        candidates = live_data.search_target_candidates(target, limit=5)
        return {'resolved': resolved, 'candidates': candidates}
    except Exception as exc:
        return {'error': str(exc)}


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


def run_chat(user_message: str, history: list[dict] | None = None) -> dict[str, Any]:
    """Gemini function-calling 채팅 한 턴 실행.

    Args:
        user_message: 사용자 입력
        history: [{'role': 'user'|'assistant', 'content': str}] 이전 대화

    Returns:
        {'reply': str, 'tool_calls': [...], 'iterations': int, 'method': 'llm'|'fallback'}
    """
    user_message = (user_message or '').strip()
    if not user_message:
        return {
            'reply': '메시지를 입력해 주세요.',
            'tool_calls': [],
            'iterations': 0,
            'method': 'fallback',
            **_response_metadata(),
        }

    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return {
            'reply': 'GEMINI_API_KEY 가 설정되지 않아 채팅을 사용할 수 없습니다. 관리자에게 문의해 주세요.',
            'tool_calls': [],
            'iterations': 0,
            'method': 'fallback',
            **_response_metadata(),
        }

    try:
        from google import genai
        from google.genai import types as gt
    except ImportError as exc:
        logger.warning(f'[chat_agent] google-genai 미설치: {exc}')
        return {'reply': 'google-genai 패키지 미설치. requirements.txt 확인 필요.', 'tool_calls': [],
                'iterations': 0, 'method': 'fallback', **_response_metadata()}

    client = genai.Client(api_key=api_key)
    model_name = os.getenv('MIROFISH_CHAT_MODEL', MODEL_DEFAULT)

    # ── Build contents ──
    contents: list[Any] = []
    for msg in (history or [])[-10:]:  # 최근 10턴만
        role = 'user' if msg.get('role') == 'user' else 'model'
        text = str(msg.get('content', ''))
        if text:
            contents.append(gt.Content(role=role, parts=[gt.Part(text=text)]))
    contents.append(gt.Content(role='user', parts=[gt.Part(text=user_message)]))

    # ── Tools ──
    fn_decls = [gt.FunctionDeclaration(**spec) for spec in FUNCTION_DECLARATIONS]
    tools = gt.Tool(function_declarations=fn_decls)

    config = gt.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[tools],
        temperature=0.3,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    tool_calls_log: list[dict[str, Any]] = []
    final_response = None
    iterations = 0

    for it in range(MAX_ITERATIONS):
        iterations = it + 1
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            logger.exception('[chat_agent] Gemini 호출 실패')
            return {
                'reply': f'AI 호출에 실패했습니다: {type(exc).__name__}',
                'tool_calls': tool_calls_log,
                'iterations': iterations,
                'method': 'llm_error',
                **_response_metadata(),
            }

        final_response = response

        # function_call 추출
        fn_call = None
        candidate_content = None
        if response.candidates and response.candidates[0].content:
            candidate_content = response.candidates[0].content
            for part in (candidate_content.parts or []):
                fc = getattr(part, 'function_call', None)
                if fc and getattr(fc, 'name', None):
                    fn_call = fc
                    break

        if not fn_call:
            break

        # 도구 실행
        fn_name = fn_call.name
        fn_args = dict(fn_call.args) if fn_call.args else {}
        if fn_name not in TOOL_REGISTRY:
            tool_result: Any = {'error': f'unknown_tool: {fn_name}'}
        else:
            try:
                tool_result = TOOL_REGISTRY[fn_name](**fn_args)
            except Exception as exc:
                logger.exception(f'[chat_agent] tool {fn_name} failed')
                tool_result = {'error': f'{type(exc).__name__}: {exc}'}

        # 로그 기록 (UI 표시용)
        try:
            preview = json.dumps(tool_result, ensure_ascii=False, default=str)
        except Exception:
            preview = str(tool_result)
        tool_calls_log.append({
            'name': fn_name,
            'args': fn_args,
            'result_preview': preview[:600],
        })

        # 다음 턴에 function call + response 전달
        contents.append(candidate_content)
        wrapped = tool_result if isinstance(tool_result, dict) else {'value': tool_result}
        contents.append(gt.Content(
            role='user',
            parts=[gt.Part(function_response=gt.FunctionResponse(name=fn_name, response=wrapped))],
        ))

    # ── 최종 텍스트 추출 ──
    text_chunks: list[str] = []
    if final_response and final_response.candidates:
        for part in (final_response.candidates[0].content.parts or []):
            t = getattr(part, 'text', None)
            if t:
                text_chunks.append(t)
    reply = ''.join(text_chunks).strip()
    if not reply:
        reply = '도구는 호출했지만 응답이 비어 있습니다.' if tool_calls_log else '응답이 없습니다.'

    return {
        'reply': reply,
        'tool_calls': tool_calls_log,
        'iterations': iterations,
        'method': 'llm',
        **_response_metadata(),
    }
