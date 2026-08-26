import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import ClawObservationCard from '@/pages/dashboard/kr/claw/ClawObservationCard';
import type { ClawQuality, ClawScorecards } from '@/lib/claw';

const quality: ClawQuality = {
  schema_version: 'marketflow.claw.quality.v1',
  generated_at: '2026-08-24T12:00:00+09:00',
  status: 'ok',
  database: { path_exists: true, bytes: 1024, foreign_keys: true, schema_version: 1 },
  ledger: {
    last_write_at: '2026-08-24T11:59:00+09:00', last_error_at: null, last_error: null,
    consecutive_errors: 0, scans: 3, contexts: 3, instances: 2, state_events: 2,
  },
  outcomes: { pending: 3, complete: 1, missing: 0, data_as_of: '2026-08-21' },
  freshness: { last_scan_at: '2026-08-24T11:59:00+09:00', age_seconds: 60, stale: false },
  errors: [],
};

const scorecards: ClawScorecards = {
  schema_version: 'marketflow.claw.scorecards.v1',
  generated_at: '2026-08-24T12:00:00+09:00',
  data_as_of: '2026-08-21',
  window: { start: '2026-08-21', end: '2026-08-24' },
  coverage: { instances: 2, eligible_n: 4, complete_n: 1, pending_n: 3, missing_n: 0, ratio: 0.25 },
  horizons: [{
    horizon_sessions: 1, eligible_n: 2, complete_n: 1, pending_n: 1, missing_n: 0,
    coverage: 0.5, avg_return_pct: 1.25, positive_rate_pct: 100, status: 'insufficient', insufficient_reason: 'sample_size',
  }],
  recent_instances: [{
    id: 1, opened_at: '2026-08-24T09:12:00+09:00', code: '005930', name: '삼성전자',
    trigger_type: 'LEADER_NEW', grade: 'S', score: 88, status: 'open', structural_phase: 'leader_market',
    live_gate_status: 'GREEN', live_halt: false, outcomes: [],
  }],
  stale: false,
  insufficient: true,
  insufficient_reason: '고유 세션 부족',
  errors: [],
};

describe('ClawObservationCard', () => {
  it('shows ledger freshness and keeps insufficient outcomes explicitly shadow-only', () => {
    render(<ClawObservationCard quality={quality} scorecards={scorecards} loading={false} />);
    expect(screen.getByText('관측·검증 하네스')).toBeInTheDocument();
    expect(screen.getByText('표본 축적 중')).toBeInTheDocument();
    expect(screen.getByText('삼성전자')).toBeInTheDocument();
    expect(screen.getByText(/정책 미적용/)).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('does not render an empty admin panel for users without access', () => {
    const { container } = render(<ClawObservationCard quality={null} scorecards={null} loading={false} />);
    expect(container).toBeEmptyDOMElement();
  });
});
