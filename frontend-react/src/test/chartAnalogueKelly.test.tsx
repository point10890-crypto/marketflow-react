import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ChartAnalogueKellyPanel, { ChartAnalogueKellyReportView } from '@/components/aibain/ChartAnalogueKellyPanel';
import { fetchChartAnalogueKelly, startChartAnalogueKelly, validateChartAnalogueKellyReport, type ChartAnalogueKellyReport } from '@/lib/chartAnalogueKellyApi';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
const input = Array.from({ length: 64 }, (_, index) => 80 + index * 20 / 63);
const metric = { sample_count: 35, distinct_symbols: 8, period_start: '2008-01-01', period_end: '2016-01-01', net_win_rate_pct: 80, wilson_lower_pct: 64, payoff_ratio: 1.5, expectancy_pct: 2.4, median_pct: 3, p10_pct: -6, p90_pct: 12, median_similarity: .87 };
const candidate = {
    rank: 1, symbol: '005930', target: '삼성전자', market: 'KOSPI', market_cap: 400_000_000_000_000, universe_rank: 1,
    score: 1.8, research_status: 'stable', reasons: ['historical_stability_only'], reference_session: '2026-10-02', current_close: 60000,
    train: metric, validation: { ...metric, period_start: '2018-01-01', period_end: '2026-08-01' },
    kelly: { empirical_fraction: .7, half_fraction: .35, capped_fraction: .2, research_weight: .2, approved_weight: null, volatility_guard: false, portfolio_scale: 1 },
    chart: { query: input, cases: [{ symbol: '000660', target: 'SK하이닉스', anchor_date: '2020-01-02', entry_date: '2020-01-03', exit_date: '2020-02-03', captured_at: '2026-10-02T09:00:00Z', similarity: .92, gross_return_pct: 8, net_return_pct: 7.67, entry_close: 10000, exit_close: 10800, input, future: Array.from({ length: 21 }, (_, i) => 100 + i * .4) }] },
};
function reportFixture(): ChartAnalogueKellyReport {
    return structuredClone({
        schema_version: 1, policy_id: 'chart-analogue-kelly-v1', mode: 'research', status: 'ready',
        as_of: '2026-10-03T00:00:00Z', generated_at: '2026-10-03T00:01:00Z',
        source: { source_id: 'naver_closed_daily', price_basis: 'provider_adjusted', latest_session: '2026-10-02', captured_at: '2026-10-02T09:00:00Z', built_at: '2026-10-02T09:01:00Z' },
        universe: { ranked: 100, quality_passed: 52, processed: 52, valid: 48, stable: 3, rejected: 4, as_of: '2026-10-01', reference_symbols: 52 },
        policy: { horizon_sessions: 20, cost_bps: 33, min_samples: 30, min_similarity: .8, max_positions: 3, max_weight: .2, max_exposure: .6, min_cash: .4, kelly_fraction: .5 },
        candidates: [candidate], leaderboard: [candidate], warnings: ['retrospective_evidence_not_calibrated_probability'],
        approval: { status: 'held', reasons: ['point_in_time_vintage_unverified'], approved_exposure: 0 },
        portfolio: { research_exposure: .2, research_cash: .8 },
        forward: { decision_days: 2, matured_trades: 0, pending_trades: 3, net_win_rate_pct: null, expectancy_pct: null, independent: false },
    } as ChartAnalogueKellyReport);
}
const none = { state: 'none', processed: 0, total: 0, error: null, freshness: 'missing', started_at: null, report: null };
const done = () => ({ ...none, state: 'done', processed: 52, total: 52, freshness: 'current', report: reportFixture() });

describe('chart analogue to Kelly report API boundary', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
    it('accepts the explicit held allocation report through the protected cheap GET', async () => {
        api.fetchAuthAPI.mockResolvedValue(done());
        expect((await fetchChartAnalogueKelly('member-token')).report?.candidates[0].target).toBe('삼성전자');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/kelly', 'member-token');
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it.each([
        ['protocol', (r: ChartAnalogueKellyReport) => { r.policy_id = 'other' as ChartAnalogueKellyReport['policy_id']; }],
        ['policy', (r: ChartAnalogueKellyReport) => { r.policy.max_weight = .5; }],
        ['invented live approval', (r: ChartAnalogueKellyReport) => { r.candidates[0].kelly.approved_weight = .2 as never; }],
        ['nonfinite price', (r: ChartAnalogueKellyReport) => { r.candidates[0].current_close = Infinity; }],
        ['scope', (r: ChartAnalogueKellyReport) => { r.universe.quality_passed = 101; }],
        ['cash', (r: ChartAnalogueKellyReport) => { r.portfolio.research_cash = .5; }],
        ['weight', (r: ChartAnalogueKellyReport) => { r.candidates[0].kelly.research_weight = .21; }],
        ['stable win gate', (r: ChartAnalogueKellyReport) => { r.candidates[0].validation!.net_win_rate_pct = 59; r.candidates[0].validation!.wilson_lower_pct = 40; }],
        ['stable Wilson gate', (r: ChartAnalogueKellyReport) => { r.candidates[0].validation!.wilson_lower_pct = 59; }],
        ['stable payoff gate', (r: ChartAnalogueKellyReport) => { r.candidates[0].validation!.payoff_ratio = .9; }],
        ['stable expectancy gate', (r: ChartAnalogueKellyReport) => { r.candidates[0].validation!.expectancy_pct = -1; }],
        ['duplicate', (r: ChartAnalogueKellyReport) => { r.candidates.push(structuredClone(r.candidates[0])); }],
        ['future entry', (r: ChartAnalogueKellyReport) => { r.candidates[0].chart.cases[0].exit_date = '2027-01-01'; }],
        ['future capture', (r: ChartAnalogueKellyReport) => { r.candidates[0].chart.cases[0].captured_at = '2027-01-01T00:00:00Z'; }],
        ['independent certificate', (r: ChartAnalogueKellyReport) => { r.forward!.independent = true as never; }],
        ['gross masquerading as net', (r: ChartAnalogueKellyReport) => { r.candidates[0].chart.cases[0].net_return_pct = 8; }],
    ])('rejects %s without rendering numerical evidence', async (_, mutate) => {
        const report = reportFixture(); mutate(report);
        api.fetchAuthAPI.mockResolvedValue({ ...done(), report });
        await expect(fetchChartAnalogueKelly('member-token')).rejects.toThrow('차트·켈리 응답 형식');
    });
    it('rejects extra candidates even when all symbols are unique', () => {
        const report = reportFixture();
        report.candidates = Array.from({ length: 4 }, (_, i) => ({ ...structuredClone(candidate), rank: i + 1, symbol: String(i + 1).padStart(6, '0') })) as ChartAnalogueKellyReport['candidates'];
        expect(() => validateChartAnalogueKellyReport(report)).toThrow('차트·켈리 응답 형식');
    });
    it('sends only empty options to the fixed background POST', async () => {
        api.postAuthAPI.mockResolvedValue({ ...none, state: 'running', total: 52, started_at: '2026-10-03T00:00:00Z' });
        await startChartAnalogueKelly('member-token');
        expect(api.postAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/chart-analogue/kelly', {}, 'member-token');
    });
    it('uses the recorded post-volatility cap without applying its guard twice', () => {
        const report = reportFixture();
        Object.assign(report.candidates[0].kelly, { volatility_guard: true, capped_fraction: .1, research_weight: .1 });
        report.portfolio = { research_exposure: .1, research_cash: .9 };
        expect(validateChartAnalogueKellyReport(report).candidates[0].kelly.research_weight).toBe(.1);
    });
    it('accepts a blocked missing-index report and retains zero-ranked inspected names', () => {
        const report = reportFixture();
        report.status = 'blocked'; report.source = {}; report.candidates = [];
        report.universe = { ranked: 100, quality_passed: 52, processed: 0, valid: 0, stable: 0, rejected: {}, as_of: '2026-10-01', reference_symbols: 0 };
        report.leaderboard[0] = { ...report.leaderboard[0], rank: 0, research_status: 'insufficient', reference_session: null, current_close: null, train: null, validation: null,
            kelly: { empirical_fraction: null, half_fraction: null, capped_fraction: null, research_weight: 0, approved_weight: null, volatility_guard: false, portfolio_scale: 1 }, chart: { query: [], cases: [] } };
        report.portfolio = { research_exposure: 0, research_cash: 1 };
        expect(validateChartAnalogueKellyReport(report).leaderboard[0].target).toBe('삼성전자');
    });
});

describe('chart analogue to Kelly evidence and scenario UI', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
    afterEach(() => { vi.useRealTimers(); });
    it('shows actual stock, held approval, validation and proportional scenario amount distinctly', async () => {
        const onSelect = vi.fn();
        render(<ChartAnalogueKellyReportView report={reportFixture()} onSelect={onSelect} />);
        const card = screen.getByRole('article', { name: /삼성전자/ });
        expect(card).toHaveTextContent('005930');
        expect(card).toHaveTextContent('80.0%');
        expect(card).toHaveTextContent('64.0%');
        expect(card).toHaveTextContent('20.0%');
        expect(card).toHaveTextContent('2,000,000원');
        expect(card).toHaveTextContent('미승인');
        expect(screen.getByText(/최종 투자 승인 보류/)).toBeInTheDocument();
        expect(screen.getByRole('img', { name: /삼성전자.*과거/ })).toBeInTheDocument();
        expect(screen.getByText(/33bp/)).toBeInTheDocument();
        await userEvent.click(within(card).getByRole('button', { name: /상세 차트/ }));
        expect(onSelect).toHaveBeenCalledWith('005930');
        fireEvent.change(screen.getByLabelText('시나리오 자산 금액'), { target: { value: '20000000' } });
        expect(card).toHaveTextContent('4,000,000원');
    });
    it('shows a watch stock even when no research capital may be allocated', () => {
        const report = reportFixture();
        report.candidates[0].research_status = 'watch';
        report.candidates[0].reasons = ['validation_samples_below_minimum'];
        report.candidates[0].kelly.research_weight = 0;
        report.portfolio = { research_exposure: 0, research_cash: 1 };
        render(<ChartAnalogueKellyReportView report={report} />);
        const card = screen.getByRole('article', { name: /삼성전자/ });
        expect(card).toHaveTextContent('관찰');
        expect(card).toHaveTextContent('0.0%');
        expect(card).toHaveTextContent('0원');
        expect(card).toHaveTextContent('검증 표본');
    });
    it('keeps missing returns pending rather than manufacturing a win rate', () => {
        const report = reportFixture();
        report.status = 'blocked'; report.candidates = []; report.leaderboard = [];
        report.portfolio = { research_exposure: 0, research_cash: 1 };
        render(<ChartAnalogueKellyReportView report={report} />);
        expect(screen.getByText(/표시할 연구 후보가 없습니다/)).toBeInTheDocument();
        expect(screen.getByText(/전향 관측.*대기/)).toBeInTheDocument();
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('loads saved result only and preserves the old screen while a new scan runs', async () => {
        api.fetchAuthAPI.mockResolvedValue(done());
        api.postAuthAPI.mockResolvedValue({ ...none, state: 'running', processed: 1, total: 52, freshness: 'stale', started_at: '2026-10-03T00:00:00Z' });
        render(<ChartAnalogueKellyPanel token="member-token" />);
        await screen.findByRole('article', { name: /삼성전자/ });
        expect(api.postAuthAPI).not.toHaveBeenCalled();
        await userEvent.click(screen.getByRole('button', { name: '차트·켈리 검사' }));
        expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByText(/이전 결과/)).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('1 / 52');
    });
    it('polls only running work and stops timers on unmount', async () => {
        vi.useFakeTimers();
        api.fetchAuthAPI.mockResolvedValue({ ...none, state: 'running', total: 52, started_at: '2026-10-03T00:00:00Z' });
        const view = render(<ChartAnalogueKellyPanel token="member-token" />);
        await act(async () => {});
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
        view.unmount();
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
    });
    it('does not render a late prior-token result after a token change', async () => {
        let resolveOld!: (value: unknown) => void;
        api.fetchAuthAPI.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; })).mockResolvedValueOnce(none);
        const view = render(<ChartAnalogueKellyPanel token="old-token" />);
        view.rerender(<ChartAnalogueKellyPanel token="new-token" />);
        await screen.findByText(/저장된 차트·켈리 결과가 없습니다/);
        await act(async () => { resolveOld(done()); });
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('allows safe retry after a failed read without leaking server error strings', async () => {
        api.fetchAuthAPI.mockRejectedValueOnce(new Error('secret-path')).mockResolvedValueOnce(done());
        render(<ChartAnalogueKellyPanel />);
        expect(await screen.findByRole('alert')).not.toHaveTextContent('secret-path');
        await userEvent.click(screen.getByRole('button', { name: '다시 조회' }));
        expect(await screen.findByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
    });
});
