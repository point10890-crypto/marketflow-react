import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ScannerEventsCard from '@/components/admin/ScannerEventsCard';

const mockApi = vi.hoisted(() => ({
  getScannerMonitorStatus: vi.fn(),
  getScannerAlertState: vi.fn(),
}));

vi.mock('@/lib/mirofishApi', () => ({
  mirofishApi: mockApi,
}));

const cacheKey = 'marketflow.mirofish.scanner-events.v1';
const cachedEvent = {
  event_key: '096770-2026-07-17',
  symbol: '096770',
  display_name: 'SK이노베이션',
  market: 'KOSPI',
  sent_at: '2026-07-17T06:00:00Z',
  action: 'BUY_CANDIDATE',
};

function seedCache() {
  window.localStorage.setItem(cacheKey, JSON.stringify({
    monitor: { last_candidate_count: 1, last_new_event_count: 1 },
    alerts: { feed_events: [cachedEvent], last_candidate_count: 1, last_new_event_count: 1 },
    cachedAt: '2026-07-17T06:01:00Z',
  }));
}

describe('ScannerEventsCard cache retention', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it('keeps the last successful event visible when refresh fails', async () => {
    seedCache();
    mockApi.getScannerMonitorStatus.mockRejectedValue(new Error('offline'));
    mockApi.getScannerAlertState.mockRejectedValue(new Error('offline'));

    render(<ScannerEventsCard />);

    expect(screen.getByText('SK이노베이션')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/마지막 정상 캐시를 유지합니다/)).toBeInTheDocument());
  });

  it('seeds the feed from the latest workflow when the scanner APIs fail on first visit', async () => {
    mockApi.getScannerMonitorStatus.mockRejectedValue(new Error('offline'));
    mockApi.getScannerAlertState.mockRejectedValue(new Error('offline'));

    render(<ScannerEventsCard fallbackEvents={[cachedEvent]} />);

    expect(await screen.findByText('SK이노베이션')).toBeInTheDocument();
    await waitFor(() => {
      const cached = JSON.parse(window.localStorage.getItem(cacheKey) || '{}');
      expect(cached.alerts.feed_events).toEqual([cachedEvent]);
    });
  });

  it('uses a successful alert response even when monitor status fails', async () => {
    mockApi.getScannerMonitorStatus.mockRejectedValue(new Error('monitor offline'));
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [cachedEvent] });

    render(<ScannerEventsCard />);

    expect(await screen.findByText('SK이노베이션')).toBeInTheDocument();
  });

  it('enriches a scanner event with the matching TradingAgents opinion', async () => {
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 1 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [cachedEvent] });

    render(<ScannerEventsCard fallbackEvents={[{
      ...cachedEvent,
      agent_opinion: 'BUY 82% · 기술적 추세와 거래량 흐름이 우호적입니다.',
      agent_verdict: 'BUY',
      agent_confidence: 82,
    }]} />);

    expect(await screen.findByText(/기술적 추세와 거래량 흐름이 우호적입니다/)).toBeInTheDocument();
    expect(screen.getByText('에이전트')).toBeInTheDocument();
  });

  it('does not erase a cached event when the server has no newer event', async () => {
    seedCache();
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 0, last_new_event_count: 0 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [], last_candidate_count: 0, last_new_event_count: 0 });

    render(<ScannerEventsCard />);

    await waitFor(() => expect(mockApi.getScannerAlertState).toHaveBeenCalled());
    expect(screen.getByText('SK이노베이션')).toBeInTheDocument();
    const cached = JSON.parse(window.localStorage.getItem(cacheKey) || '{}');
    expect(cached.alerts.feed_events).toEqual([cachedEvent]);
  });
});
