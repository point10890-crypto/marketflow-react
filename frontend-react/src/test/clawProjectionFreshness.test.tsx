import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KrClawPage from '@/pages/dashboard/kr/claw/KrClawPage';
import ClawLiveCard from '@/pages/dashboard/aibain/ClawLiveCard';
import { ClawBrandBar } from '@/components/claw/ClawHero';

const mocks = vi.hoisted(() => ({ fetch: vi.fn(), refresh: null as (() => Promise<void>) | null }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: mocks.fetch }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'test', user: null }) }));
vi.mock('@/hooks/useAutoRefresh', () => ({ useAutoRefresh: (fn: () => Promise<void>) => { mocks.refresh = fn; } }));
vi.mock('@/components/claw/ClawAsciiBackdrop', () => ({ default: () => null }));

const overview = {
    generated_at: '2026-11-03T03:00:00Z', errors: {},
    projection: { state: 'stale', stale: true, refreshing: true, age_seconds: 30, cached_at: '2026-11-03T03:00:00Z', last_attempt_at: null, last_error: null, retry_after_seconds: 5 },
    loop: { state: 'running' as const, market_open: true, heartbeat_age_s: 3, heartbeat_state: 'running', last_tick_ts: '2026-11-03T03:00:00Z', source: 'file', source_age_s: 4 },
    regime: { regime: 'NEUTRAL', gate_status: 'YELLOW', gate_score: 54, gate_age_hours: 2, breadth_pct: 61, leader_count: 1, halt: false, reasons: [] },
    leaders: { snapshot_ts: '2026-11-03T03:00:00Z', market_status: 'open', source: 'file', by_grade: { S: 1 }, error: null,
        rows: [{ code: '005930', name: '확인된종목', grade: 'S', score: 71, chg: 1.2, trval_eok: 38, since_ts: null, today_event: null }] },
    events: { day: '20261103', counts: {}, items: [] }, briefs: { items: [] },
    system: { snapshots_today: 12, events_today: 0, briefs_today: 0, briefs_delivered_today: 0, kis_calls_today: 0, db_bytes: 1024, drop_confirm_ticks: 3, delivery: { enabled: false, mode: 'direct-dm', token_key: '', configured: false }, kill_switches: {} },
};

async function show(element: React.ReactElement) {
    await act(async () => { render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{element}</MemoryRouter>); });
}
beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-11-03T03:00:30Z'));
    mocks.fetch.mockReset();
    mocks.refresh = null;
    mocks.fetch.mockImplementation((url: string) => Promise.resolve(url.endsWith('/overview') ? overview : {}));
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('Claw cached projection freshness', () => {
    it('labels a cached running snapshot stale and never resets its heartbeat age on repeated fetches', async () => {
        await show(<KrClawPage />);
        expect(screen.getByText('Claw LIVE · STALE')).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent(/오래된 캐시/);
        expect(screen.queryByText('지금 장을 5초마다 보고 있어요.')).not.toBeInTheDocument();
        expect(screen.getAllByText(/하트비트 33s 전/).length).toBeGreaterThan(0);
        await act(async () => { vi.advanceTimersByTime(10000); await mocks.refresh!(); });
        expect(screen.getAllByText(/하트비트 43s 전/).length).toBeGreaterThan(0);
        expect(screen.getByText(/스냅샷 40s 전/)).toBeInTheDocument();
    });

    it('keeps the compact card stale with the original source age across polling', async () => {
        await show(<ClawLiveCard />);
        expect(screen.getByText('STALE')).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent(/오래된 캐시/);
        expect(screen.queryByText('실시간')).not.toBeInTheDocument();
        expect(screen.getByText(/하트비트 33s 전/)).toBeInTheDocument();
        await act(async () => { vi.advanceTimersByTime(10000); });
        expect(screen.getByText(/하트비트 43s 전/)).toBeInTheDocument();
    });

    it('does not claim live operation in the global brand bar for cached running data', async () => {
        vi.spyOn(window, 'requestAnimationFrame').mockImplementation(cb => { cb(0); return 1; });
        vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
        await show(<div className="dashboard-shell-scroll" data-testid="brand-scroller"><ClawBrandBar data={overview} /></div>);
        expect(screen.getByText('Claw LIVE · STALE')).toBeInTheDocument();
        expect(screen.queryByText('지금 장을 5초마다 보고 있어요.')).not.toBeInTheDocument();
        const banner = screen.getByTestId('claw-brand-banner');
        Object.defineProperty(banner, 'offsetTop', { value: 0 });
        Object.defineProperty(banner, 'offsetHeight', { value: 200 });
        const scroller = screen.getByTestId('brand-scroller');
        scroller.scrollTop = 220;
        fireEvent.scroll(scroller);
        // A cached "running" snapshot must remain STALE in the short mobile badge.
        expect(screen.getByTestId('claw-brand-compact')).toHaveTextContent('STALE');
        expect(screen.getByTestId('claw-brand-compact')).not.toHaveTextContent('LIVE');
        expect(screen.getByLabelText('Claw LIVE · STALE', { exact: true })).toBeInTheDocument();
    });

    it('shows unavailable observation projections explicitly when the overview is available', async () => {
        mocks.fetch.mockImplementation((url: string) => url.endsWith('/overview') ? Promise.resolve(overview) : Promise.reject(Object.assign(new Error('HTTP 503'), { status: 503 })));
        await show(<KrClawPage />);
        expect(screen.getByRole('alert')).toHaveTextContent(/관측 원장.*확인하지 못/);
        expect(screen.getByRole('button', { name: /관측.*다시 시도/ })).toBeInTheDocument();
    });

    it.each([['page', KrClawPage], ['card', ClawLiveCard]])('shows a cold 503 as an error with retry in the %s', async (_, Component) => {
        mocks.fetch.mockRejectedValue(new Error('HTTP 503'));
        await show(<Component />);
        expect(screen.getByRole('alert')).toHaveTextContent(/확인|불러오지 못/);
        expect(screen.queryByText(/데이터가 아직 없습니다|아직 스냅샷 없음/)).not.toBeInTheDocument();
        mocks.fetch.mockResolvedValue({ ...overview, projection: { ...overview.projection, stale: false, state: 'fresh' } });
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: /다시 시도/ })); });
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(screen.getAllByText('확인된종목').length).toBeGreaterThan(0);
    });
});
