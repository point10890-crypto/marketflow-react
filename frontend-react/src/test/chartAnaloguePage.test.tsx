import { act, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnaloguePage from '@/pages/dashboard/aibain/ChartAnaloguePage';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: api.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'member-token' }) }));

const ready = {
    symbol: '003690', target: '코리안리', status: 'ready', mode: 'shadow',
    model_version: 'chart-analogue-v1', as_of: '2026-10-01T00:00:00Z', lookback_sessions: 252,
    sample_count: 20,
    source: { name: 'daily_prices.csv', source_id: 'local_daily_prices', latest_session: '2026-09-30',
        captured_at: '2026-09-30T09:00:00Z', built_at: '2026-09-30T10:00:00Z',
        price_basis: 'unadjusted', rows: 20000, symbols: 100, freshness_days: 1 },
    diagnostics: { eligible_windows: 200, rejected: {}, latest_session: '2026-09-30', freshness_days: 1 },
    history: [{ date: '2026-09-29', close: 9500 }, { date: '2026-09-30', close: 10000 }],
    horizons: [
        { sessions: 5, median_return_pct: 2, p10_return_pct: -4, p90_return_pct: 8, up_frequency_pct: 60,
            median_price: 10200, lower_price: 9600, upper_price: 10800 },
        { sessions: 20, median_return_pct: 4, p10_return_pct: -8, p90_return_pct: 16, up_frequency_pct: 65,
            median_price: 10400, lower_price: 9200, upper_price: 11600 },
        { sessions: 40, median_return_pct: 6, p10_return_pct: -12, p90_return_pct: 24, up_frequency_pct: 70,
            median_price: 10600, lower_price: 8800, upper_price: 12400 },
    ],
    fan: [{ session: 0, median_price: 10000, p10_price: 10000, p90_price: 10000 },
        { session: 5, median_price: 10200, p10_price: 9600, p90_price: 10800 },
        { session: 20, median_price: 10400, p10_price: 9200, p90_price: 11600 },
        { session: 40, median_price: 10600, p10_price: 8800, p90_price: 12400 }],
    neighbors: [{ symbol: '005930', target: '삼성전자', start_date: '2024-01-02', end_date: '2024-12-30',
        outcome_end_date: '2025-03-03', captured_at: '2025-03-03T09:00:00Z', similarity: 0.91,
        returns: { '5': 3, '20': -2, '40': 8 } }],
    warnings: ['raw_price_corporate_action_uncertainty', 'Samples can share market regimes and are not statistically independent.'],
};

function renderPage(path = '/dashboard/ai-bain/chart-predict') {
    return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <ChartAnaloguePage />
    </MemoryRouter>);
}

describe('historical chart analogue member page', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); });

    it('renders real history, empirical horizons and dated neighbors with provenance', async () => {
        api.fetchAuthAPI.mockResolvedValue(ready);
        renderPage();
        expect(await screen.findByRole('heading', { name: /코리안리/ })).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: '종목 코드' })).toHaveValue('003690');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/003690', 'member-token');
        expect(screen.getByText(/daily_prices.csv/)).toBeInTheDocument();
        expect(screen.getByText(/표본 20개/)).toBeInTheDocument();
        expect(screen.getByText(/보정된 상승 확률이 아닙니다/)).toBeInTheDocument();
        expect(screen.getByText(/실제 후보 순위에는 반영하지 않습니다/)).toBeInTheDocument();
        expect(screen.getByText(/통계적으로 독립된 표본이 아닙니다/)).toBeInTheDocument();
        const chart = screen.getByRole('img', { name: /과거 종가와 유사 사례/ });
        expect(chart.querySelector('[data-series="history"]')).toHaveAttribute('points', expect.stringMatching(/\d/));
        expect(chart.querySelector('[data-series="fan-band"]')).toHaveAttribute('points', expect.stringMatching(/\d/));
        expect(chart.innerHTML).not.toMatch(/NaN|Infinity/);
        const stats = screen.getByRole('table', { name: '유사 사례의 기간별 관측 결과' });
        expect(within(stats).getByText('5거래일')).toBeInTheDocument();
        expect(within(stats).getByText('60.0%')).toBeInTheDocument();
        expect(within(stats).getByText('10,200원')).toBeInTheDocument();
        expect(within(stats).getByText('-4.0% ~ +8.0%')).toBeInTheDocument();
        expect(screen.getByRole('table', { name: '과거 유사 사례' })).toHaveTextContent('삼성전자');
        expect(screen.getByRole('table', { name: '과거 유사 사례' })).toHaveTextContent('2025-03-03');
        await userEvent.click(screen.getByText('차트 수치 보기'));
        expect(screen.getByRole('table', { name: '차트의 원본 수치' })).toHaveTextContent('9,500원');
    });

    it('reads a linked symbol and shows only its returned target', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, symbol: '005930', target: '삼성전자' });
        renderPage('/dashboard/ai-bain/chart-predict?code=005930');
        expect(await screen.findByRole('heading', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByRole('textbox', { name: '종목 코드' })).toHaveValue('005930');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/005930', 'member-token');
    });

    it('identifies a preserved price snapshot with the original target capture time', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, source: { ...ready.source,
            query_collection_status: 'cache_preserved', query_captured_at: '2026-09-29T08:00:00Z' } });
        renderPage();
        expect(await screen.findByText(/이전 정상 스냅샷을 사용합니다/)).toBeInTheDocument();
        expect(screen.getByText('2026-09-29 08:00:00 UTC')).toBeInTheDocument();
    });

    it('shows unavailable pre-capture history when the target capture is null', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, status: 'insufficient_history',
            source: { ...ready.source, query_captured_at: null }, history: [], horizons: [], fan: [], neighbors: [] });
        renderPage();
        expect(await screen.findByText('가격 이력이 부족합니다')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).toBeNull();
    });

    it('shows the supplied adjusted price basis without a raw-price claim', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, warnings: [], source: {
            ...ready.source, source_id: 'naver_closed_daily', price_basis: 'provider_adjusted',
        } });
        renderPage();
        expect(await screen.findByRole('heading', { name: /코리안리/ })).toBeInTheDocument();
        expect(screen.getByText('공급자 수정주가 · 확정 일봉')).toBeInTheDocument();
        expect(screen.queryByText(/수정 전 가격/)).toBeNull();
    });

    it('validates a six digit code before sending another request', async () => {
        api.fetchAuthAPI.mockResolvedValue(ready);
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('textbox', { name: '종목 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, 'BAD');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(screen.getByRole('alert')).toHaveTextContent('6자리');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });

    it('shows loading without inventing a chart', () => {
        api.fetchAuthAPI.mockReturnValue(new Promise(() => {}));
        renderPage();
        expect(screen.getByRole('status')).toHaveTextContent('조회 중');
        expect(screen.queryByRole('img', { name: /과거 종가/ })).toBeNull();
    });

    it('allows retry after a failed read', async () => {
        api.fetchAuthAPI.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(ready);
        renderPage();
        expect(await screen.findByRole('alert')).toHaveTextContent('불러오지 못했습니다');
        await userEvent.click(screen.getByRole('button', { name: '다시 조회' }));
        expect(await screen.findByRole('heading', { name: /코리안리/ })).toBeInTheDocument();
    });

    it.each([
        ['missing_index', '과거 사례 색인이 준비되지 않았습니다'],
        ['stale_data', '가격 데이터가 오래되었습니다'],
        ['insufficient_history', '가격 이력이 부족합니다'],
        ['insufficient_analogues', '유사 사례 표본이 부족합니다'],
        ['unavailable', '현재 유사 사례 분석을 사용할 수 없습니다'],
    ])('shows %s honestly even if an old distribution was included', async (status, text) => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, status });
        renderPage();
        expect(await screen.findByText(text)).toBeInTheDocument();
        expect(screen.queryByRole('img', { name: /과거 종가/ })).toBeNull();
        expect(screen.queryByRole('table', { name: '유사 사례의 기간별 관측 결과' })).toBeNull();
    });

    it.each([
        { ...ready, history: [{ date: '2026-09-30', close: NaN }] },
        { ...ready, source: { ...ready.source, name: { unexpected: 'object' } } },
        { ...ready, fan: [{ ...ready.fan[0], p90_price: Infinity }, ready.fan[1]] },
        { ...ready, symbol: '005930' },
    ])('rejects nonfinite or malformed response values instead of plotting them %#', async (response) => {
        api.fetchAuthAPI.mockResolvedValue(response);
        renderPage();
        expect(await screen.findByRole('alert')).toHaveTextContent('응답 형식');
        expect(screen.queryByRole('img', { name: /과거 종가/ })).toBeNull();
    });

    it('ignores a late result for the previously searched symbol', async () => {
        let finishOld!: (value: typeof ready) => void;
        api.fetchAuthAPI.mockReturnValueOnce(new Promise(resolve => { finishOld = resolve; }))
            .mockResolvedValueOnce({ ...ready, symbol: '005930', target: '삼성전자' });
        renderPage();
        const input = screen.getByRole('textbox', { name: '종목 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '005930');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('heading', { name: /삼성전자/ })).toBeInTheDocument();
        await act(async () => finishOld(ready));
        expect(screen.queryByRole('heading', { name: /코리안리/ })).toBeNull();
    });

    it('exposes the member forecast page in the shared AI Brain navigation', () => {
        render(<AiBrainServiceTabs active="scanner" />);
        const nav = screen.getByRole('navigation', { name: 'AI Brain 서비스' });
        expect(within(nav).getByRole('link', { name: /차트 유사 사례/ })).toHaveAttribute(
            'href', '/dashboard/ai-bain/chart-predict?code=003690',
        );
        expect(within(nav).getByRole('link', { name: /알파 스캐너/ })).toHaveAttribute('aria-current', 'page');
        expect(within(nav).getByRole('link', { name: /Goodrich TOP 3/ })).toHaveAttribute('href', '/dashboard/ai-bain/goodrich');
    });
});
