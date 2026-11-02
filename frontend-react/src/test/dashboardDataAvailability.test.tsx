import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DashboardClient from '@/pages/dashboard/DashboardClient';
import { PullToRefreshProvider } from '@/components/layout/PullToRefreshProvider';

const api = vi.hoisted(() => ({
    briefing: vi.fn(), gate: vi.fn(), dominance: vi.fn(), vcpKr: vi.fn(), vcpUs: vi.fn(),
    vcpCrypto: vi.fn(), jongga: vi.fn(), leading: vi.fn(), wave: vi.fn(), aiBriefing: vi.fn(),
    indices: vi.fn(), aiChart: vi.fn(), usAiChart: vi.fn(), community: vi.fn(),
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: null }) }));
vi.mock('@/hooks/useAutoRefresh', () => ({ useSmartRefresh: () => {} }));
vi.mock('@/lib/api', () => ({
    usAPI: { getMarketBriefing: api.briefing, getVCPEnhanced: api.vcpUs, getAIChartAnalysis: api.usAiChart },
    krAPI: { getMarketGate: api.gate, getVCPEnhanced: api.vcpKr, getLeadingStocks: api.leading, getAIChartAnalysis: api.aiChart },
    cryptoAPI: { getDominance: api.dominance, getVCPEnhanced: api.vcpCrypto },
    jonggaAPI: { getTodaySummary: api.jongga }, waveAPI: { getDashboard: api.wave },
    briefingAPI: { getLatest: api.aiBriefing }, commonAPI: { getMarketIndices: api.indices },
    communityAPI: { getSummary: api.community },
}));

const initialData = { briefing: null, krGate: null, cryptoDom: null };
const refreshRef = { current: null as (() => Promise<void>) | null };
function show(data = initialData) {
    return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <PullToRefreshProvider onRefreshRef={refreshRef}>
            <DashboardClient initialData={data} />
        </PullToRefreshProvider>
    </MemoryRouter>);
}
const krCard = () => screen.getByRole('link', { name: /KR Market/ });
const vcpCard = () => screen.getByRole('link', { name: /VCP 강화/ });

beforeEach(() => {
    vi.resetAllMocks();
    refreshRef.current = null;
    api.briefing.mockResolvedValue({ vix: { value: 17.25, level: 'LOW' }, fear_greed: { score: 61 } });
    api.gate.mockResolvedValue({ score: 77, label: '검증된 게이트' });
    api.dominance.mockResolvedValue({ btc_price: 98000, btc_rsi: 57, sentiment: 'Neutral' });
    api.vcpKr.mockResolvedValue({ signals: [{ symbol: '005930', name: '검증VCP', score: 81 }] });
    api.vcpUs.mockResolvedValue({ signals: [] });
    api.vcpCrypto.mockResolvedValue({ signals: [] });
    api.jongga.mockResolvedValue({ top_signal: null, by_grade: {} });
    api.leading.mockResolvedValue({ results: [{ symbol: '000660', name: '선행검증', grade: 'S', score: { total: 89 }, change_pct: 1.2 }], by_grade: { S: 1 } });
    api.wave.mockResolvedValue({ summary: { active: 0 }, active_signals: [] });
    api.aiBriefing.mockResolvedValue({ type: 'morning', title: '확인된 시장 브리핑', summary: '확인된 요약', key_events: [] });
    api.indices.mockResolvedValue({ indices: [], updated_at: 1 });
    api.aiChart.mockResolvedValue({ signals: [], summary: { total: 0 } });
    api.usAiChart.mockResolvedValue({ signals: [], summary: { total: 0 } });
    api.community.mockResolvedValue({ total_posts: 23, today_posts: 2, pending_purchases: 0 });
});
afterEach(cleanup);

describe('dashboard data availability', () => {
    it('renders resolved sources while a separate source is still pending', async () => {
        api.community.mockReturnValue(new Promise(() => {}));
        show();
        expect(await screen.findByRole('heading', { name: '확인된 시장 브리핑' })).toBeInTheDocument();
        expect(within(krCard()).getByText('77')).toBeInTheDocument();
        expect(within(vcpCard()).getByText('검증VCP')).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent(/커뮤니티.*불러오는 중/);
    });

    it('shows leading-stock evidence before the independent closing-bet request finishes', async () => {
        api.jongga.mockReturnValue(new Promise(() => {}));
        show();
        expect(await screen.findByRole('link', { name: /주도주LIVE.*선행검증/ })).toBeInTheDocument();
        expect(screen.queryByText('아직 시그널 없음')).not.toBeInTheDocument();
    });

    it('keeps last successful values on a 503 refresh and recovers through retry', async () => {
        show();
        await waitFor(() => expect(within(krCard()).getByText('77')).toBeInTheDocument());
        api.gate.mockRejectedValueOnce(new Error('HTTP 503'));
        await act(async () => { await refreshRef.current!(); });
        expect(within(krCard()).getByText('77')).toBeInTheDocument();
        expect(screen.getByRole('alert')).toHaveTextContent(/한국 시장.*확인하지 못/);
        api.gate.mockResolvedValue({ score: 88, label: '재확인된 게이트' });
        fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }));
        await waitFor(() => expect(within(krCard()).getByText('88')).toBeInTheDocument());
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('shares the current refresh across overlapping pull and version triggers', async () => {
        api.community.mockReturnValue(new Promise(() => {}));
        show();
        await act(async () => { void refreshRef.current!(); void refreshRef.current!(); });
        for (const request of Object.values(api)) expect(request).toHaveBeenCalledTimes(1);
    });

    it('does not display missing first-load data as zero counts or synthetic scores, and can retry', async () => {
        for (const request of Object.values(api)) request.mockRejectedValueOnce(new Error('HTTP 503'));
        show();
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(within(krCard()).queryByText('0')).not.toBeInTheDocument();
        expect(vcpCard()).not.toHaveTextContent('0');
        const observation = screen.getByRole('region', { name: '관찰 강도 지수' });
        expect(observation).toHaveTextContent('데이터 확인 필요');
        expect(observation).not.toHaveTextContent(/KR 0|US 50|Crypto 50/);
        fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }));
        expect(await screen.findByRole('heading', { name: '확인된 시장 브리핑' })).toBeInTheDocument();
        await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    });

    it('removes stale leading and VCP signals instead of retaining them as fresh', async () => {
        show();
        await screen.findAllByText('선행검증');
        expect(within(vcpCard()).getByText('검증VCP')).toBeInTheDocument();
        api.leading.mockResolvedValue({ results: [{ name: '오래된주도주' }], metadata: { freshness: { is_stale: true } } });
        api.vcpKr.mockResolvedValue({ signals: [{ symbol: '005930', name: '오래된VCP' }], freshness: { is_stale: true } });
        await act(async () => { await refreshRef.current!(); });
        expect(screen.queryByText('선행검증')).not.toBeInTheDocument();
        expect(screen.queryByText('오래된주도주')).not.toBeInTheDocument();
        expect(screen.queryByText('검증VCP')).not.toBeInTheDocument();
        expect(screen.queryByText('오래된VCP')).not.toBeInTheDocument();
    });
});
