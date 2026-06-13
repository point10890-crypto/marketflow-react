"""One-shot deployment verification for the Alpha Brain Agent.

Runs import checks, a dry-run cycle, and confirms journal creation.
Safe: forces MIROFISH_AGENT_DRY_RUN=1 and disables Telegram brief.
"""

from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, REPO_ROOT)

# Mirror production runtime: scheduler.py / flask_app.py load .env with override.
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(REPO_ROOT, '.env'), override=True)
except Exception:
    pass

os.environ['MIROFISH_AGENT_DRY_RUN'] = '1'
os.environ['MIROFISH_AGENT_BRIEF_ENABLED'] = '0'

from app.services.mirofish import (  # noqa: E402
    agent_actions,
    alpha_brain_agent,
    edge_map,
    hypothesis_replay,
)


def main() -> int:
    print('[1] imports OK:', all([
        callable(alpha_brain_agent.run_agent_cycle),
        callable(alpha_brain_agent.get_agent_status),
        callable(edge_map.build_edge_map),
        callable(hypothesis_replay.replay_tag_delta),
        callable(agent_actions.execute_decisions),
    ]))

    from app.services.mirofish import llm_client  # noqa: E402

    provider_probe = llm_client.generate_text(
        'Reply with the single word OK.', max_tokens=8, temperature=0.0,
    )
    print('[1b] LLM provider reachable:', bool(provider_probe),
          '| order=%s' % llm_client.provider_order())

    status = alpha_brain_agent.get_agent_status()
    print('[2] status: enabled=%s dry_run=%s circuit_open=%s overrides=%s overlay=%s' % (
        status.get('enabled'),
        status.get('dry_run'),
        status.get('circuit_open'),
        status.get('active_overrides'),
        list((status.get('active_scoring_overlay') or {}).keys()),
    ))

    journal_before = len(alpha_brain_agent.read_journal_tail(9999))
    result = alpha_brain_agent.run_agent_cycle('evening')
    journal_after = len(alpha_brain_agent.read_journal_tail(9999))
    print('[3] dry-run cycle: status=%s llm=%s maintenance=%s rollbacks=%s' % (
        result.get('status'),
        (result.get('llm') or {}).get('status'),
        len(result.get('maintenance') or []),
        len(result.get('rollbacks') or []),
    ))
    print('[4] journal grew: %s -> %s entries' % (journal_before, journal_after))

    kpi = (result.get('kpi') or {})
    print('[5] KPI snapshot: evaluated=%s hit_rate=%s expR=%s IC=%s' % (
        kpi.get('evaluated_count'), kpi.get('hit_rate_recent'),
        kpi.get('backtest_expectancy_r'), kpi.get('backtest_ic'),
    ))

    ok = (
        result.get('status') in {'completed', 'skipped_circuit_open'}
        and journal_after > journal_before
    )
    print('VERIFY_RESULT', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
