import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ClawLiveCard from '@/pages/dashboard/aibain/ClawLiveCard';
import { isClawOverview, renderTelegramText } from '@/lib/claw';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 1, tier: 'pro', role: 'user' }, token: 't' }) }));

const overview = {
  generated_at: '2026-08-24T10:00:00',
  errors: {},
  loop: { state: 'running', market_open: true, heartbeat_age_s: 3, heartbeat_state: null, last_tick_ts: '2026-08-24T10:00:00', source: 'file', source_age_s: 4 },
  regime: { regime: 'NEUTRAL', gate_status: 'YELLOW', gate_score: 54, gate_age_hours: 2, breadth_pct: 61, leader_count: 2, halt: false, reasons: [] },
  leaders: {
    snapshot_ts: '2026-08-24T10:00:00', market_status: 'open', source: 'file', by_grade: { S: 1, A: 1, B: 1 }, error: null,
    rows: [
      { code: '002990', name: '금호건설', grade: 'S', score: 71, chg: 29.9, trval_eok: 386, since_ts: '2026-08-24T09:41:05', today_event: { type: 'LEADER_NEW', ts: '2026-08-24T09:41:05' } },
      { code: '049080', name: '기가레인', grade: 'A', score: 61, chg: 13.7, trval_eok: 122, since_ts: null, today_event: null },
      { code: '402340', name: 'SK스퀘어', grade: 'B', score: 51, chg: -6.0, trval_eok: 10994, since_ts: null, today_event: null },
    ],
  },
  events: { day: '20260824', counts: { LEADER_NEW: 1 }, items: [{ ts: '2026-08-24T09:41:05', type: 'LEADER_NEW', code: '002990', name: '금호건설', grade_from: '', grade_to: 'S', score: 71, chg: 29.9, reported_at: '2026-08-24T09:41:06' }] },
  briefs: { items: [] },
  system: { snapshots_today: 732, events_today: 1, briefs_today: 1, briefs_delivered_today: 1, kis_calls_today: 0, db_bytes: 1024, drop_confirm_ticks: 3, delivery: { enabled: true, mode: 'direct-dm', token_key: 'TELEGRAM_CHANNEL_BOT_TOKEN', configured: true }, kill_switches: { CLAW_ENABLED: true } },
};

describe('ClawLiveCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders S/A leaders, event chips and KRX colors from the overview contract', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(overview);
    render(<MemoryRouter><ClawLiveCard /></MemoryRouter>);
    await waitFor(() => expect(screen.getAllByText('금호건설').length).toBeGreaterThanOrEqual(2)); // 주도주 행 + 이벤트 행
    expect(screen.getByText('기가레인')).toBeInTheDocument();
    expect(screen.queryByText('SK스퀘어')).not.toBeInTheDocument();      // B 등급은 압축 카드에 안 보임
    expect(screen.getByText('+29.9%')).toHaveClass('text-red-400');        // KRX 상승 = 빨강
    expect(screen.getAllByText(/NEW/).length).toBeGreaterThan(0);
    expect(screen.getByText('전체 보기')).toHaveAttribute('href', '/dashboard/kr/claw');
    expect(screen.queryByText('dry-run')).not.toBeInTheDocument();
  });

  it('degrades to a quiet placeholder when the response is not the Claw contract', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ detections: { items: [] } }); // AI Brain overview 모양
    render(<MemoryRouter><ClawLiveCard /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/백엔드 준비 중/)).toBeInTheDocument());
  });

  it('shows HALT overlay text when the loop is halted', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ ...overview, loop: { ...overview.loop, state: 'halt' }, regime: { ...overview.regime, halt: true, reasons: ['leaders source error: token'] } });
    render(<MemoryRouter><ClawLiveCard /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText(/검출 보류 중/)).toBeInTheDocument());
  });
});

describe('claw helpers', () => {
  it('isClawOverview rejects foreign shapes', () => {
    expect(isClawOverview(overview)).toBe(true);
    expect(isClawOverview({ detections: {} })).toBe(false);
    expect(isClawOverview(null)).toBe(false);
  });
  it('renderTelegramText keeps <b> bold and escapes everything else (no innerHTML)', () => {
    render(<div data-testid="t">{renderTelegramText('a <b>bold</b> <img src=x onerror=alert(1)>')}</div>);
    const el = screen.getByTestId('t');
    expect(el.querySelector('b')?.textContent).toBe('bold');
    expect(el.querySelector('img')).toBeNull();
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>');
  });
});
