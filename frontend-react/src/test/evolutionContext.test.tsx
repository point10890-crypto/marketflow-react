import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, within } from '@testing-library/react';
import { validateAlphaLabStatus } from '@/lib/alphaLabApi';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { validateEvolutionContext } from '@/lib/evolutionContext';
import { validateOpportunityEngine } from '@/lib/opportunityEngine';
import { completedEvolutionFixture, evolutionBoardFixture, evolutionFixture, evolutionNow, evolutionStatusFixture } from './fixtures/evolutionFixture';
import engineFixtureJson from './fixtures/alphaEvolutionEngineStatus.json?raw';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);

const decisionAt = '2026-10-14T11:30:00Z';
const now = Date.parse('2026-10-14T12:00:00Z');
function statusFixture(evolution?: unknown) {
    return { schema_version: 1, state: 'held', generated_at: decisionAt, error: null,
        ...(evolution === undefined ? {} : { evolution }),
        report: { schema_version: 1, mode: 'research', as_of: decisionAt,
            universe: { ranked_count: 100, quality_count: 42, inspected_count: 42, scope_date: '2026-10-14' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [],
            forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } },
    };
}
beforeEach(() => { vi.spyOn(Date, 'now').mockReturnValue(evolutionNow); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('optional evolution public boundary', () => {
    it('drops malformed optional evidence while preserving the original research result and payload', () => {
        vi.spyOn(Date, 'now').mockReturnValue(now);
        const raw = statusFixture({ private_path: 'C:\\private\\.env', mean_net_return: Infinity });
        const original = structuredClone(raw);
        const result = validateAlphaLabStatus(raw);
        expect(result).not.toHaveProperty('evolution');
        expect(result.report?.universe.quality_count).toBe(42);
        expect(raw).toEqual(original);
    });
    it('preserves legacy absence without attaching evidence', () => {
        expect(validateAlphaLabStatus(statusFixture())).not.toHaveProperty('evolution');
    });
    it('accepts paired negative evidence without changing selected inputs or source records', () => {
        const raw = evolutionStatusFixture(); const original = structuredClone(raw);
        const result = validateAlphaLabStatus(raw);
        expect(result.evolution?.arms[0].metrics.mean_net_return).toBe(-.01);
        expect(result.evolution?.arms[1].counts.revised).toBe(1);
        expect(result.evolution?.binding_status).toBe('current');
        expect(raw).toEqual(original);
    });
    it('preserves actual review sample counts without treating them as a qualified strategy', () => {
        const raw = evolutionFixture(); raw.review.entered_outcomes = 1; raw.review.control_entered_outcomes = 1;
        const result = validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()));
        expect(result).toBeDefined();
        expect(result?.review.status).toBe('collecting');
    });
    it('accepts the engine-produced synthetic public schema through the store wrapper', () => {
        const engineValue = JSON.parse(engineFixtureJson) as Record<string, unknown>;
        const raw = { ...evolutionFixture(), ...engineValue };
        const board = validateOpportunityEngine({ ...evolutionBoardFixture(), ...(engineValue.binding as Record<string, string>) });
        const result = validateEvolutionContext(raw, board);
        expect(result?.arms[0].selected.map(row => row.symbol)).toEqual(['000001', '000004', '000002']);
        expect(result?.window.enrolled_sessions).toBe(1);
        expect(result?.arms[0].counts.paired_sessions).toBe(1);
    });
    it('rejects a review phase without a completed independent confirmation review', () => {
        const raw = evolutionFixture(); raw.phase = 'awaiting_review';
        expect(validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()))).toBeUndefined();
    });
    it('rejects a candidate review with unresolved source-bound results', () => {
        const raw = completedEvolutionFixture(); raw.window.resolved_sessions = 105; raw.arms.forEach(arm => { arm.counts.paired_sessions = 105; });
        expect(validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()))).toBeUndefined();
    });
    it('rejects a candidate review with revised selected outcomes', () => {
        const raw = completedEvolutionFixture(); raw.arms[1].counts.revised = 1;
        expect(validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()))).toBeUndefined();
    });
    it('holds qualification when the control lacks thirty independent entered outcomes', () => {
        const raw = completedEvolutionFixture(); raw.review.control_entered_outcomes = 0;
        expect(validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()))).toBeUndefined();
    });
    it('explains actual engine holds in readable Korean', async () => {
        const engineValue = JSON.parse(engineFixtureJson) as Record<string, unknown>;
        const raw = { ...evolutionFixture(), ...engineValue };
        const status = evolutionStatusFixture(raw);
        Object.assign(status.opportunity_engine, engineValue.binding);
        status.report.input_fingerprint = String(status.opportunity_engine.input_fingerprint);
        api.fetchAuthAPI.mockResolvedValue(status);
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('고정된 미래 평가 구간이 아직 완료되지 않았습니다.');
        expect(region).toHaveTextContent('고정된 지명 비교군이 아직 없습니다.');
        expect(region).not.toHaveTextContent('fixed_window_incomplete');
    });
    it('keeps a completed research candidate awaiting human review with zero exposure and no orders', async () => {
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(completedEvolutionFixture()));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('연구 후보 · 검토 대기');
        expect(region).toHaveTextContent('승인 노출 0 · 주문 실행 없음');
    });
    it.each(['decision_id', 'input_fingerprint', 'source_audit_hash'] as const)('holds a foreign %s without exposing current selections or performance', key => {
        const raw = evolutionFixture(); raw.binding[key] = 'f'.repeat(64);
        const result = validateEvolutionContext(raw, validateOpportunityEngine(evolutionBoardFixture()));
        expect(result?.binding_status).toBe('mismatch');
        expect(result?.arms.every(arm => arm.selected.length === 0 && Object.values(arm.metrics).every(value => value === null))).toBe(true);
        expect(result?.reasons).toContain('current_identity_mismatch');
    });
    it.each([
        ['nonfinite net return', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].metrics.mean_net_return = Infinity; }],
        ['nonfinite review statistic', (v: ReturnType<typeof evolutionFixture>) => { v.review.block_lower_bound = NaN; }],
        ['future saved status', (v: ReturnType<typeof evolutionFixture>) => { v.generated_at = '2026-10-14T12:00:01Z'; }],
        ['impossible calendar date', (v: ReturnType<typeof evolutionFixture>) => { v.generated_at = '2026-02-30T11:40:00Z'; }],
        ['duplicate fixed arm', (v: ReturnType<typeof evolutionFixture>) => { v.arms[1].id = 'control'; }],
        ['extra fixed arm', (v: ReturnType<typeof evolutionFixture>) => { v.arms.push(structuredClone(v.arms[0])); }],
        ['negative outcome count', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].counts.closed = -1; }],
        ['unresolved evidence presented as a metric', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].counts.paired_sessions = 0; }],
        ['invalid exposure authorization', (v: ReturnType<typeof evolutionFixture>) => { v.approved_exposure = .1; }],
        ['live orders authorization', (v: ReturnType<typeof evolutionFixture>) => { v.live_orders = true; }],
        ['too many selections', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].selected = Array(4).fill(v.arms[0].selected[0]); }],
        ['duplicate current stock', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].selected.push(structuredClone(v.arms[0].selected[0])); }],
        ['sensitive reason text', (v: ReturnType<typeof evolutionFixture>) => { v.reasons = ['C:\\private\\.env']; }],
        ['unsupported probability', (v: ReturnType<typeof evolutionFixture>) => { Object.assign(v.arms[0].metrics, { win_probability: .9 }); }],
        ['negative tail-loss magnitude', (v: ReturnType<typeof evolutionFixture>) => { v.arms[0].metrics.downside_tail_loss = -.02; }],
        ['numeric current symbol', (v: ReturnType<typeof evolutionFixture>) => { Object.assign(v.arms[0].selected[0], { symbol: 123456 }); }],
        ['array strategy identifier', (v: ReturnType<typeof evolutionFixture>) => { Object.assign(v.arms[0].selected[0], { strategy_id: ['mean_reversion'] }); }],
        ['array artifact status', (v: ReturnType<typeof evolutionFixture>) => { Object.assign(v, { status: ['ready'] }); }],
        ['array phase', (v: ReturnType<typeof evolutionFixture>) => { Object.assign(v, { phase: ['collecting_nomination'] }); }],
    ])('discards %s optional data without breaking the board', (_label, mutate) => {
        const raw = evolutionFixture(); mutate(raw);
        const result = validateAlphaLabStatus(evolutionStatusFixture(raw));
        expect(result).not.toHaveProperty('evolution');
        expect(result.opportunity_engine?.decision_id).toBe('a'.repeat(64));
    });
    it.each([false, true])('renders shared four-arm evidence for desk=%s with actual next step, names and revised counts', async desk => {
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture());
        render(<AlphaLabPanel token="member" desk={desk} />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('다음 결정 거래일의 첫 선정과 종료 결과를 관측합니다.');
        expect(region).toHaveTextContent('삼성전자'); expect(region).toHaveTextContent('005930');
        expect(region).toHaveTextContent('106'); expect(region).toHaveTextContent('수정 제외 1');
        expect(within(region).getAllByRole('article')).toHaveLength(4);
        expect(region).toHaveTextContent('-1.00%'); expect(region).toHaveTextContent('-1.40%');
        expect(region).toHaveTextContent('결과 확정 3'); expect(region).toHaveTextContent('종료 1');
        expect(region).toHaveTextContent('진입 생략 1'); expect(region).toHaveTextContent('연구 후보 판단 보류');
        expect(region).toHaveTextContent('관심목록'); expect(region).toHaveTextContent('계좌 수익');
        expect(within(region).queryByText(/승률|성공 확률|전략 승격/)).not.toBeInTheDocument();
    });
    it('shows null metrics as unknown rather than zero or a win while keeping named selections readable', async () => {
        const value = evolutionFixture(); value.window.resolved_sessions = 0;
        value.arms.forEach(arm => { arm.counts.paired_sessions = 0; Object.assign(arm.metrics, { mean_net_return: null, stress_mean_net_return: null, paired_advantage: null, stress_paired_advantage: null, downside_tail_loss: null }); });
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(value));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('미산출'); expect(region).toHaveTextContent('삼성전자');
        expect(within(region).queryByText(/0\.00%/)).not.toBeInTheDocument();
    });
    it('renders a visible identity hold instead of a foreign current stock or stale return', async () => {
        const value = evolutionFixture(); value.binding.decision_id = 'f'.repeat(64);
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(value));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('현재 선정 연결 보류');
        expect(region).toHaveTextContent('현재 화면의 선정과 관측 자료가 일치하지 않습니다.');
        expect(within(region).queryByText(/삼성전자|005930|-1\.00%/)).not.toBeInTheDocument();
    });
    it('keeps a foreign completed candidate visibly held after the API and component both validate it', async () => {
        const value = completedEvolutionFixture(); value.binding.decision_id = 'f'.repeat(64);
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(value));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('현재 선정 연결 보류');
        expect(region).toHaveTextContent('연구 후보 판단 보류');
        expect(within(region).queryByText(/삼성전자|005930/)).not.toBeInTheDocument();
    });
    it('distinguishes unavailable current selection from a known no-selection result while retaining labeled historical aggregates', async () => {
        const value = evolutionFixture(); value.reasons = ['current_selection_unavailable']; value.arms.forEach(arm => { arm.selected = []; });
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(value));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('현재 선정 연결 확인 대기');
        expect(region).not.toHaveTextContent('현재 조건 통과 종목 없음');
        expect(region).toHaveTextContent('-1.00%');
    });
    it('explains the actual saved-refresh failure without showing old stocks as current', async () => {
        const value = evolutionFixture(); value.status = 'held'; value.reasons = ['last_refresh_failed'];
        api.fetchAuthAPI.mockResolvedValue(evolutionStatusFixture(value));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        const region = screen.getByRole('region', { name: '알파 진화 관측' });
        expect(region).toHaveTextContent('최근 관측 갱신에 실패하여 저장 자료를 확인해야 합니다.');
        expect(region).not.toHaveTextContent('last_refresh_failed');
        expect(within(region).queryByText(/삼성전자|005930/)).not.toBeInTheDocument();
    });
    it('adds no visible panel for legacy absence and performs only the existing status request', async () => {
        const value = evolutionStatusFixture(); Reflect.deleteProperty(value, 'evolution');
        api.fetchAuthAPI.mockResolvedValue(value);
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        expect(screen.queryByRole('region', { name: '알파 진화 관측' })).not.toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
});
