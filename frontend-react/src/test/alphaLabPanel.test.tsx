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
function opportunity() {
    const value = proposed('avoid');
    value.report!.universe.quality_count = 52; value.report!.universe.inspected_count = 52;
    value.report!.strategies[0].qualified = false; value.report!.strategies[0].test.net_total_return = -.05;
    const phase = (start: string, end: string, samples: number) => ({ samples, wins: samples * .6, losses: samples * .4, zeros: 0,
        win_rate: .6, mean_net_return: .015, stress_mean_net_return: .01, compounded_trade_return: .5,
        stress_compounded_trade_return: .3, start, end, last_exit_session: end, t_stat: 1.7 });
    const buy_candidates = [['196170', '알테오젠', 'mean_reversion'], ['007660', '이수페타시스', 'momentum'], ['402340', 'SK스퀘어', 'mean_reversion']].map(([symbol, name, strategy_id]) => ({
        ...structuredClone(value.report!.candidates[0]), symbol, name, strategy_id, score: .01,
        risk: { weight: 0, status: 'held', reasons: ['research_only_cio_approval_required'], p: .6, kelly_raw: .2, research_weight: .05,
            quarter_kelly_fraction: .05, planned_account_risk: .0025 },
        proposal: { ...value.report!.candidates[0].proposal!, action: 'buy', label: '매수 제안', proposed_weight: .05,
            reason: '이 종목의 두 기간 조건부 거래 순손익과 현재 진입 조건을 통과했습니다.', next_step: '다음 장 시가를 확인하고 최대 10거래일 계획을 다시 계산하세요.' },
        evidence: { selection_basis: 'calibration_stress_mean_then_confirmation', stronger_evidence: false,
            calibration: phase('2021-10-01', '2025-09-30', 40), confirmation: phase('2025-10-01', '2026-10-02', 20),
            retrospective: true, independent_validation: false },
    }));
    return { ...value, report: { ...value.report!, buy_candidates,
        opportunity_scan: { policy_version: 'quality-setup-opportunity-v1', selection_basis: 'calibration_stress_mean_then_confirmation',
            status: 'ready', latest_session: '2026-10-02', lookback_sessions: 1260, calibration_sessions: 1008, confirmation_sessions: 252,
            horizon_sessions: 10, inspected_count: 52, eligible_count: 3, active_setup_count: 12, reasons: [] as string[],
            forward: { decisions: 3, matured: 0, win_rate: null, mean_net_return: null } },
        opportunity_summary: { action: 'buy', headline: '오늘 제안: 새 매수 후보 3종목', reason: '종목별 두 기간의 조건부 성과와 최신 진입 조건을 통과한 후보입니다.',
            buy_count: 3, wait_count: 0, avoid_count: 0, policy_version: 'quality-setup-opportunity-v1' },
    } };
}

function contextualOpportunity() {
    const value = opportunity();
    const input_fingerprint = 'a'.repeat(64);
    return { ...value, report: { ...value.report, input_fingerprint,
        buy_candidates: value.report.buy_candidates.map(row => ({ ...row,
            analyst_context: { schema_version: 1, policy_version: 'quality-analyst-context-v1', symbol: row.symbol,
                as_of: row.quote_session!, input_fingerprint, scope: 'current_quality_cohort', cohort_count: 52,
                comparison_count: 52, status: 'ready', score: 53.676471, favorable_count: 2, caution_count: 1, neutral_count: 1,
                analysts: [
                    { id: 'rev_5', metric_value: -.03, percentile: 78.431373, stance: 'favorable' },
                    { id: 'low_vol_60', metric_value: .35, percentile: 19.607843, stance: 'caution' },
                    { id: 'anti_max_21', metric_value: .05, percentile: 50, stance: 'neutral' },
                    { id: 'attention_fade', metric_value: .8, percentile: 66.666667, stance: 'favorable' },
                ], reasons: [] as string[] },
            entry_guard: { policy_version: 'reference-chase-cap-v1', symbol: row.symbol, as_of: row.quote_session!,
                input_fingerprint, reference_price: row.last_close!, max_chase_fraction: .02,
                max_entry_price: 61200, applies_to: 'manual_next_open_reference', backtest_applied: false },
        })),
    } };
}
const monitorNow = '2026-10-05T00:05:00Z';
function monitoredOpportunity() {
    const value = contextualOpportunity(); const audit = 'b'.repeat(64);
    const valid_until = '2026-10-05T06:30:00Z';
    return { ...value, report: { ...value.report,
        opportunity_scan: { ...value.report.opportunity_scan, audit_hash: audit },
        proposal_window: { policy_version: 'next-session-proposal-v1', input_fingerprint: value.report.input_fingerprint,
            opportunity_audit_hash: audit, origin_at: value.report.decision_at!, entry_session: '2026-10-05', valid_until,
            calendar_source: 'KIS:CTCA0903R' },
        buy_candidates: value.report.buy_candidates.map(row => ({ ...row, plan: { ...row.plan!, atr: 1500 },
            proposal: { ...row.proposal, derived_at: monitorNow, valid_until } })),
    }, operations: { schema_version: 1, policy_version: 'alpha-cadence-v1', generated_at: monitorNow,
        cadence: { timezone: 'Asia/Seoul', research_time: '20:30', monitor_interval_seconds: 300, market_state: 'open',
            calendar_status: 'ready', calendar_checked_at: '2026-10-04T23:55:00Z', last_scan_at: value.report.decision_at!,
            next_scan_at: '2026-10-05T11:30:00Z', last_monitor_at: monitorNow, next_monitor_at: '2026-10-05T00:10:00Z', reasons: [] as string[] },
        monitoring: { status: 'ready', decision_at: value.report.decision_at!, origin_at: value.report.decision_at!,
            input_fingerprint: value.report.input_fingerprint, opportunity_audit_hash: audit, entry_session: '2026-10-05',
            valid_until, observed_at: monitorNow, reasons: [] as string[], quotes: value.report.buy_candidates.map(row => ({ symbol: row.symbol,
                price: 60500, quote_at: '2026-10-05T00:04:30Z', fetched_at: monitorNow, opening_price: 60000,
                source: 'KIS:J:FHKST03010200+FHKST01010100', entry_state: 'within_band', reference_price: 60000,
                entry_ceiling: 61200, stop_price: 57000, target_price: 66000,
                adjusted_plan: { entry_price: 60000, stop_price: 57000, target_price: 66000, loss_fraction: .05, proposed_weight: .05 },
                reasons: [] as string[] })) },
        paper: { decisions: 3, matured: 1, win_rate: 1, mean_net_return: .01,
            counts: { pending: 2, open: 0, unfilled: 0, missing_session: 0, source_revision: 0, closed: 1 },
            excluded_revised_closed: 0, basis: 'frozen_watchlist_next_open_outcomes_not_account_pnl', entry_guard_applied: false },
    } };
}

beforeEach(() => { api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); vi.spyOn(Date, 'now').mockReturnValue(Date.parse(now)); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });
const openOriginal = () => fireEvent.click(screen.getByText('기존 실험 후보 · 제외 근거'));

describe('AlphaLab evidence boundary', () => {
    it('rejects malformed optional operations even for a structurally valid legacy-expiry report', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        Reflect.deleteProperty(input.report, 'proposal_window');
        input.report.buy_candidates.forEach(row => { row.proposal.valid_until = '2026-10-05T00:00:00Z'; });
        input.operations.monitoring.quotes[0].price = NaN;
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it('accepts the certified next-session window beyond legacy twenty-four hours without renewing the origin', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow));
        const result = validateAlphaLabStatus(monitoredOpportunity());
        expect(result.report?.buy_candidates?.[0].proposal?.action).toBe('buy');
    });
    it('preserves three unfetched closed-day quote states without inventing stale-price warnings', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse('2026-10-04T07:10:00Z')); const input = monitoredOpportunity();
        input.report.proposal_window.entry_session = '2026-10-06'; input.report.proposal_window.valid_until = '2026-10-06T06:30:00Z';
        input.report.buy_candidates.forEach(row => { row.proposal.derived_at = '2026-10-04T07:10:00Z'; row.proposal.valid_until = input.report.proposal_window.valid_until; });
        input.operations.generated_at = '2026-10-04T07:10:00Z'; input.operations.cadence.market_state = 'closed';
        input.operations.cadence.calendar_checked_at = input.operations.generated_at;
        Object.assign(input.operations.monitoring, { status: 'held', observed_at: null, entry_session: '2026-10-06', valid_until: input.report.proposal_window.valid_until });
        input.operations.monitoring.quotes.forEach(quote => Object.assign(quote, { price: null, opening_price: null, quote_at: null,
            fetched_at: null, adjusted_plan: null, entry_state: 'closed', reasons: ['market_closed'] }));
        const result = validateAlphaLabStatus(input);
        expect(result.report?.buy_candidates?.filter(row => row.proposal?.action === 'buy')).toHaveLength(3);
        expect(result.operations?.monitoring.quotes.every(quote => quote.price === null && quote.entry_state === 'closed' && !quote.reasons.includes('quote_stale'))).toBe(true);
    });
    it('holds a corrected calendar instead of renewing a source-bound entry deadline', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        Object.assign(input.report.proposal_window, { entry_session: null, valid_until: null });
        Object.assign(input.operations.monitoring, { entry_session: null, valid_until: null, reasons: ['calendar_revision'] });
        expect(validateAlphaLabStatus(input).report?.buy_candidates?.[0].proposal?.action).toBe('wait');
    });
    it('rejects a within-band opening above the frozen entry ceiling even without an adjusted plan', () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        input.operations.monitoring.quotes[0].opening_price = 62000;
        Reflect.deleteProperty(input.operations.monitoring.quotes[0], 'adjusted_plan');
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it.each([
        ['window policy', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.policy_version = 'renew_on_rescan'; }],
        ['window fingerprint', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.input_fingerprint = 'c'.repeat(64); }],
        ['window audit identity', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.opportunity_audit_hash = 'c'.repeat(64); }],
        ['origin after decision', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.origin_at = '2026-10-04T00:00:01Z'; }],
        ['unverified calendar source', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.calendar_source = 'weekday_guess'; }],
        ['entry on origin day', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.entry_session = '2026-10-04'; }],
        ['more than seven days', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.entry_session = '2026-10-12'; v.report.proposal_window.valid_until = '2026-10-12T06:30:00Z'; }],
        ['wrong session close', (v: ReturnType<typeof monitoredOpportunity>) => { v.report.proposal_window.valid_until = '2026-10-05T06:30:01Z'; }],
        ['wrong cadence timezone', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.cadence.timezone = 'UTC'; }],
        ['wrong cadence interval', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.cadence.monitor_interval_seconds = 30; }],
        ['wrong monitor enum', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.status = 'approved'; }],
        ['nonfinite current price', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].price = NaN; }],
        ['unknown price provider', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].source = 'LLM'; }],
        ['forged frozen reference', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].reference_price = 61000; }],
        ['forged current ceiling', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].entry_ceiling = 63000; }],
        ['forged adjusted risk', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].adjusted_plan.loss_fraction = .001; }],
        ['overweight adjusted plan', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].adjusted_plan.proposed_weight = .06; }],
        ['duplicate monitored symbol', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[1].symbol = v.operations.monitoring.quotes[0].symbol; }],
        ['unknown monitored symbol', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].symbol = '005930'; }],
        ['private monitor reason', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.monitoring.quotes[0].reasons = ['C:\\private\\.env']; }],
        ['wrong paper denominator', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.paper.matured = 2; }],
        ['revised closed counted', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.paper.excluded_revised_closed = 1; }],
        ['claims guard-tested paper', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.paper.entry_guard_applied = true; }],
        ['claims account profit', (v: ReturnType<typeof monitoredOpportunity>) => { v.operations.paper.basis = 'account_pnl'; }],
    ])('rejects malformed cadence/monitor evidence: %s', (_, mutate) => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity(); mutate(input);
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it.each(['pending', 'calendar_failed', 'calendar_identity'] as const)('holds next-session BUY without a verified matching calendar: %s', condition => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        if (condition === 'pending') {
            Object.assign(input.report.proposal_window, { entry_session: null, valid_until: null });
            Object.assign(input.operations.monitoring, { entry_session: null, valid_until: null });
        } else if (condition === 'calendar_failed') input.operations.cadence.calendar_status = 'failed';
        else input.operations.monitoring.input_fingerprint = 'c'.repeat(64);
        expect(validateAlphaLabStatus(input).report?.buy_candidates?.[0].proposal?.action).toBe('wait');
    });
    it.each(['stale', 'failed'] as const)('suppresses current quotes while preserving a certified research BUY after monitor %s', condition => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        if (condition === 'stale') input.operations.monitoring.quotes.forEach(quote => { quote.quote_at = '2026-10-04T23:57:00Z'; quote.fetched_at = quote.quote_at; });
        else input.operations.monitoring.status = 'failed';
        const result = validateAlphaLabStatus(input);
        expect(result.report?.buy_candidates?.[0].proposal?.action).toBe('buy');
        expect(JSON.stringify(result)).not.toContain('"price":60500');
    });
    it('accepts snapshot-bound diagnostic context and the manual reference ceiling without changing selection or weights', () => {
        const result = validateAlphaLabStatus(contextualOpportunity());
        expect(result.report?.buy_candidates?.map(row => [row.symbol, row.proposal?.action, row.risk.research_weight])).toEqual([
            ['196170', 'buy', .05], ['007660', 'buy', .05], ['402340', 'buy', .05],
        ]);
    });
    it('rejects a coerced array status even when the unavailable diagnostic shape is otherwise valid', () => {
        const input = contextualOpportunity(); const context = input.report.buy_candidates[0].analyst_context;
        Object.assign(context, { status: ['unavailable'], score: null, favorable_count: 0, caution_count: 0, neutral_count: 0 });
        context.analysts.forEach(analyst => Object.assign(analyst, { metric_value: null, percentile: null, stance: 'unavailable' }));
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it.each([
        ['different symbol', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.symbol = '005930'; }],
        ['different context session', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.as_of = '2026-10-01'; }],
        ['different snapshot', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.input_fingerprint = 'b'.repeat(64); }],
        ['missing report snapshot', (r: ReturnType<typeof contextualOpportunity>['report']) => { Reflect.deleteProperty(r, 'input_fingerprint'); }],
        ['invalid report snapshot', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.input_fingerprint = 'private'; }],
        ['wrong context policy', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.policy_version = 'trained'; }],
        ['wrong quality cohort', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.cohort_count = 51; }],
        ['comparison exceeds cohort', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.comparison_count = 53; }],
        ['fractional comparison', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.comparison_count = 51.5; }],
        ['small cohort marked ready', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.comparison_count = 7; }],
        ['nonfinite metric', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[0].metric_value = NaN; }],
        ['negative volatility', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[1].metric_value = -.1; }],
        ['negative amount proxy', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[3].metric_value = -.1; }],
        ['return below total loss', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[0].metric_value = -1; }],
        ['percentile outside range', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[0].percentile = 101; }],
        ['stance contradicts percentile', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts[0].stance = 'caution'; }],
        ['forged favorable count', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.favorable_count = 3; }],
        ['forged score', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.score = 90; }],
        ['changed analyst order', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.analysts.reverse(); }],
        ['private context reason', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].analyst_context.reasons = ['C:\\private\\.env']; }],
        ['unknown context field', (r: ReturnType<typeof contextualOpportunity>['report']) => { Object.assign(r.buy_candidates[0].analyst_context, { worker_path: 'C:\\private' }); }],
        ['guard for a different symbol', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.symbol = '005930'; }],
        ['guard for a different session', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.as_of = '2026-10-01'; }],
        ['guard for a different snapshot', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.input_fingerprint = 'b'.repeat(64); }],
        ['guard for a different reference', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.reference_price = 59000; }],
        ['wrong chase fraction', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.max_chase_fraction = .03; }],
        ['wrong ceiling equation', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.max_entry_price = 61201; }],
        ['claims historical application', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.backtest_applied = true; }],
        ['claims order execution', (r: ReturnType<typeof contextualOpportunity>['report']) => { r.buy_candidates[0].entry_guard.applies_to = 'order_limit'; }],
    ])('rejects unbound or contradictory optional guidance: %s', (_, mutate) => {
        const input = contextualOpportunity(); mutate(input.report);
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it.each(['legacy', 'opportunity'] as const)('accepts a fresh %s BUY from a server clock two seconds ahead', kind => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(now));
        const input = kind === 'legacy' ? proposed() : opportunity();
        input.report!.decision_at = '2026-10-04T01:00:02Z';
        for (const row of [...input.report!.candidates, ...(input.report!.buy_candidates ?? [])]) {
            if (!row.proposal) continue;
            row.proposal.derived_at = '2026-10-04T01:00:02Z'; row.proposal.valid_until = '2026-10-05T01:00:02Z';
        }
        const result = validateAlphaLabStatus(input);
        expect(kind === 'legacy' ? result.report?.candidates[0].proposal?.action : result.report?.buy_candidates?.[0].proposal?.action).toBe('buy');
    });
    it.each(['legacy', 'opportunity'] as const)('rejects a %s BUY whose decision or assessment exceeds sixty seconds ahead', kind => {
        const makeInput = () => kind === 'legacy' ? proposed() : opportunity();
        const decision = makeInput(); decision.report!.decision_at = '2026-10-04T01:01:00.001Z';
        for (const row of [...decision.report!.candidates, ...(decision.report!.buy_candidates ?? [])]) {
            if (row.proposal) row.proposal.valid_until = '2026-10-05T01:01:00.001Z';
        }
        expect(() => validateAlphaLabStatus(decision)).toThrow(/응답 형식/);
        const assessment = makeInput();
        for (const row of [...assessment.report!.candidates, ...(assessment.report!.buy_candidates ?? [])]) {
            if (row.proposal) row.proposal.derived_at = '2026-10-04T01:01:00.001Z';
        }
        expect(() => validateAlphaLabStatus(assessment)).toThrow(/응답 형식/);
    });
    it('accepts independent conditional opportunities while the original champion remains unqualified and losing', () => {
        const result = validateAlphaLabStatus(opportunity());
        expect(result.report?.buy_candidates?.map(row => row.symbol)).toEqual(['196170', '007660', '402340']);
        expect(result.report?.strategies[0].qualified).toBe(false);
    });
    it('accepts uncapped quarter Kelly while capping the proposed research allocation at five percent', () => {
        const input = opportunity(); const row = input.report.buy_candidates[0];
        row.risk.kelly_raw = .8; row.risk.quarter_kelly_fraction = .2;
        expect(validateAlphaLabStatus(input).report?.buy_candidates?.[0].proposal?.proposed_weight).toBe(.05);
    });
    it.each([
        ['wrong policy', (r: ReturnType<typeof opportunity>['report']) => { r.opportunity_scan.policy_version = 'loose'; }],
        ['wrong selection', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.selection_basis = 'confirmation_best'; }],
        ['calibration sample shortage', (r: ReturnType<typeof opportunity>['report']) => { const p = r.buy_candidates[0].evidence.calibration; p.samples = 25; p.wins = 15; p.losses = 10; }],
        ['confirmation sample shortage', (r: ReturnType<typeof opportunity>['report']) => { const p = r.buy_candidates[0].evidence.confirmation; p.samples = 5; p.wins = 3; p.losses = 2; }],
        ['zero confirmation stress mean', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.confirmation.stress_mean_net_return = 0; }],
        ['cost stress improves the mean', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.confirmation.stress_mean_net_return = .02; }],
        ['confirmation does not end at latest session', (r: ReturnType<typeof opportunity>['report']) => { const p = r.buy_candidates[0].evidence.confirmation; p.end = '2026-10-01'; p.last_exit_session = p.end; }],
        ['negative calibration compounded return', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.calibration.compounded_trade_return = -.1; }],
        ['nonfinite confirmation return', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.confirmation.mean_net_return = Infinity; }],
        ['invented win rate', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.calibration.win_rate = .99; }],
        ['overlapping phases', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.confirmation.start = '2025-09-30'; }],
        ['exit outside phase', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.calibration.last_exit_session = '2025-10-01'; }],
        ['no losses', (r: ReturnType<typeof opportunity>['report']) => { const p = r.buy_candidates[0].evidence.calibration; p.wins = 40; p.losses = 0; p.win_rate = 1; }],
        ['six percent allocation', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].proposal.proposed_weight = .06; r.buy_candidates[0].risk.research_weight = .06; }],
        ['proposal differs from calculated research weight', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].proposal.proposed_weight = .04; }],
        ['approved risk weight', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].risk.weight = .01; }],
        ['forged quarter Kelly', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].risk.quarter_kelly_fraction = .04; }],
        ['forged directional probability', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].risk.p = .99; }],
        ['forged stronger evidence', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.stronger_evidence = true; }],
        ['forged summary', (r: ReturnType<typeof opportunity>['report']) => { r.opportunity_summary.buy_count = 4; }],
        ['duplicate opportunities', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[1].symbol = r.buy_candidates[0].symbol; }],
        ['private evidence', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].proposal.reason = 'C:\\private\\.env'; }],
        ['pretended independent test', (r: ReturnType<typeof opportunity>['report']) => { r.buy_candidates[0].evidence.independent_validation = true; }],
    ])('rejects invalid opportunity evidence: %s', (_, mutate) => {
        const input = opportunity(); mutate(input.report);
        expect(() => validateAlphaLabStatus(input)).toThrow(/응답 형식/);
    });
    it.each(['held', 'refresh_failed'] as const)('retains the opportunity evidence but downgrades a BUY when scan status is %s', condition => {
        const input = opportunity();
        if (condition === 'held') input.report.opportunity_scan.status = 'held';
        else input.report.opportunity_scan.reasons = ['source_refresh_failed'];
        const result = validateAlphaLabStatus(input);
        expect(result.report?.buy_candidates?.[0].proposal?.action).toBe('wait');
        expect(result.report?.opportunity_summary?.buy_count).toBe(0);
    });
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
    it('shows saved cadence, current quotes and opening-reference plans without claiming fills or account profits', async () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); api.fetchAuthAPI.mockResolvedValue(monitoredOpportunity());
        render(<AlphaLabPanel />); const card = await screen.findByRole('article', { name: /알테오젠/ });
        expect(screen.getByText('자동 연구 · 20:30 KST')).toBeVisible();
        expect(screen.getByText('가격 감시 · 5분')).toBeVisible();
        expect(within(card).getByText('60,500원')).toBeVisible();
        expect(within(card).getByText('공식 시가 참고 · 체결 아님')).toBeVisible();
        expect(screen.getByText('새 후보 전향 모의 결과')).toBeVisible();
        expect(screen.getByText(/완료·수정 제외 분모 1건/)).toBeVisible();
        expect(screen.getByText(/추격 상한을 적용한 성과나 계좌 손익이 아닙니다/)).toBeVisible();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('renders the saved legacy cadence during a rolling server release', async () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow));
        const input = monitoredOpportunity(); input.operations.cadence.research_time = '18:45';
        input.operations.cadence.next_scan_at = '2026-10-05T09:45:00Z';
        api.fetchAuthAPI.mockResolvedValue(input); render(<AlphaLabPanel />);
        expect(await screen.findByText('자동 연구 · 18:45 KST')).toBeVisible();
    });
    it('keeps revised closed paper outcomes out of the visible performance denominator', async () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse(monitorNow)); const input = monitoredOpportunity();
        input.operations.paper.counts.closed = 3; input.operations.paper.matured = 2; input.operations.paper.excluded_revised_closed = 1;
        input.operations.paper.win_rate = .5; api.fetchAuthAPI.mockResolvedValue(input); render(<AlphaLabPanel />);
        await screen.findByText('새 후보 전향 모의 결과');
        expect(screen.getByText(/완료·수정 제외 분모 2건/)).toBeVisible();
        expect(screen.getByText(/수정 종료 제외 1건/)).toBeVisible();
    });
    it('polls only saved status every thirty seconds when ready and cleans up the timer on unmount', async () => {
        vi.useFakeTimers(); api.fetchAuthAPI.mockResolvedValue(contextualOpportunity());
        const view = render(<AlphaLabPanel />); await act(async () => {});
        await act(async () => { await vi.advanceTimersByTimeAsync(29999); }); expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(1); }); expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
        expect(api.postAuthAPI).not.toHaveBeenCalled(); view.unmount();
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); }); expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2);
    });
    it('expires current-price guidance on the idle TTL while preserving the longer certified research BUY', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date(monitorNow));
        api.fetchAuthAPI.mockResolvedValueOnce(monitoredOpportunity()).mockImplementation(() => new Promise(() => {}));
        render(<AlphaLabPanel />); await act(async () => {}); const card = screen.getByRole('article', { name: /알테오젠/ });
        expect(within(card).getByText('60,500원')).toBeVisible();
        await act(async () => { await vi.advanceTimersByTimeAsync(390000); });
        expect(within(card).queryByText('60,500원')).toBeNull();
        expect(within(card).getByText('BUY · 매수 제안')).toBeVisible();
        expect(within(card).getByText(/현재 가격 확인 대기/)).toBeVisible();
    });
    it('masks current prices during a failed poll then safely recovers on a later saved GET', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date(monitorNow));
        api.fetchAuthAPI.mockResolvedValueOnce(monitoredOpportunity()).mockRejectedValueOnce(new Error('private')).mockResolvedValue(monitoredOpportunity());
        render(<AlphaLabPanel />); await act(async () => {}); const card = screen.getByRole('article', { name: /알테오젠/ });
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(within(card).queryByText('60,500원')).toBeNull(); expect(screen.getByRole('alert')).not.toHaveTextContent('private');
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(within(card).getByText('60,500원')).toBeVisible(); expect(screen.queryByRole('alert')).toBeNull();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('prevents overlapping manual requests while a saved-status poll is still pending', async () => {
        vi.useFakeTimers(); api.fetchAuthAPI.mockResolvedValueOnce(contextualOpportunity()).mockImplementation(() => new Promise(() => {}));
        render(<AlphaLabPanel />); await act(async () => {});
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(screen.getByRole('button', { name: '저장 결과 새로고침' })).toBeDisabled();
        expect(screen.getByRole('button', { name: '매수 후보 검출' })).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('shows subsequent-session reference monitoring separately without renewing an expired entry proposal', async () => {
        vi.mocked(Date.now).mockReturnValue(Date.parse('2026-10-06T00:05:00Z')); const input = monitoredOpportunity();
        input.operations.generated_at = '2026-10-06T00:05:00Z'; input.operations.monitoring.observed_at = input.operations.generated_at;
        input.operations.monitoring.quotes.forEach(quote => { quote.quote_at = '2026-10-06T00:04:30Z'; quote.fetched_at = input.operations.generated_at; });
        api.fetchAuthAPI.mockResolvedValue(input); render(<AlphaLabPanel />);
        expect(await screen.findByText('진입 종료 · 참고 감시')).toBeVisible();
        const card = screen.getByRole('article', { name: /알테오젠/ });
        expect(within(card).getByText('WAIT · 진입 대기')).toBeVisible(); expect(within(card).queryByText('60,500원')).toBeNull();
        expect(screen.getAllByText(/알테오젠 · 60,500원/)[0]).toBeVisible(); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('shows descriptive price-factor counts and the two-percent reference ceiling only on the current BUY cards', async () => {
        api.fetchAuthAPI.mockResolvedValue(contextualOpportunity()); const onSelect = vi.fn();
        render(<AlphaLabPanel onSelectSymbol={onSelect} />);
        const card = await screen.findByRole('article', { name: /알테오젠/ });
        expect(within(card).getByText('가격 요인 대조 · 우호 2 / 주의 1 / 중립 1')).toBeVisible();
        expect(within(card).getByText('추격 매수 상한 (+2%)')).toBeVisible();
        expect(within(card).getAllByText('61,200원')[0]).toBeVisible();
        expect(within(card).getByText(/다음 장 시가가 상한을 넘으면 진입을 기다립니다/)).toBeVisible();
        const disclosure = within(card).getByText('검증 근거와 참고 계산');
        disclosure.focus(); expect(disclosure).toHaveFocus(); fireEvent.keyDown(disclosure, { key: 'Enter' });
        await userEvent.click(disclosure);
        expect(within(card).getByText(/종가 × 거래량/)).toBeVisible();
        expect(within(card).getByText(/과거 백테스트·전향 모의 성과에는 이 상한을 적용하지 않았습니다/)).toBeVisible();
        expect(within(card).getByText(/학습된 모델이나 독립 에이전트 투표가 아닙니다/)).toBeVisible();
        await userEvent.click(within(card).getByRole('button', { name: /종목 상세/ }));
        expect(onSelect).toHaveBeenCalledWith('196170'); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('preserves BUY selection when optional price context is unavailable and reveals only its data limitation', async () => {
        const input = contextualOpportunity();
        for (const row of input.report.buy_candidates) {
            Object.assign(row.analyst_context, { status: 'unavailable', comparison_count: 7, score: null,
                favorable_count: 0, caution_count: 0, neutral_count: 0, reasons: ['insufficient_cohort'] });
            row.analyst_context.analysts.forEach(analyst => Object.assign(analyst, { metric_value: null, percentile: null, stance: 'unavailable' }));
        }
        expect(validateAlphaLabStatus(input).report?.buy_candidates?.[0].proposal?.action).toBe('buy');
        api.fetchAuthAPI.mockResolvedValue(input); render(<AlphaLabPanel />);
        const card = await screen.findByRole('article', { name: /알테오젠/ });
        expect(within(card).queryByText(/가격 요인 대조/)).toBeNull();
        await userEvent.click(within(card).getByText('검증 근거와 참고 계산'));
        expect(within(card).getByText(/가격 요인 자료 부족/)).toBeVisible();
    });
    it('puts three new exploratory BUY cards before the closed original excluded candidates', async () => {
        api.fetchAuthAPI.mockResolvedValue(opportunity()); const onSelect = vi.fn();
        render(<AlphaLabPanel onSelectSymbol={onSelect} />);
        const first = await screen.findByRole('article', { name: /알테오젠/ });
        expect(first).toBeVisible(); expect(within(first).getByText('BUY · 매수 제안')).toBeVisible();
        expect(within(first).getAllByText('5.0%')[0]).toBeVisible();
        expect(within(first).getByText('보유 계획 · 최대 10거래일')).toBeVisible();
        expect(screen.getByRole('article', { name: /이수페타시스/ })).toBeVisible();
        expect(screen.getByRole('article', { name: /SK스퀘어/ })).toBeVisible();
        expect(screen.getByRole('article', { name: /삼성전자/ })).not.toBeVisible();
        expect(screen.getByText('탐색적 매수 제안')).toBeVisible();
        await userEvent.click(within(first).getByText('검증 근거와 참고 계산'));
        expect(within(first).getAllByText(/과거 승리 비율/)).toHaveLength(2);
        expect(within(first).getAllByText(/평균 거래 순손익/).every(element => element.closest('details')?.open !== false)).toBe(true);
        expect(within(first).getAllByText(/독립 검증/)[0]).toBeVisible();
        await userEvent.click(within(first).getByRole('button', { name: /종목 상세/ }));
        expect(onSelect).toHaveBeenCalledWith('196170'); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('does not promote the old excluded cards when the independent scan has no eligible opportunities', async () => {
        const input = opportunity(); input.report.buy_candidates = []; input.report.opportunity_scan.eligible_count = 0;
        input.report.opportunity_summary = { ...input.report.opportunity_summary, action: 'wait', headline: '오늘 제안: 진입 대기', buy_count: 0 };
        api.fetchAuthAPI.mockResolvedValue(input); render(<AlphaLabPanel />);
        expect(await screen.findByText('현재 조건을 통과한 새 매수 후보가 없습니다.')).toBeVisible();
        expect(screen.getByRole('article', { name: /삼성전자/ })).not.toBeVisible();
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
    });
    it.each(['running', 'failed'] as const)('hides all new BUY proposals immediately during POST and retains them only as WAIT after %s', async state => {
        let finish!: (value: unknown) => void;
        api.fetchAuthAPI.mockResolvedValue(contextualOpportunity()); api.postAuthAPI.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
        render(<AlphaLabPanel />); const first = await screen.findByRole('article', { name: /알테오젠/ });
        fireEvent.click(screen.getByRole('button', { name: '매수 후보 검출' }));
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(within(first).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(first).queryByText('추격 매수 상한 (+2%)')).toBeNull();
        expect(within(first).queryByText(/가격 요인 대조/)).toBeNull();
        await act(async () => { finish({ ...missing, state }); });
        expect(within(first).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(first).getByText('57,000원')).not.toBeVisible();
        expect(screen.getByRole('article', { name: /삼성전자/ })).not.toBeVisible();
    });
    it('suppresses every new BUY during a read and after a rejected refresh, retaining the evidence', async () => {
        api.fetchAuthAPI.mockResolvedValueOnce(contextualOpportunity()).mockRejectedValueOnce(new Error('secret-key'));
        render(<AlphaLabPanel />); const first = await screen.findByRole('article', { name: /알테오젠/ });
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        expect(within(first).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(first).queryByText('추격 매수 상한 (+2%)')).toBeNull();
        await screen.findByRole('alert');
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(within(first).getByText('57,000원')).not.toBeVisible();
        expect(within(first).queryByText(/가격 요인 대조/)).toBeNull();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('expires new candidates while preserving their evidence and the closed original experiment', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T23:59:59Z'));
        api.fetchAuthAPI.mockResolvedValue(contextualOpportunity()); render(<AlphaLabPanel />); await act(async () => {});
        const first = screen.getByRole('article', { name: /알테오젠/ });
        expect(within(first).getByText('BUY · 매수 제안')).toBeVisible();
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(within(first).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(first).queryByText('추격 매수 상한 (+2%)')).toBeNull();
        expect(within(first).queryByText(/가격 요인 대조/)).toBeNull();
        expect(within(first).getByText('57,000원')).not.toBeVisible();
        expect(screen.getByRole('article', { name: /삼성전자/ })).not.toBeVisible();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('preserves an actionable legacy BUY in the closed original experiment without promoting it to the new candidate list', async () => {
        api.fetchAuthAPI.mockResolvedValue(proposed());
        render(<AlphaLabPanel />);
        const card = await screen.findByRole('article', { name: /삼성전자/ });
        expect(card).not.toBeVisible();
        expect(screen.getByText('현재 조건을 통과한 새 매수 후보가 없습니다.')).toBeVisible();
        openOriginal();
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
        openOriginal();
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
        expect(card).not.toBeVisible(); openOriginal();
        expect(within(card).getByText('WAIT · 진입 대기')).toBeVisible();
        expect(within(card).getByText('57,000원')).not.toBeVisible();
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
    });
    it.each(['running', 'failed'] as const)('immediately hides a retained BUY before the POST and throughout a %s result', async state => {
        api.fetchAuthAPI.mockResolvedValue(proposed());
        let finish!: (value: unknown) => void;
        api.postAuthAPI.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
        render(<AlphaLabPanel />); await screen.findByText('BUY · 매수 제안');
        openOriginal();
        fireEvent.click(screen.getByRole('button', { name: '매수 후보 검출' }));
        expect(screen.queryByText('BUY · 매수 제안')).toBeNull();
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        await act(async () => { finish({ ...missing, state }); });
        expect(screen.getByText('WAIT · 진입 대기')).toBeVisible();
        expect(screen.getByText('57,000원')).not.toBeVisible();
    });
    it('downgrades a BUY on expiry while idle without starting or fetching another experiment', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-04T23:59:59Z'));
        api.fetchAuthAPI.mockResolvedValue(proposed()); render(<AlphaLabPanel />); await act(async () => {});
        openOriginal();
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
        openOriginal();
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
        openOriginal();
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
        openOriginal();
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
        openOriginal();
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
        expect(await screen.findByText(/저장된 매수 후보 검출 결과가 없습니다/)).toBeInTheDocument();
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
        await userEvent.click(screen.getByRole('button', { name: '매수 후보 검출' }));
        expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('매수 후보 검출 진행 중');
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
        await userEvent.click(screen.getByRole('button', { name: '매수 후보 검출' }));
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
        expect(screen.getByRole('button', { name: '매수 후보 검출' })).not.toBeDisabled();
    });
    it('discards a result returned for a previous token', async () => {
        let oldResolve!: (value: unknown) => void;
        api.fetchAuthAPI.mockImplementationOnce(() => new Promise(resolve => { oldResolve = resolve; })).mockResolvedValueOnce(missing);
        const view = render(<AlphaLabPanel token="old" />);
        view.rerender(<AlphaLabPanel token="new" />);
        await screen.findByText(/저장된 매수 후보 검출 결과가 없습니다/);
        await act(async () => { oldResolve(contextualOpportunity()); });
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('removes prior-account factor context and entry guidance immediately when the token changes', async () => {
        let finish!: (value: unknown) => void;
        api.fetchAuthAPI.mockResolvedValueOnce(contextualOpportunity()).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
        const view = render(<AlphaLabPanel token="old" />);
        const card = await screen.findByRole('article', { name: /알테오젠/ });
        expect(within(card).getByText('추격 매수 상한 (+2%)')).toBeVisible();
        view.rerender(<AlphaLabPanel token="new" />);
        expect(screen.queryByRole('article')).toBeNull();
        expect(screen.queryByText(/가격 요인 대조/)).toBeNull();
        await act(async () => { finish(missing); });
        expect(screen.queryByText('추격 매수 상한 (+2%)')).toBeNull();
    });
});
