import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ScannerEventsCard from '@/components/admin/ScannerEventsCard';

const mockApi = vi.hoisted(() => ({
  getScannerMonitorStatus: vi.fn(),
  getScannerAlertState: vi.fn(),
  getScannerTradingAgentsHistory: vi.fn(),
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
    mockApi.getScannerTradingAgentsHistory.mockResolvedValue({ records: [], count: 0 });
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

  it('adds a matching verified DeepSeek brief to the cached scanner card', async () => {
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 1 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [cachedEvent] });

    render(<ScannerEventsCard fallbackEvents={[{
      ...cachedEvent,
      deepseek_brief: 'BUY 82% · 거래량과 추세가 함께 개선되고 있습니다.',
    }]} />);

    expect(await screen.findByText(/거래량과 추세가 함께 개선되고 있습니다/)).toBeInTheDocument();
    expect(screen.getByText('DeepSeek')).toBeInTheDocument();
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

  it('enriches a scanner event from the TradingAgents history endpoint', async () => {
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 1 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [cachedEvent] });
    mockApi.getScannerTradingAgentsHistory.mockResolvedValue({
      count: 1,
      records: [{
        event_key: '096770:BUY_CANDIDATE:2026-07-17',
        symbol: cachedEvent.symbol,
        detected_at: cachedEvent.sent_at,
        verdict: 'BUY',
        confidence: 78,
        strong_buy: false,
      }],
    });

    render(<ScannerEventsCard />);

    expect(await screen.findByText(/13D 딥검증 · 매매의견 매수/)).toBeInTheDocument();
    expect(screen.getByText(/78%/)).toBeInTheDocument();
  });

  it('shows an explicit pending opinion while 13D verification is unavailable', async () => {
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 1 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [cachedEvent] });

    render(<ScannerEventsCard />);

    expect(await screen.findByText('13D 딥검증 · 매매의견 검증 대기')).toBeInTheDocument();
  });

  it('adds the workflow TradingAgents opinion to the preserved scanner cache by symbol', async () => {
    seedCache();
    mockApi.getScannerMonitorStatus.mockResolvedValue({ last_candidate_count: 1 });
    mockApi.getScannerAlertState.mockResolvedValue({ feed_events: [] });

    render(<ScannerEventsCard fallbackEvents={[{
      ...cachedEvent,
      event_key: 'workflow:latest:096770',
      tradingagents: { verdict: 'BUY', confidence: 70, strong_buy: false },
    }]} />);

    expect(await screen.findByText(/13D 딥검증 · 매매의견 매수/)).toBeInTheDocument();
    expect(screen.getByText(/70%/)).toBeInTheDocument();
  });
});
