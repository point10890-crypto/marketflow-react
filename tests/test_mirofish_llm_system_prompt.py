from app.services.mirofish import chat_agent
from app.services.mirofish.llm_system_prompt import (
    SYSTEM_INSTRUCTION,
    SYSTEM_PROMPT_SHA256,
    SYSTEM_PROMPT_VERSION,
    get_system_prompt_status,
)


def test_fixed_system_prompt_contains_institutional_six_agent_protocol():
    assert 'institutional-grade Korean equity market intelligence system' in SYSTEM_INSTRUCTION
    assert '6 independent specialist agents' in SYSTEM_INSTRUCTION
    assert 'Agent 3 — Capital Flow' in SYSTEM_INSTRUCTION
    assert 'Bayesian Probability Update' in SYSTEM_INSTRUCTION
    assert 'Do not fabricate missing data' in SYSTEM_INSTRUCTION
    assert 'Probability total must equal 100%' in SYSTEM_INSTRUCTION


def test_fixed_system_prompt_contains_mirofish_mcp_guardrails():
    assert 'MIROFISH MCP EXECUTION APPENDIX' in SYSTEM_INSTRUCTION
    assert 'safe read-only MCP-style tools' in SYSTEM_INSTRUCTION
    assert 'get_top3_summary' in SYSTEM_INSTRUCTION
    assert 'resolve_target' in SYSTEM_INSTRUCTION
    assert 'Never expose secrets' in SYSTEM_INSTRUCTION


def test_system_prompt_status_exposes_metadata_only():
    status = get_system_prompt_status()

    assert status['version'] == SYSTEM_PROMPT_VERSION
    assert status['sha256'] == SYSTEM_PROMPT_SHA256
    assert len(status['sha256']) == 64
    assert status['agent_count'] == 6
    assert status['full_prompt_exposed'] is False
    assert 'prompt' not in status


def test_chat_agent_registers_prompt_status_tool_and_response_metadata(monkeypatch):
    tool_names = {item['name'] for item in chat_agent.FUNCTION_DECLARATIONS}
    assert 'get_llm_system_prompt_status' in tool_names
    assert 'get_llm_system_prompt_status' in chat_agent.TOOL_REGISTRY

    tool_status = chat_agent.TOOL_REGISTRY['get_llm_system_prompt_status']()
    assert tool_status['version'] == SYSTEM_PROMPT_VERSION

    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    response = chat_agent.run_chat('이번 TOP 3 알려줘', history=[])

    assert response['method'] == 'fallback'
    assert response['prompt_version'] == SYSTEM_PROMPT_VERSION
    assert response['prompt_hash'] == SYSTEM_PROMPT_SHA256[:12]
