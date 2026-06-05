from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_multi_agent_template_structure_exists():
    expected = [
        'multi_agent/CLAUDE.md',
        'multi_agent/_shared/routing.md',
        'multi_agent/_shared/approval-policy.md',
        'multi_agent/_shared/orchestrator-rules.md',
        'multi_agent/_shared/learnings.md',
        'multi_agent/_templates/task.md',
        'multi_agent/_templates/context.md',
        'multi_agent/_templates/worker-brief.md',
        'multi_agent/_templates/worker-result.md',
        'multi_agent/_templates/log.md',
        'multi_agent/_templates/task-folder.md',
    ]

    for rel_path in expected:
        path = REPO_ROOT / rel_path
        assert path.exists(), rel_path
        assert path.read_text(encoding='utf-8').strip()


def test_multi_agent_rules_keep_alpha_detection_primary():
    text = (REPO_ROOT / 'multi_agent' / 'CLAUDE.md').read_text(encoding='utf-8')

    assert 'alpha candidate detection' in text
    assert 'MCP, Hermes, GraphRAG' in text
    assert 'not the objective by themselves' in text
    assert 'Do not execute broker orders' in text
