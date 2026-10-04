import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { fetchAlphaLab, startAlphaLab, validateAlphaLabStatus } from '@/lib/alphaLabApi';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
const missing = { schema_version: 1, state: 'missing', generated_at: null, report: null, error: null };
function reportFixture() {
    return structuredClone({
        schema_version: 1, mode: 'research', as_of: '2026-10-04T00:00:00Z',
        universe: { ranked_count: 100, quality_count: 42, inspected_count: 42, scope_date: '2026-10-02' },
        provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
            point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
        champion: { strategy_id: 'trend', selection_basis: 'validation_only', status: 'held', reasons: ['historical_vintage_unverified'] },
        strategies: [{ strategy_id: 'trend', name: '추세 지속', validation: { trades: 35, win_rate: .6, mean_net_return: .012 },
            test: { net_total_return: .08, max_drawdown: -.04, trades: 12, win_rate: .58 },
            stress: { net_total_return: -.03, max_drawdown: -.07, trades: 8, win_rate: .375 },
            qualified: false, reasons: ['stress_gate_failed'] }],
        candidates: [{ symbol: '005930', name: '삼성전자', strategy_id: 'trend', score: .78, last_close: 60000,
            plan: { entry_price: 60000, stop_price: 57000, target_price: 66000, loss_fraction: .05 },
            risk: { weight: 0, status: 'held', reasons: ['historical_vintage_unverified'], p: .6, kelly_raw: .15 }, reasons: ['trend_strength'] }],
        agents: ['universe', 'data', 'strategy', 'validation', 'risk', 'paper'].map(id => ({ id, name: `${id} 담당`, status: 'done', detail: '근거 확인 완료' })),
        warnings: ['current_cohort_bias'], forward: { decisions: 2, matured: 0, win_rate: null, mean_net_return: null },
        protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 20,
            source_references: [{ name: '연구 방법', url: 'https://www.nber.org/papers/w11690' }] },
    });
}
const held = () => ({ ...missing, state: 'held', generated_at: '2026-10-04T00:01:00Z', report: reportFixture() });

beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('AlphaLab evidence boundary', () => {
    it('accepts saved research evidence and calls only the protected status GET', async () => {
        api.fetchAuthAPI.mockResolvedValue(held());
        expect((await fetchAlphaLab('member-token')).report?.candidates[0].symbol).toBe('005930');
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab', 'member-token');
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('starts the fixed async policy with an empty body', async () => {
        api.postAuthAPI.mockResolvedValue({ ...missing, state: 'running' });
        expect((await startAlphaLab('member-token')).state).toBe('running');
        expect(api.postAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab', {}, 'member-token');
    });
    it.each([
        ['nonfinite candidate score', (r: ReturnType<typeof reportFixture>) => { r.candidates[0].score = NaN; }],
        ['nonfinite price', (r: ReturnType<typeof reportFixture>) => { r.candidates[0].plan.entry_price = Infinity; }],
        ['unsafe weight', (r: ReturnType<typeof reportFixture>) => { r.candidates[0].risk.weight = .21; }],
        ['stop above entry', (r: ReturnType<typeof reportFixture>) => { r.candidates[0].plan.stop_price = 61000; }],
        ['duplicate symbols', (r: ReturnType<typeof reportFixture>) => { r.candidates.push(structuredClone(r.candidates[0])); }],
        ['unknown strategy', (r: ReturnType<typeof reportFixture>) => { r.candidates[0].strategy_id = 'unknown'; }],
        ['test-selected champion', (r: ReturnType<typeof reportFixture>) => { r.champion.selection_basis = 'test_only'; }],
        ['internal path', (r: ReturnType<typeof reportFixture>) => { r.warnings = ['C:\\private\\.env']; }],
        ['unsafe reference URL', (r: ReturnType<typeof reportFixture>) => { r.protocol.source_references[0].url = 'javascript:alert(1)'; }],
    ])('rejects %s before numbers or private values reach the view', (_, mutate) => {
        const value = held(); mutate(value.report!);
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
    it('rejects a fourth candidate', () => {
        const value = held();
        value.report!.candidates = Array.from({ length: 4 }, (_, i) => ({ ...structuredClone(value.report!.candidates[0]), symbol: `00000${i}` }));
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
});

describe('AlphaLab operational panel', () => {
    it('shows held stock, price plan, validation contest and agent evidence without an automatic start', async () => {
        api.fetchAuthAPI.mockResolvedValue(held());
        const onSelect = vi.fn();
        render(<AlphaLabPanel token="member-token" onSelectSymbol={onSelect} />);
        const candidate = await screen.findByRole('article', { name: /삼성전자/ });
        expect(candidate).toHaveTextContent('005930');
        expect(candidate).toHaveTextContent('60,000원');
        expect(candidate).toHaveTextContent('57,000원');
        expect(candidate).toHaveTextContent('66,000원');
        expect(candidate).toHaveTextContent('0.0%');
        expect(screen.getByText(/실투자 승인 없음/)).toBeInTheDocument();
        expect(screen.getByRole('table', { name: '전략 검증 비교' })).toHaveTextContent('추세 지속');
        expect(screen.getByRole('list', { name: '에이전트 진행 상태' }).children).toHaveLength(6);
        expect(screen.getByText(/전향 관측 대기/)).toBeInTheDocument();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
        await userEvent.click(within(candidate).getByRole('button', { name: /종목 상세/ }));
        expect(onSelect).toHaveBeenCalledWith('005930');
    });
    it('shows warmup without inventing candidates or win rates', async () => {
        api.fetchAuthAPI.mockResolvedValue(missing);
        render(<AlphaLabPanel />);
        expect(await screen.findByText(/저장된 전략 실험 결과가 없습니다/)).toBeInTheDocument();
        expect(screen.queryByRole('article')).toBeNull();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('explains heldout losses in Korean while retaining the validation-selected strategy', async () => {
        const value = held();
        value.report!.champion = { strategy_id: 'liquidity_breakout', selection_basis: 'validation_only', status: 'held',
            reasons: ['heldout_test_net_loss', 'heldout_cost_stress_net_loss', 'heldout_insufficient_completed_outcomes', 'input_refresh_failed_previous_snapshot_retained'] };
        const strategy = value.report!.strategies[0];
        strategy.strategy_id = 'liquidity_breakout'; strategy.name = '유동성 돌파';
        strategy.test.net_total_return = -.0548996294; strategy.stress.net_total_return = -.0671924424;
        strategy.reasons = [...value.report!.champion.reasons];
        value.report!.candidates[0].strategy_id = 'liquidity_breakout';
        value.report!.candidates[0].risk.reasons = ['heldout_test_net_loss', 'source_verification_required', 'entry_setup_inactive'];
        value.report!.warnings = ['recent_fixed_split_not_full_multiyear_walkforward', 'correlated_outcomes_not_independent_trials',
            'hypothetical_costs_and_liquidity_not_guaranteed', 'diagnostic_backtest_10pct_not_approved_allocation', 'allocation_caps_allow_subsequent_price_drift'];
        api.fetchAuthAPI.mockResolvedValue(value);
        render(<AlphaLabPanel />);
        const candidate = await screen.findByRole('article', { name: /삼성전자/ });
        expect(candidate).toHaveTextContent('고정 테스트 구간의 순수익이 음수');
        expect(candidate).toHaveTextContent('자료의 수집·보정 시점 검증 대기');
        expect(candidate).toHaveTextContent('현재 진입 조건 미충족');
        const contest = screen.getByRole('table', { name: '전략 검증 비교' });
        expect(contest).toHaveTextContent('유동성 돌파');
        expect(contest).toHaveTextContent('검증 구간 선택');
        expect(contest).toHaveTextContent('-5.5%');
        expect(contest).toHaveTextContent('-6.7%');
        expect(screen.getByText(/테스트와 스트레스 결과를 보고 우승 전략을 바꾸지 않습니다/)).toBeInTheDocument();
        expect(screen.getAllByText(/자료 갱신에 실패하여 이전 정상 스냅샷을 사용합니다/).length).toBeGreaterThan(0);
        await userEvent.click(screen.getByText('자료 시점 · 고정 실험 기준 · 출처'));
        expect(screen.getByText(/여러 해의 시점을 반복 이동하는 검증은 완료되지 않았습니다/)).toBeInTheDocument();
        expect(screen.getByText(/결과가 서로 연관될 수 있어 독립 시행으로 인증하지 않습니다/)).toBeInTheDocument();
        expect(screen.getByText(/체결 비용·유동성 보장을 뜻하지 않습니다/)).toBeInTheDocument();
        expect(screen.getByText(/진단용 백테스트의 10% 비중은 승인된 실투자 비중이 아닙니다/)).toBeInTheDocument();
        expect(screen.getByText(/이후 가격 변동으로 비중이 상한을 넘을 수 있습니다/)).toBeInTheDocument();
    });
    it('starts only on a click and preserves last validated evidence during a new run', async () => {
        api.fetchAuthAPI.mockResolvedValue(held());
        api.postAuthAPI.mockResolvedValue({ ...missing, state: 'running' });
        render(<AlphaLabPanel />);
        await screen.findByRole('article', { name: /삼성전자/ });
        await userEvent.click(screen.getByRole('button', { name: '전략 실험 실행' }));
        expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('전략 실험 진행 중');
        expect(screen.getByText(/이전 검증 결과/)).toBeInTheDocument();
    });
    it('retries a failed read and never exposes raw server diagnostics', async () => {
        api.fetchAuthAPI.mockRejectedValueOnce(new Error('C:\\private\\.env secret-key')).mockResolvedValueOnce(held());
        render(<AlphaLabPanel />);
        expect(await screen.findByRole('alert')).not.toHaveTextContent(/private|secret-key/);
        await userEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        expect(await screen.findByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('preserves previous evidence after the worker fails and hides its raw error', async () => {
        api.fetchAuthAPI.mockResolvedValue(held());
        api.postAuthAPI.mockResolvedValue({ ...missing, state: 'failed', error: 'C:\\private\\worker.py' });
        render(<AlphaLabPanel />);
        await screen.findByRole('article', { name: /삼성전자/ });
        await userEvent.click(screen.getByRole('button', { name: '전략 실험 실행' }));
        expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByRole('alert')).not.toHaveTextContent('worker.py');
    });
    it('polls only running work and cancels polling on unmount', async () => {
        vi.useFakeTimers();
        api.fetchAuthAPI.mockResolvedValue({ ...missing, state: 'running' });
        const view = render(<AlphaLabPanel />);
        await act(async () => {});
        await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
        view.unmount();
        await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
    });
    it('does not overlap a slow manual refresh with automatic running-status polling', async () => {
        vi.useFakeTimers();
        let finishRead!: (value: unknown) => void;
        api.fetchAuthAPI.mockResolvedValueOnce({ ...missing, state: 'running' })
            .mockImplementationOnce(() => new Promise(resolve => { finishRead = resolve; })).mockResolvedValue(held());
        render(<AlphaLabPanel />);
        await act(async () => {});
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        await act(async () => {});
        await act(async () => { await vi.advanceTimersByTimeAsync(8000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
        await act(async () => { finishRead(held()); });
        expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '전략 실험 실행' })).not.toBeDisabled();
    });
    it('discards a result returned for a previous token', async () => {
        let oldResolve!: (value: unknown) => void;
        api.fetchAuthAPI.mockImplementationOnce(() => new Promise(resolve => { oldResolve = resolve; })).mockResolvedValueOnce(missing);
        const view = render(<AlphaLabPanel token="old" />);
        view.rerender(<AlphaLabPanel token="new" />);
        await screen.findByText(/저장된 전략 실험 결과가 없습니다/);
        await act(async () => { oldResolve(held()); });
        expect(screen.queryByRole('article')).toBeNull();
    });
});
