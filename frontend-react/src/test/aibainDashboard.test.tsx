import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AiBainDashboard from '@/pages/dashboard/aibain/AiBainDashboard';

const mockApi = vi.hoisted(() => ({
  fetchAuthAPI: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  fetchAuthAPI: mockApi.fetchAuthAPI,
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
        rs_rating: 92,
        entry_date: '2026-06-15',
        tradingagents: { verdict: 'STRONG_BUY', confidence: 85, strong_buy: true },
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
  });

  it('renders a slim dashboard: hit-rate, Top 3 detection with verdict badge, and learning one-liner', async () => {
    const user = userEvent.setup();
    mockApi.fetchAuthAPI.mockResolvedValueOnce(fullOverview).mockResolvedValueOnce(null);

    render(<AiBainDashboard />);

    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());

    // header trust chip + performance band both show hit rate
    expect((await screen.findAllByText(/46.2/)).length).toBeGreaterThan(0);
    // main hero: detected stock + verdict badge + mono meta line
    expect((await screen.findAllByText(/Alpha One/)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/매수 유력/)).toBeTruthy();
    expect(await screen.findByText(/RS 92 주도주/)).toBeTruthy();
    expect(screen.queryByText(/momentum\+RISK_ON/)).toBeNull();
    await user.click(screen.getByRole('button', { name: /상세 분석/ }));
    // learning signal preserved as a single footer line
    expect(await screen.findByText(/momentum\+RISK_ON/)).toBeTruthy();
    // the live scanner feed (30s polling) is removed from the subscriber view
    expect(screen.queryByText('광주신세계')).toBeNull();
    expect(screen.queryByText('알파 스캐너 신규 이벤트')).toBeNull();
  });

  it('renders empty-state messaging when sections have no data', async () => {
    const user = userEvent.setup();
    mockApi.fetchAuthAPI.mockResolvedValueOnce(emptyOverview).mockResolvedValueOnce(null);

    render(<AiBainDashboard />);

    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());

    expect(await screen.findByText('오늘 신규 검출이 없습니다')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /상세 분석/ }));
    expect(await screen.findByText('성과 검증 데이터를 누적 중입니다')).toBeTruthy();
  });
});
