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

from app.services.mirofish import autonomous_mcp, live_data, workflow

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
MAX_OUTPUT_TOKENS = 2048
MODEL_DEFAULT = 'gemini-2.5-flash'


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
]


SYSTEM_INSTRUCTION = """당신은 MarketFlow MiroFish 의 AI 분석 어시스턴트입니다.

응답 규칙:
- 한국어로 자연스럽게 답변합니다 (존댓말).
- 데이터가 필요한 질문은 제공된 도구를 호출해 실제 결과를 가져와 답변합니다.
- 도구 결과에 데이터가 없으면 솔직하게 "아직 분석이 없습니다" 같은 안내.
- 결과는 간결하게 요약 — 긴 JSON 그대로 노출 X.
- 시장 데이터 / 종목 추천 / 예측 같은 질문에는 항상 도구로 사실 확인.
- 사용자 인사 / 기능 안내 등은 도구 호출 없이 직접 답변.

추천 사용 패턴:
- "오늘 TOP 3 알려줘" → get_top3_summary 호출 후 한 줄 요약
- "시장 열려?" → get_market_clock
- "삼성전자 분석 정보" → resolve_target 으로 심볼 확인 + 최근 분석 있는지 확인
- "지난 워크플로우 5개" → list_recent_workflows(limit=5)
- "카톡 공유 정보 줘" → get_workflow_share

도구 호출 후 결과를 반드시 사용자 친화적 한국어로 정리해서 답변하세요.
"""


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
        return {'reply': '메시지를 입력해 주세요.', 'tool_calls': [], 'iterations': 0, 'method': 'fallback'}

    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not api_key:
        return {
            'reply': 'GEMINI_API_KEY 가 설정되지 않아 채팅을 사용할 수 없습니다. 관리자에게 문의해 주세요.',
            'tool_calls': [],
            'iterations': 0,
            'method': 'fallback',
        }

    try:
        from google import genai
        from google.genai import types as gt
    except ImportError as exc:
        logger.warning(f'[chat_agent] google-genai 미설치: {exc}')
        return {'reply': 'google-genai 패키지 미설치. requirements.txt 확인 필요.', 'tool_calls': [],
                'iterations': 0, 'method': 'fallback'}

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
    }
