import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OpportunityBoard from '@/components/aibain/OpportunityBoard';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { validateAlphaLabStatus } from '@/lib/alphaLabApi';
import { effectiveOpportunityEngine, opportunityClockExpirations, validateOpportunityEngine } from '@/lib/opportunityEngine';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
const now = Date.parse('2026-10-05T01:00:00Z');
export function opportunityFixture() {
    const identity = { decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), source_audit_hash: 'c'.repeat(64) };
    return { schema_version: 1, policy_version: 'profit-opportunity-v1', ...identity, generated_at: '2026-10-04T10:00:00Z',
        latest_session: '2026-10-02', entry_session: '2026-10-05', valid_until: '2026-10-05T06:30:00Z', status: 'ready', research_only: true, live_orders: false,
        coverage: { inspected: 100, eligible: 7, selected: 1 }, alternatives: [], reasons: [] as string[],
        stages: [{ id: 'data', status: 'passed', detail: '저장 가격과 출처 확인', count: 100 }],
        evaluation: { basis: 'issued_opportunities_not_fills', issued: 1, pending: 1, expired: 0, observed: 0, unobserved: 0 },
        candidates: [{ ...identity, opportunity_id: 'd'.repeat(64), symbol: '005930', name: '삼성전자', market: 'KR', strategy_id: 'momentum', rank: 1,
            action: 'entry_candidate', label: '현재 진입 후보', why_stock: '비용 2배 조건부 평균과 불확실성을 대조했습니다.',
            why_now: '새 관측 가격이 참고 상한 안에 있습니다.', next_action: '참고 가격과 손실 한도를 직접 확인하세요.',
            quote_session: '2026-10-02', source_at: '2026-10-04T09:00:00Z', current_price: 60000,
            quote_at: '2026-10-05T00:59:30Z', fetched_at: '2026-10-05T00:59:45Z', quote_source: 'KIS:J:FHKST03010200+FHKST01010100',
            valid_until: '2026-10-05T06:30:00Z', reference_weight: .04,
            plan: { basis: 'observed_quote_reference', entry_low: 60000, entry_high: 61200, stop_price: 57000, target_price: 66000, horizon_sessions: 10 },
            ranking: { stress_mean_net_return: .03, standard_error: .005, conservative_score: .0202, correlation_penalty: 0, score: .0202, calibration_samples: 40, confirmation_samples: 20 },
            kelly: { raw_fraction: .16, fraction: .25, cap: .05, account_risk_cap: .01 },
            audit: { status: 'passed', reasons: [], independent_validation: false }, reasons: [] }],
    };
}
function statusFixture(board = opportunityFixture()) {
    return { schema_version: 1, state: 'ready', generated_at: '2026-10-04T10:00:00Z', error: null, opportunity_engine: board,
        report: { schema_version: 1, mode: 'research', as_of: '2026-10-04T10:00:00Z', input_fingerprint: 'b'.repeat(64), latest_session: '2026-10-02',
            universe: { ranked_count: 100, quality_count: 100, inspected_count: 100, scope_date: '2026-10-02' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [], forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } },
    };
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('profit opportunity public boundary', () => {
    it('accepts an identified finite reference plan and preserves optional board absence', () => {
        expect(validateOpportunityEngine(opportunityFixture()).candidates[0].symbol).toBe('005930');
        const old = statusFixture(); Reflect.deleteProperty(old, 'opportunity_engine');
        expect(validateAlphaLabStatus(old).report?.candidates).toEqual([]);
    });
    it.each([
        ['nonfinite score', (v: any) => { v.candidates[0].ranking.score = Infinity; }],
        ['duplicate symbol', (v: any) => { v.candidates.push({ ...v.candidates[0], rank: 2 }); v.coverage.selected = 2; }],
        ['foreign decision', (v: any) => { v.candidates[0].decision_id = 'f'.repeat(64); }],
        ['wrong source identity', (v: any) => { v.candidates[0].source_audit_hash = 'f'.repeat(64); }],
        ['reversed stop', (v: any) => { v.candidates[0].plan.stop_price = 63000; }],
        ['different expiry', (v: any) => { v.candidates[0].valid_until = '2026-10-05T06:30:01Z'; }],
        ['invalid calendar day', (v: any) => { v.latest_session = '2026-02-30'; }],
        ['negative weight', (v: any) => { v.candidates[0].reference_weight = -.01; }],
        ['kelly exceeds reference', (v: any) => { v.candidates[0].reference_weight = .05; }],
        ['invented ranking', (v: any) => { v.candidates[0].ranking.conservative_score = .04; }],
        ['raw internal field', (v: any) => { v.candidates[0].private_path = 'hidden'; }],
        ['private text', (v: any) => { v.candidates[0].why_stock = 'C:\\private\\.env'; }],
        ['invented future certainty', (v: any) => { v.candidates[0].next_action = '미래 승률 100% 보장'; }],
    ])('rejects %s before any investor guidance renders', (_, mutate) => {
        const value = opportunityFixture(); mutate(value);
        expect(() => validateOpportunityEngine(value)).toThrow(/응답 형식/);
        expect(() => validateAlphaLabStatus(statusFixture(value))).toThrow(/응답 형식/);
    });
    it('binds an optional board to the current report input', () => {
        const value = statusFixture(); value.report.input_fingerprint = 'f'.repeat(64);
        expect(() => validateAlphaLabStatus(value)).toThrow(/응답 형식/);
    });
    it.each([
        ['stale quote', '2026-10-05T01:06:30Z', false, 'data_check'],
        ['expired window', '2026-10-05T06:30:00Z', false, 'data_check'],
        ['blocked read', '2026-10-05T01:00:00Z', true, 'data_check'],
        ['before entry session', '2026-10-04T11:00:00Z', false, 'wait_next_session'],
    ])('locally downgrades %s without renewing the deadline', (_, time, blocked, action) => {
        const value = validateOpportunityEngine(opportunityFixture());
        const result = effectiveOpportunityEngine(value, Date.parse(time), blocked);
        expect(result.candidates[0].action).toBe(action); expect(result.candidates[0].current_price).toBeNull();
        expect(result.valid_until).toBe('2026-10-05T06:30:00Z'); expect(value.candidates[0].action).toBe('entry_candidate');
    });
    it('ignores a forged entry label with future, foreign-day or delayed fetched quotes', () => {
        for (const times of [['2026-10-05T01:01:00Z', '2026-10-05T01:01:01Z'], ['2026-10-04T01:00:00Z', '2026-10-04T01:00:00Z'], ['2026-10-05T00:55:00Z', '2026-10-05T00:59:45Z']]) {
            const value = opportunityFixture(); [value.candidates[0].quote_at, value.candidates[0].fetched_at] = times;
            const result = effectiveOpportunityEngine(validateOpportunityEngine(value), now);
            expect(result.candidates[0].action).toBe('data_check'); expect(result.candidates[0].current_price).toBeNull();
        }
    });
    it('schedules quote freshness and original entry expiry boundaries', () => {
        expect(opportunityClockExpirations(validateOpportunityEngine(opportunityFixture()))).toContain(Date.parse('2026-10-05T01:06:30Z'));
        expect(opportunityClockExpirations(validateOpportunityEngine(opportunityFixture()))).toContain(Date.parse('2026-10-05T06:30:00Z'));
    });
    it('keeps a verified closed-day next-session wait readable when the board is held', () => {
        const value = opportunityFixture(); value.status = 'held'; value.candidates[0].action = 'wait_next_session';
        Object.assign(value.candidates[0], { current_price: null, quote_at: null, fetched_at: null, quote_source: null });
        value.candidates[0].plan.basis = 'last_closed_price_reference';
        const result = effectiveOpportunityEngine(validateOpportunityEngine(value), Date.parse('2026-10-04T11:00:00Z'));
        expect(result.candidates[0].action).toBe('wait_next_session'); expect(result.candidates[0].reference_weight).toBe(.04);
        expect(result.candidates[0].why_stock).toContain('비용 2배');
    });
    it('cannot keep a claimed entry action when the board is held', () => {
        const value = opportunityFixture(); value.status = 'held';
        const result = effectiveOpportunityEngine(validateOpportunityEngine(value), now);
        expect(result.candidates[0].action).toBe('data_check'); expect(result.candidates[0].current_price).toBeNull();
    });
    it.each(['saved_board_invalid', 'scan_unavailable', 'entry_window_changed', 'entry_window_unavailable', 'source_identity_unavailable', 'calendar_unavailable_or_changed', 'source_unavailable'])('blocks a forged ready label with %s', reason => {
        const value = opportunityFixture(); value.reasons = [reason];
        expect(effectiveOpportunityEngine(validateOpportunityEngine(value), now).candidates[0].action).toBe('data_check');
    });
});
describe('investor opportunity board', () => {
    it('shows ranked stock, entry band and quarter Kelly reference with drilldown', () => {
        const select = vi.fn(); render(<OpportunityBoard board={validateOpportunityEngine(opportunityFixture())} now={now} onSelectSymbol={select} />);
        const row = screen.getByRole('article', { name: /1위.*삼성전자.*005930/ });
        expect(row).toHaveTextContent('60,000원'); expect(row).toHaveTextContent('61,200원'); expect(row).toHaveTextContent('57,000원');
        expect(row).toHaveTextContent('66,000원'); expect(row).toHaveTextContent('4.0%'); expect(row).toHaveTextContent('1/4 Kelly');
        expect(screen.queryByText(/미래 승률 \d/)).not.toBeInTheDocument();
        fireEvent.click(within(row).getByRole('button', { name: /삼성전자 상세 분석/ })); expect(select).toHaveBeenCalledWith('005930');
    });
    it('shows zero candidates without promoting legacy research or implying account performance', () => {
        const value = opportunityFixture(); value.candidates = []; value.coverage.selected = 0;
        render(<OpportunityBoard board={validateOpportunityEngine(value)} now={now} />);
        expect(screen.getByText(/현재 선택된 기회 후보가 없습니다/)).toBeInTheDocument();
        expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(screen.queryByText(/승리 비율/)).not.toBeInTheDocument();
    });
    it('uses the existing authenticated lifecycle and hides old primary cards in a disclosure', async () => {
        api.fetchAuthAPI.mockResolvedValue(statusFixture()); const view = render(<AlphaLabPanel token="member" />); await act(async () => {});
        expect(screen.getByRole('region', { name: '수익 기회 순위' })).toBeInTheDocument();
        const summary = screen.getByText('이전 연구 제안 · 근거 펼치기'); expect(summary.closest('details')).not.toHaveAttribute('open');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1); expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab', 'member');
        expect(api.postAuthAPI).not.toHaveBeenCalled(); view.unmount(); await act(async () => { await vi.advanceTimersByTimeAsync(600000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('expires a saved current quote while idle without an additional poll or provider call', async () => {
        const value = statusFixture(); value.opportunity_engine.candidates[0].quote_at = '2026-10-05T00:53:01Z';
        value.opportunity_engine.candidates[0].fetched_at = '2026-10-05T00:53:15Z';
        api.fetchAuthAPI.mockResolvedValue(value); render(<AlphaLabPanel />); await act(async () => {});
        expect(screen.getByRole('article', { name: /1위.*삼성전자/ })).toHaveTextContent('진입 조건 충족');
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.getByRole('article', { name: /1위.*삼성전자/ })).toHaveTextContent('가격 확인 대기');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('suppresses retained entry guidance after read failure and removes another token board', async () => {
        api.fetchAuthAPI.mockResolvedValueOnce(statusFixture()).mockRejectedValueOnce(new Error('private trace'));
        const view = render(<AlphaLabPanel token="old" />); await act(async () => {});
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' })); await act(async () => {});
        expect(screen.getByRole('article', { name: /1위.*삼성전자/ })).toHaveTextContent('가격 확인 대기');
        expect(screen.queryByText(/private trace/)).not.toBeInTheDocument();
        api.fetchAuthAPI.mockReturnValue(new Promise(() => {})); view.rerender(<AlphaLabPanel token="new" />);
        expect(screen.queryByRole('region', { name: '수익 기회 순위' })).not.toBeInTheDocument();
    });
});
