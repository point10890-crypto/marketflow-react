import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnaloguePage from '@/pages/dashboard/aibain/ChartAnaloguePage';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), fetchEvaluation: vi.fn(), fetchTop3: vi.fn(), postAuthAPI: vi.fn() }));
// Stock-flow tests keep independent global panel requests separate from symbol forecasts.
vi.mock('@/lib/api', () => ({
    fetchAuthAPI: (path: string, token?: string) => path.endsWith('/alpha-lab') ? Promise.resolve({ schema_version: 1,
        state: 'missing', generated_at: null, report: null, error: null }) : path.endsWith('/kelly') ? Promise.resolve({ state: 'none', processed: 0, total: 0, started_at: null,
        error: null, freshness: 'missing', report: null }) : path.endsWith('/evaluation') ? api.fetchEvaluation(path, token)
        : path.endsWith('/top3') ? api.fetchTop3(path, token) : api.fetchAuthAPI(path, token),
    postAuthAPI: api.postAuthAPI,
}));
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
    beforeEach(() => {
        api.fetchAuthAPI.mockReset();
        api.fetchEvaluation.mockReset();
        api.fetchTop3.mockReset();
        api.postAuthAPI.mockReset();
        api.fetchTop3.mockResolvedValue({ state: 'none', processed: 0, total: 0, started_at: null,
            error: null, freshness: 'missing', report: null });
        api.fetchEvaluation.mockResolvedValue({ schema_version: 1, status: 'collecting', evaluated_at: null,
            protocol: 'chart_median20_v1', ranking_effect: 'none', cost_bps: 23, slippage_bps: 10,
            counts: { recorded: 0, eligible_days: 0, pending: 0, blocked: 0, intraday_excluded: 0 },
            horizons: [5, 20, 40].map(sessions => ({ sessions, paired_days: 0, pending_days: 0, blocked_days: 0,
                baseline_net_return_pct: null, challenger_net_return_pct: null, excess_return_pct: null })),
            recent: [], warnings: [] });
    });

    it('renders real history, empirical horizons and dated neighbors with provenance', async () => {
        api.fetchAuthAPI.mockResolvedValue(ready);
        renderPage();
        expect(await screen.findByRole('heading', { name: /코리안리/ })).toBeInTheDocument();
        expect(screen.getByRole('combobox', { name: '종목명 또는 코드' })).toHaveValue('003690');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/003690', 'member-token');
        const autoTop3 = screen.getByRole('heading', { name: '차트 자동 TOP3' });
        const manualSearch = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        expect(autoTop3.compareDocumentPosition(manualSearch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(screen.getByText(/daily_prices.csv/)).toBeInTheDocument();
        expect(within(screen.getByRole('region', { name: '종목과 데이터 출처' })).getByText(/표본 20개/)).toBeInTheDocument();
        expect(screen.getByText(/보정된 상승 확률이 아닙니다/)).toBeInTheDocument();
        expect(screen.getByText(/기존 AI Brain 검출 순위를 변경하지 않습니다/)).toBeInTheDocument();
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
        expect(screen.getByRole('combobox', { name: '종목명 또는 코드' })).toHaveValue('005930');
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
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '123');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(screen.getByRole('alert')).toHaveTextContent('6자리');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });

    it('resolves a complete Korean name before querying its six digit chart code', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '한미반도체', candidates: [{ symbol: '042700', name: '한미반도체', market: 'KOSPI', asset_type: 'equity' }] }
            : path.endsWith('/042700') ? { ...ready, symbol: '042700', target: '한미반도체' } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '한미반도체');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('heading', { name: /한미반도체/ })).toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/042700', 'member-token');
        expect(api.fetchAuthAPI.mock.calls.some(([path]) => String(path).includes('/chart-analogue/한미'))).toBe(false);
    });

    it('shows partial-name candidates and lets the keyboard select an exact stock', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '한미', candidates: [{ symbol: '042700', name: '한미반도체' }, { symbol: '128940', name: '한미약품' }] }
            : path.endsWith('/128940') ? { ...ready, symbol: '128940', target: '한미약품' } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '한미');
        expect(await screen.findByRole('option', { name: /한미약품.*128940/ })).toBeInTheDocument();
        await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}');
        expect(await screen.findByRole('heading', { name: /한미약품/ })).toBeInTheDocument();
        expect(screen.queryByRole('listbox')).toBeNull();
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/128940', 'member-token');
    });

    it('requires a choice when a submitted partial name has several matches', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '한미', candidates: [{ symbol: '042700', name: '한미반도체' }, { symbol: '128940', name: '한미약품' }] } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '한미');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('선택');
        expect(screen.getAllByRole('option')).toHaveLength(2);
        expect(api.fetchAuthAPI.mock.calls.filter(([path]) => String(path).includes('/chart-analogue/'))).toHaveLength(1);
    });

    it('explains an unmatched name while keeping the previous valid chart', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '없는종목', candidates: [] } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '없는종목');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('검색 결과가 없습니다');
        expect(screen.getByRole('heading', { name: /코리안리/ })).toBeInTheDocument();
    });

    it('uses an exact name even when its preferred-share sibling is also returned', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '삼성전자', candidates: [{ symbol: '005930', name: '삼성전자' }, { symbol: '005935', name: '삼성전자우' }] }
            : path.endsWith('/005930') ? { ...ready, symbol: '005930', target: '삼성전자' } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '삼성전자');
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('heading', { name: /삼성전자/ })).toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/005930', 'member-token');
    });

    it('ignores candidate results for an input that has already changed', async () => {
        let finishOld!: (result: unknown) => void;
        api.fetchAuthAPI.mockImplementation((path: string) => {
            if (!path.includes('/targets/search?')) return Promise.resolve(ready);
            if (path.includes(encodeURIComponent('한미'))) return new Promise(resolve => { finishOld = resolve; });
            return Promise.resolve({ target: '삼성', candidates: [{ symbol: '005930', name: '삼성전자' }] });
        });
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '한미');
        await waitFor(() => expect(finishOld).toBeTypeOf('function'));
        await userEvent.clear(input);
        await userEvent.type(input, '삼성');
        await screen.findByRole('option', { name: /삼성전자/ });
        await act(async () => finishOld({ target: '한미', candidates: [{ symbol: '042700', name: '한미반도체' }] }));
        expect(screen.queryByRole('option', { name: /한미반도체/ })).toBeNull();
        expect(screen.getByRole('option', { name: /삼성전자/ })).toBeInTheDocument();
    });

    it('does not reopen escaped suggestions when a pending request completes', async () => {
        let finish!: (result: unknown) => void;
        api.fetchAuthAPI.mockImplementation((path: string) => path.includes('/targets/search?')
            ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        await userEvent.clear(input);
        await userEvent.type(input, '한미');
        await waitFor(() => expect(finish).toBeTypeOf('function'));
        await userEvent.keyboard('{Escape}');
        await act(async () => finish({ target: '한미', candidates: [{ symbol: '042700', name: '한미반도체' }] }));
        expect(screen.queryByRole('listbox')).toBeNull();
        expect(input).toHaveAttribute('aria-expanded', 'false');
    });

    it('cancels IME Enter defaults even after compositionend has cleared React state', async () => {
        api.fetchAuthAPI.mockResolvedValue(ready);
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        expect(fireEvent.keyDown(input, { key: 'Enter', keyCode: 229, isComposing: true })).toBe(false);
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });

    it('keeps IME composition local and resolves the completed Korean name', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/targets/search?')
            ? { target: '한미반도체', candidates: [{ symbol: '042700', name: '한미반도체' }] }
            : path.endsWith('/042700') ? { ...ready, symbol: '042700', target: '한미반도체' } : ready));
        renderPage();
        await screen.findByRole('heading', { name: /코리안리/ });
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        fireEvent.compositionStart(input);
        fireEvent.change(input, { target: { value: '한미반도체' } });
        expect(fireEvent.keyDown(input, { key: 'Enter', keyCode: 229, isComposing: true })).toBe(false);
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
        fireEvent.compositionEnd(input);
        await screen.findByRole('option', { name: /한미반도체/ });
        await userEvent.click(screen.getByRole('button', { name: '유사 사례 조회' }));
        expect(await screen.findByRole('heading', { name: /한미반도체/ })).toBeInTheDocument();
    });

    it('shows loading without inventing a chart', async () => {
        api.fetchAuthAPI.mockReturnValue(new Promise(() => {}));
        renderPage();
        await screen.findByRole('table', { name: 'TOP3 기간별 비교 관측' });
        expect(screen.getByRole('status')).toHaveTextContent('과거 유사 사례 조회 중');
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
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
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
