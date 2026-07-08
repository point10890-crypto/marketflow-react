import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AiBainDashboard from '@/pages/dashboard/aibain/AiBainDashboard';

const mockApi = vi.hoisted(() => ({
  fetchAuthAPI: vi.fn(),
}));

const mockMirofishApi = vi.hoisted(() => ({
  getScannerMonitorStatus: vi.fn(),
  getScannerAlertState: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  fetchAuthAPI: mockApi.fetchAuthAPI,
}));

vi.mock('@/lib/mirofishApi', () => ({
  mirofishApi: mockMirofishApi,
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 1, email: 'test@example.com', tier: 'pro', role: 'user', is_aibain_active: true },
    token: 't',
  }),
}));

const fullOverview = {
  generated_at: '2026-06-15T00:00:00+00:00',
  detections: {
    as_of: '2026-06-15',
    items: [
      {
        symbol: '000001',
        name: 'Alpha One',
        action: 'BUY_CANDIDATE',
        alpha_score: 88,
        risk_score: 21,
        entry_date: '2026-06-15',
      },
    ],
  },
  performance: {
    window_days: 30,
    hit_rate_pct: 46.2,
    avg_forward_return_pct: 1.8,
    false_positive_pct: 12.5,
    evaluated_count: 13,
    verified: [
      {
        symbol: '000001',
        name: 'Alpha One',
        entry_date: '2026-06-01',
        forward_return_pct: 5.2,
        hit: true,
        status: 'evaluated',
      },
    ],
  },
  learning: {
    regime_distribution: { RISK_ON: 26, NEUTRAL: 10, RISK_OFF: 4 },
    top_positive: [
      { combo: 'momentum+RISK_ON', n: 12, hit_rate: 0.75, expectancy_pct: 3.2 },
    ],
    top_negative: [
      { combo: 'event_risk+RISK_OFF', n: 8, hit_rate: 0.2, expectancy_pct: -2.1 },
    ],
    updated_at: '2026-06-15T00:00:00+00:00',
  },
};

const emptyOverview = {
  generated_at: '2026-06-15T00:00:00+00:00',
  detections: { as_of: null, items: [] },
  performance: {
    window_days: 30,
    hit_rate_pct: null,
    avg_forward_return_pct: null,
    false_positive_pct: null,
    evaluated_count: 0,
    verified: [],
  },
  learning: {
    regime_distribution: {},
    top_positive: [],
    top_negative: [],
    updated_at: null,
  },
};

describe('AiBainDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMirofishApi.getScannerMonitorStatus.mockResolvedValue({
      last_checked_at: '2026-07-08T10:38:20.679750+09:00',
      last_status: 'sent',
      last_candidate_count: 9,
      last_new_event_count: 1,
    });
    mockMirofishApi.getScannerAlertState.mockResolvedValue({
      last_sent_at: '2026-07-08T10:38:20.679750+09:00',
      last_candidate_count: 9,
      recent_sent_events: [{
        event_key: '037710:BUY_CANDIDATE:2026-07-08',
        sent_at: '2026-07-08T10:38:20.679750+09:00',
        symbol: '037710',
        display_name: '광주신세계',
        market: 'KOSPI',
        action: 'BUY_CANDIDATE',
        signal_quality: 'B',
        risk_score: 40,
        price: { current_price: 45900, change_rate: 1.2 },
      }],
    });
  });

  it('renders detections, performance and learning data after load', async () => {
    mockApi.fetchAuthAPI.mockResolvedValueOnce(fullOverview);

    render(<AiBainDashboard />);

    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());

    expect(await screen.findByText(/46.2/)).toBeTruthy();
    expect(await screen.findByText('광주신세계')).toBeTruthy();
    expect((await screen.findAllByText(/Alpha One/)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/momentum\+RISK_ON/)).toBeTruthy();
  });

  it('renders empty-state messaging when sections have no data', async () => {
    mockApi.fetchAuthAPI.mockResolvedValueOnce(emptyOverview);

    render(<AiBainDashboard />);

    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());

    expect(await screen.findByText('성과 검증 데이터를 누적 중입니다')).toBeTruthy();
    expect(await screen.findByText('학습 데이터를 누적 중입니다')).toBeTruthy();
  });
});
