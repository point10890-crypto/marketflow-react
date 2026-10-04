import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { fetchAlphaLab, startAlphaLab, validateAlphaLabStatus, type AlphaLabStatus } from '@/lib/alphaLabApi';

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
const now = '2026-10-04T01:00:00Z';
function proposed(action: 'buy' | 'wait' | 'avoid' = 'buy'): AlphaLabStatus {
    const value = held() as AlphaLabStatus;
    const r = value.report!;
    r.decision_at = '2026-10-04T00:00:00Z'; r.latest_session = '2026-10-02';
    r.provenance.captured_at = r.decision_at; r.provenance.analysis_ready = false;
    r.strategies[0].qualified = true;
    r.strategies[0].test.trades = 35; r.strategies[0].stress.trades = 35;
    r.strategies[0].stress.net_total_return = .02;
    const row = r.candidates[0];
    row.setup_active = true; row.quote_session = r.latest_session; row.risk.research_weight = .1;
    row.proposal = { action, label: action === 'buy' ? '매수 제안' : action === 'avoid' ? '매매 제외' : '진입 대기',
        reason: action === 'avoid' ? '고정 테스트 손실로 신규매수에서 제외합니다.' : action === 'wait' ? '다음 자료 확인까지 진입을 기다립니다.' : '선택 전략의 검증과 비용 검사 및 진입 조건을 통과했습니다.',
        next_step: action === 'buy' ? '다음 장 시가 확인 후 재계산하세요.' : '새 검사 결과가 나오면 다시 판단하세요.',
        proposed_weight: action === 'buy' ? .1 : 0, input_session: r.latest_session, derived_at: now,
        valid_until: '2026-10-05T00:00:00Z', plan_basis: 'last_closed_price_next_open_reference', order_allowed: false };
    r.proposal_summary = { action, headline: action === 'avoid' ? '오늘 제안: 신규매수 제외' : action === 'buy' ? '오늘 제안: 매수 검토 1종목' : '오늘 제안: 진입 대기',
        reason: row.proposal.reason, buy_count: Number(action === 'buy'), wait_count: Number(action === 'wait'), avoid_count: Number(action === 'avoid'), policy_version: 'alpha-proposal-v1' };
    return value;
}

beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); vi.spyOn(Date, 'now').mockReturnValue(Date.parse(now)); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

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
    it('accepts a qualified manual proposal with held automatic weight and unverified historical vintage', () => {
        const value = validateAlphaLabStatus(proposed());
        expect(value.report?.candidates[0].proposal?.action).toBe('buy');
        expect(value.report?.candidates[0].risk.weight).toBe(0);
    });
    it.each([
        ['wrong action label', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].proposal!.label = '매매 제외'; }],
        ['forged summary counts', (r: NonNullable<AlphaLabStatus['report']>) => { r.proposal_summary!.buy_count = 2; }],
        ['contradictory summary action', (r: NonNullable<AlphaLabStatus['report']>) => { r.proposal_summary!.action = 'avoid'; }],
        ['negative fixed test', (r: NonNullable<AlphaLabStatus['report']>) => { r.strategies[0].test.net_total_return = -.01; }],
        ['zero cost stress', (r: NonNullable<AlphaLabStatus['report']>) => { r.strategies[0].stress.net_total_return = 0; }],
        ['too few outcomes', (r: NonNullable<AlphaLabStatus['report']>) => { r.strategies[0].stress.trades = 29; }],
        ['negative validation mean', (r: NonNullable<AlphaLabStatus['report']>) => { r.strategies[0].validation.mean_net_return = 0; }],
        ['not qualified', (r: NonNullable<AlphaLabStatus['report']>) => { r.strategies[0].qualified = false; }],
        ['not validation champion', (r: NonNullable<AlphaLabStatus['report']>) => { r.champion.strategy_id = null; }],
        ['inactive setup', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].setup_active = false; }],
        ['uncalibrated risk', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].risk.p = null; }],
        ['certain probability', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].risk.p = 1; }],
        ['missing research weight', (r: NonNullable<AlphaLabStatus['report']>) => { delete r.candidates[0].risk.research_weight; }],
        ['plan beyond eight percent', (r: NonNullable<AlphaLabStatus['report']>) => { const row = r.candidates[0]; row.plan!.stop_price = 54600; row.plan!.loss_fraction = .09; }],
        ['entry differs from reference close', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].last_close = 61000; }],
        ['understated stop risk near cap', (r: NonNullable<AlphaLabStatus['report']>) => { const row = r.candidates[0]; row.plan!.stop_price = 56994.6; row.plan!.loss_fraction = .05; row.proposal!.proposed_weight = .2; row.risk.research_weight = .2; }],
        ['mismatched input session', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].proposal!.input_session = '2026-10-01'; }],
        ['future decision time', (r: NonNullable<AlphaLabStatus['report']>) => { r.decision_at = '2026-10-05T00:00:00Z'; }],
        ['wrong validity horizon', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].proposal!.valid_until = '2026-10-06T00:00:00Z'; }],
        ['automatic order permission', (r: NonNullable<AlphaLabStatus['report']>) => { Object.assign(r.candidates[0].proposal!, { order_allowed: true }); }],
        ['excess plan risk', (r: NonNullable<AlphaLabStatus['report']>) => { const row = r.candidates[0]; row.plan!.stop_price = 54000; row.plan!.loss_fraction = .1; row.proposal!.proposed_weight = .2; row.risk.research_weight = .2; }],
        ['private proposal reason', (r: NonNullable<AlphaLabStatus['report']>) => { r.candidates[0].proposal!.reason = 'C:\\private\\.env'; }],
        ['private summary reason', (r: NonNullable<AlphaLabStatus['report']>) => { r.proposal_summary!.reason = 'api_key=secret'; }],
    ])('rejects a forged BUY: %s', (_, mutate) => {
        const value = proposed(); mutate(value.report!);
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
    it('rejects a nonzero allocation for WAIT or AVOID', () => {
        const value = proposed('wait'); value.report!.candidates[0].proposal!.proposed_weight = .1;
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
    it('accepts expired genuine evidence but sanitizes its BUY and summary to WAIT', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse('2026-10-05T00:00:00Z'));
        const value = validateAlphaLabStatus(proposed());
        expect(value.report?.candidates[0].proposal?.action).toBe('wait');
        expect(value.report?.proposal_summary?.buy_count).toBe(0);
        expect(value.report?.candidates[0].plan?.stop_price).toBe(57000);
    });
    it.each(['source', 'scope', 'session'] as const)('preserves evidence but sanitizes stale %s freshness to WAIT', field => {
        const input = proposed();
        if (field === 'source') input.report!.provenance.captured_at = '2026-09-25T00:00:00Z';
        if (field === 'scope') input.report!.universe.scope_date = '2026-09-25';
        if (field === 'session') { input.report!.latest_session = '2026-09-25'; input.report!.candidates[0].quote_session = '2026-09-25'; input.report!.candidates[0].proposal!.input_session = '2026-09-25'; }
        const value = validateAlphaLabStatus(input);
        expect(value.report?.candidates[0].proposal?.action).toBe('wait');
        expect(value.report?.candidates[0].plan?.stop_price).toBe(57000);
    });
    it('accepts absent source capture on a legitimate WAIT report', () => {
        const input = proposed('wait'); input.report!.provenance.captured_at = null;
        expect(validateAlphaLabStatus(input).report?.candidates[0].proposal?.action).toBe('wait');
    });
});

describe('AlphaLab operational panel', () => {
    it('leads with the conclusion and an actionable manual BUY even when automatic allocation remains held', async () => {
        api.fetchAuthAPI.mockResolvedValue(proposed());
        render(<AlphaLabPanel />);
        const card = await screen.findByRole('article', { name: /삼성전자/ });
        expect(screen.getByRole('heading', { name: '에이전트 매매 제안' })).toBeInTheDocument();
        const conclusion = screen.getByText('오늘 제안: 매수 검토 1종목');
        expect(conclusion.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(within(card).getByText('BUY · 매수 제안')).toBeVisible();
        expect(within(card).getByText('제안 비중')).toBeVisible();
        expect(within(card).getByText('10.0%')).toBeVisible();
        expect(within(card).getByText('기준 종가')).toBeVisible();
        expect(within(card).getByText('다음 장 시가 확인 후 재계산')).toBeVisible();
        expect(screen.getByText('직접 판단용 · 주문 실행 없음')).toBeVisible();
        expect(screen.getByRole('table', { name: '전략 검증 비교' })).not.toBeVisible();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('shows AVOID as new-buy exclusion and hides reference prices until the native disclosure opens', async () => {
        const value = proposed('avoid'); value.report!.strategies[0].test.net_total_return = -.0549;
        api.fetchAuthAPI.mockResolvedValue(value);
        const onSelect = vi.fn(); render(<AlphaLabPanel onSelectSymbol={onSelect} />);
        const card = await screen.findByRole('article', { name: /삼성전자/ });
        expect(screen.getByText('오늘 제안: 신규매수 제외')).toBeVisible();
        expect(within(card).getByText('AVOID · 매매 제외')).toBeVisible();
        expect(within(card).getByText('고정 테스트 손실로 신규매수에서 제외합니다.')).toBeVisible();
        expect(within(card).getByText('57,000원')).not.toBeVisible();
        const disclosure = within(card).getByText('제외 근거와 참고 계산');
        expect(disclosure.tagName).toBe('SUMMARY'); disclosure.focus(); expect(disclosure).toHaveFocus();
        await userEvent.click(disclosure);
        expect(within(card).getByText('57,000원')).toBeVisible();
        await userEvent.click(within(card).getByRole('button', { name: /종목 상세/ }));
        expect(onSelect).toHaveBeenCalledWith('005930');
    });
    it('uses WAIT for a legacy report instead of inferring a buy from its score', async () => {
        api.fetchAuthAPI.mockResolvedValue(held()); render(<AlphaLabPanel />);
        const card = await screen.findByRole('article', { name: /삼성전자/ });
        expect(within(card).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(card).getByText('57,000원')).not.toBeVisible();
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
    });
    it.each(['running', 'failed'] as const)('immediately hides a retained BUY before the POST and throughout a %s result', async state => {
        api.fetchAuthAPI.mockResolvedValue(proposed());
        let finish!: (value: unknown) => void;
        api.postAuthAPI.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
        render(<AlphaLabPanel />); await screen.findByText('BUY · 매수 제안');
        fireEvent.click(screen.getByRole('button', { name: '전략 실험 실행' }));
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        await act(async () => { finish({ ...missing, state }); });
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(screen.getByText('57,000원')).not.toBeVisible();
    });
    it('downgrades a BUY on expiry while idle without starting or fetching another experiment', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T23:59:59Z'));
        api.fetchAuthAPI.mockResolvedValue(proposed()); render(<AlphaLabPanel />); await act(async () => {});
        expect(screen.getByText('BUY · 매수 제안')).toBeVisible();
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(screen.getByText('57,000원')).not.toBeVisible();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it.each(['source', 'scope'] as const)('downgrades a BUY when its %s becomes eight KST calendar days old before the decision expires', async field => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T14:59:59Z'));
        const value = proposed();
        if (field === 'source') value.report!.provenance.captured_at = '2026-09-27T00:00:00Z';
        else value.report!.universe.scope_date = '2026-09-27';
        api.fetchAuthAPI.mockResolvedValue(value); render(<AlphaLabPanel />); await act(async () => {});
        expect(screen.getByText('BUY · 매수 제안')).toBeVisible();
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('suppresses a retained BUY immediately during a refresh and after a read fails', async () => {
        let rejectRead!: (reason: Error) => void;
        api.fetchAuthAPI.mockResolvedValueOnce(proposed()).mockImplementationOnce(() => new Promise((_, reject) => { rejectRead = reject; }));
        render(<AlphaLabPanel />); await screen.findByText('BUY · 매수 제안');
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        await act(async () => { rejectRead(new Error('private worker error')); });
        expect(screen.getByRole('alert')).not.toHaveTextContent('private');
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(screen.getByText('57,000원')).not.toBeVisible();
    });
    it('reevaluates an expired proposal when returning to the window after a clock jump', async () => {
        api.fetchAuthAPI.mockResolvedValue(proposed()); render(<AlphaLabPanel />); await screen.findByText('BUY · 매수 제안');
        vi.mocked(Date.now).mockReturnValue(Date.parse('2026-10-05T00:00:00Z'));
        fireEvent(window, new Event('focus'));
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
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
        expect(screen.getByText(/직접 판단용 연구 의견 · 실투자 승인 없음/)).toBeVisible();
        expect(within(candidate).getByText('57,000원')).not.toBeVisible();
        await userEvent.click(within(candidate).getByText('대기 근거와 참고 계산'));
        expect(within(candidate).getByText('57,000원')).toBeVisible();
        await userEvent.click(screen.getByText('전략 비교 · 에이전트 · 자료 근거 펼치기'));
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
