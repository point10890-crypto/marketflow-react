import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnalogueEvaluationPanel from '@/components/aibain/ChartAnalogueEvaluationPanel';
import ChartAnaloguePage from '@/pages/dashboard/aibain/ChartAnaloguePage';
import { fetchChartAnalogueEvaluation } from '@/lib/chartAnalogueApi';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: api.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'member-token' }) }));

const empty = {
    schema_version: 1, status: 'collecting', evaluated_at: null,
    protocol: 'chart_median20_v1', ranking_effect: 'none', cost_bps: 23, slippage_bps: 10,
    counts: { recorded: 0, eligible_days: 0, pending: 0, blocked: 0, intraday_excluded: 0 },
    horizons: [5, 20, 40].map(sessions => ({ sessions, paired_days: 0, pending_days: 0, blocked_days: 0,
        baseline_net_return_pct: null, challenger_net_return_pct: null, excess_return_pct: null })),
    recent: [], warnings: [],
};
const ready = {
    ...empty, status: 'ready', evaluated_at: '2026-10-12T08:00:00Z',
    counts: { recorded: 4, eligible_days: 2, pending: 1, blocked: 1, intraday_excluded: 1 },
    horizons: [
        { sessions: 5, paired_days: 2, pending_days: 0, blocked_days: 0,
            baseline_net_return_pct: 1.25, challenger_net_return_pct: 2.75, excess_return_pct: 1.5 },
        { sessions: 20, paired_days: 1, pending_days: 1, blocked_days: 0,
            baseline_net_return_pct: -0.5, challenger_net_return_pct: 1.75, excess_return_pct: 2.25 },
        { sessions: 40, paired_days: 0, pending_days: 2, blocked_days: 0,
            baseline_net_return_pct: null, challenger_net_return_pct: null, excess_return_pct: null },
    ],
    recent: [{ workflow_id: 'workflow-20261001', decision_at: '2026-10-01T07:00:00Z', status: 'eligible', reason: null,
        baseline: [{ symbol: '003690', target: '코리안리' }, { symbol: '005930', target: '삼성전자' }, { symbol: '000660', target: 'SK하이닉스' }],
        challenger: [{ symbol: '035420', target: 'NAVER' }, { symbol: '005930', target: '삼성전자' }, { symbol: '000660', target: 'SK하이닉스' }],
        horizons: [
            { sessions: 5, status: 'matured', observed_sessions: 5,
                baseline_net_return_pct: 1.25, challenger_net_return_pct: 2.75, excess_return_pct: 1.5 },
            { sessions: 20, status: 'pending', observed_sessions: 5,
                baseline_net_return_pct: null, challenger_net_return_pct: null, excess_return_pct: null },
            { sessions: 40, status: 'pending', observed_sessions: 5,
                baseline_net_return_pct: null, challenger_net_return_pct: null, excess_return_pct: null },
        ] }],
};
const forecast = {
    symbol: '003690', target: '코리안리', status: 'ready', mode: 'shadow', model_version: 'chart-v1',
    as_of: '2026-10-01T08:00:00Z', lookback_sessions: 252, sample_count: 5, source: {}, diagnostics: {},
    history: [{ date: '2026-09-30', close: 10000 }, { date: '2026-10-01', close: 10200 }],
    horizons: [5, 20, 40].map(sessions => ({ sessions, median_return_pct: 1, p10_return_pct: -1, p90_return_pct: 2,
        up_frequency_pct: 60, median_price: 10302, lower_price: 10098, upper_price: 10404 })),
    fan: [{ session: 0, median_price: 10200, p10_price: 10200, p90_price: 10200 },
        { session: 40, median_price: 10302, p10_price: 10098, p90_price: 10404 }],
    neighbors: [], warnings: [],
};

describe('prospective TOP3 comparison panel', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); });

    it('shows unrecorded collection as waiting without fabricated return zeros or picks', async () => {
        api.fetchAuthAPI.mockResolvedValue(empty);
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        expect((await screen.findAllByText('관측 대기')).length).toBeGreaterThan(0);
        expect(screen.getByText(/저장된 관측 0건/)).toBeInTheDocument();
        const table = screen.getByRole('table', { name: 'TOP3 기간별 비교 관측' });
        expect(table).not.toHaveTextContent('0.00%');
        expect(screen.queryByRole('list', { name: '최근 TOP3 비교 관측' })).toBeNull();
        expect(screen.queryByText('코리안리')).toBeNull();
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/evaluation', 'member-token');
    });

    it('displays evaluated paired days and net returns with percentage-point differences', async () => {
        api.fetchAuthAPI.mockResolvedValue(ready);
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        const table = await screen.findByRole('table', { name: 'TOP3 기간별 비교 관측' });
        const row = within(table).getByRole('row', { name: /5관측일/ });
        expect(row).toHaveTextContent('1.25%');
        expect(row).toHaveTextContent('2.75%');
        expect(row).toHaveTextContent('+1.50%p');
        const waiting = within(table).getByRole('row', { name: /40관측일/ });
        expect(waiting).toHaveTextContent('관측 대기');
        expect(waiting).not.toHaveTextContent('0.00%');
        expect(screen.getByText(/왕복 비용 23bp/)).toHaveTextContent('슬리피지 10bp');
        expect(screen.getByText(/총 0.33%/)).toBeInTheDocument();
        expect(screen.getByText(/한국시간 하루 첫 유효 관측/)).toBeInTheDocument();
        expect(screen.getByText(/실제 체결 수익이 아닙니다/)).toBeInTheDocument();
        expect(screen.getByText(/시장 지수와의 비교는 제공하지 않습니다/)).toBeInTheDocument();
        expect(screen.getByText(/2026-10-01 이전/)).toBeInTheDocument();
        const recent = screen.getByRole('list', { name: '최근 TOP3 비교 관측' });
        expect(recent).toHaveTextContent('코리안리 003690');
        expect(recent).toHaveTextContent('NAVER 035420');
        expect(recent).toHaveTextContent('2026-10-01');
    });

    it('labels partially blocked selection without exposing internal failure reasons', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...empty, counts: { ...empty.counts, recorded: 1, blocked: 1 }, recent: [{
            workflow_id: 'bad-workflow', decision_at: '2026-10-01T08:00:00+00:00',
            status: 'missing_forecasts', reason: 'FileNotFoundError: C:/private/internal',
            baseline: [{ symbol: '003690', target: '코리안리' }], challenger: [], horizons: [],
        }] });
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        const recent = await screen.findByRole('list', { name: '최근 TOP3 비교 관측' });
        expect(recent).toHaveTextContent('선정 종목·자료 부족');
        expect(recent).not.toHaveTextContent(/missing_forecasts|FileNotFoundError|private/);
        expect(recent).toHaveTextContent('선정 자료 없음');
    });

    it('retains a genuine evaluated zero instead of treating it as missing', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...ready, horizons: [
            { ...ready.horizons[0], baseline_net_return_pct: 0, challenger_net_return_pct: 0, excess_return_pct: 0 },
            ...ready.horizons.slice(1),
        ] });
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        const table = await screen.findByRole('table', { name: 'TOP3 기간별 비교 관측' });
        expect(within(table).getByRole('row', { name: /5관측일/ })).toHaveTextContent('0.00%p');
    });

    it('identifies excluded intraday decisions without calling them missing selections', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...empty, counts: { ...empty.counts, recorded: 1, intraday_excluded: 1 },
            recent: [{ ...ready.recent[0], status: 'blocked', reason: 'intraday_excluded', horizons: [] }] });
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        const recent = await screen.findByRole('list', { name: '최근 TOP3 비교 관측' });
        expect(recent).toHaveTextContent('장중 관측 제외');
        expect(recent).not.toHaveTextContent('선정 종목·자료 부족');
    });

    it('offers its own retry and keeps raw request errors out of the page', async () => {
        api.fetchAuthAPI.mockRejectedValueOnce(new Error('private internal exception')).mockResolvedValueOnce(empty);
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        expect(await screen.findByRole('alert')).toHaveTextContent('비교 관측을 불러오지 못했습니다');
        expect(screen.queryByText(/private internal/)).toBeNull();
        await userEvent.click(screen.getByRole('button', { name: '비교 관측 다시 조회' }));
        expect((await screen.findAllByText('관측 대기')).length).toBeGreaterThan(0);
    });

    it.each(['missing_index', 'stale_data'])('still loads comparison when the selected stock is %s', async status => {
        api.fetchAuthAPI.mockImplementation(async (path: string) => path.endsWith('/evaluation')
            ? ready : { ...forecast, status, horizons: [], fan: [], neighbors: [] });
        render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ChartAnaloguePage /></MemoryRouter>);
        expect(await screen.findByRole('table', { name: 'TOP3 기간별 비교 관측' })).toHaveTextContent('+1.50%p');
        expect(screen.queryByRole('img', { name: /과거 종가/ })).toBeNull();
    });

    it('does not replace a valid stock chart when comparison is unavailable', async () => {
        api.fetchAuthAPI.mockImplementation(async (path: string) => {
            if (path.endsWith('/evaluation')) throw new Error('evaluation offline');
            return forecast;
        });
        render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ChartAnaloguePage /></MemoryRouter>);
        expect(await screen.findByRole('img', { name: /과거 종가/ })).toBeInTheDocument();
        expect(await screen.findByRole('alert')).toHaveTextContent('비교 관측을');
    });

    it('shows an unavailable report without fabricated counts or returns', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...empty, status: 'unavailable' });
        render(<ChartAnalogueEvaluationPanel token="member-token" />);
        expect(await screen.findByText('비교 관측 자료를 확인할 수 없습니다')).toBeInTheDocument();
        expect(screen.queryByRole('table', { name: 'TOP3 기간별 비교 관측' })).toBeNull();
    });
});

describe('comparison API response validation', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); });

    it.each([
        { ...empty, counts: { ...empty.counts, recorded: -1 } },
        { ...empty, counts: { ...empty.counts, eligible_days: 1.5 } },
        { ...ready, evaluated_at: '2026-10-12 08:00:00' },
        { ...ready, protocol: 'another-selector' },
        { ...ready, ranking_effect: 'live' },
        { ...ready, status: ['ready'] },
        { ...ready, cost_bps: 24 },
        { ...ready, horizons: [{ ...ready.horizons[0], challenger_net_return_pct: NaN }, ...ready.horizons.slice(1)] },
        { ...empty, horizons: [{ ...empty.horizons[0], excess_return_pct: undefined }, ...empty.horizons.slice(1)] },
        { ...empty, horizons: [{ ...empty.horizons[0], excess_return_pct: 0 }, ...empty.horizons.slice(1)] },
        { ...ready, recent: [{ ...ready.recent[0], baseline: [{ symbol: 'BAD', target: '잘못된 코드' }] }] },
        { ...ready, recent: [{ ...ready.recent[0], horizons: [{ ...ready.recent[0].horizons[1], challenger_net_return_pct: 0 }] }] },
        { ...ready, recent: [{ ...ready.recent[0], horizons: [{ ...ready.recent[0].horizons[1], status: ['pending'] }] }] },
    ])('rejects invalid or invented comparison values %#', async response => {
        api.fetchAuthAPI.mockResolvedValue(response);
        await expect(fetchChartAnalogueEvaluation('member-token')).rejects.toThrow('비교 관측 응답 형식');
    });
});
