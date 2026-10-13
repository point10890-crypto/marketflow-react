"""Initialize or recover the predeclared trial using saved AlphaLab sources only."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.mirofish.alpha_lab import evolution_store, service, store


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=service.ROOT)
    args = parser.parse_args(argv)
    try:
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        protocol = evolution_store.initialize(args.root, now=now)
        report = store.read_status(args.root)['report']
        if not isinstance(report, dict):
            raise ValueError('saved_report_unavailable')
        inputs = service.load_inputs(*service.resolve_inputs(args.root))
        # No historical backfill and no re-ranking of existing first decisions.
        discovery = {}
        cohort = args.root/'evolution'/'cohorts'/f"{report['latest_session']}.json"
        decision = datetime.fromisoformat(report['decision_at'].replace('Z', '+00:00'))
        declared = datetime.fromisoformat(protocol['declared_at'].replace('Z', '+00:00'))
        if decision > declared and not cohort.exists():
            discovery = service.discover_opportunities(inputs['prices_by_symbol'], names=inputs['names'],
                as_of=inputs['latest_session'], candidate_limit=100)
        status = evolution_store.refresh(args.root, inputs, report, discovery, now=now)
        print(json.dumps({key: status.get(key) for key in
            ('status', 'phase', 'protocol_hash', 'declared_at', 'window', 'reasons')}, ensure_ascii=False))
        return 0 if status.get('status') == 'ready' else 2
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'status': 'held', 'reason': 'saved_evolution_inputs_unavailable'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
