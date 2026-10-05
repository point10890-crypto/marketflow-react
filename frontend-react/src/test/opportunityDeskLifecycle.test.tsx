import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, useLocation } from 'react-router-dom';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import AiBainDashboard from '@/pages/dashboard/aibain/AiBainDashboard';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'member', user: { role: 'user' } }) }));
const now = Date.parse('2026-10-05T01:00:00Z');
function savedStatus(symbol = '005930', name = '삼성전자') {
    const identity = { decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), source_audit_hash: 'c'.repeat(64) };
    return { schema_version: 1, state: 'ready', generated_at: '2026-10-04T10:00:00Z', error: null,
        opportunity_engine: { schema_version: 1, policy_version: 'profit-opportunity-v1', ...identity, generated_at: '2026-10-04T10:00:00Z',
            latest_session: '2026-10-02', entry_session: '2026-10-05', valid_until: '2026-10-05T06:30:00Z', status: 'ready', research_only: true, live_orders: false,
            coverage: { inspected: 100, eligible: 7, selected: 1 }, alternatives: [], reasons: [],
            stages: [{ id: 'data', status: 'passed', detail: '저장 가격과 출처 확인', count: 100 }],
            evaluation: { basis: 'issued_opportunities_not_fills', issued: 1, pending: 1, expired: 0, observed: 0, unobserved: 0 },
            candidates: [{ ...identity, opportunity_id: 'd'.repeat(64), symbol, name, market: 'KR', strategy_id: 'momentum', rank: 1,
                action: 'entry_candidate', label: '현재 진입 후보', why_stock: '비용 2배 조건부 평균과 불확실성을 대조했습니다.',
                why_now: '새 관측 가격이 참고 상한 안에 있습니다.', next_action: '참고 가격과 손실 한도를 직접 확인하세요.',
                quote_session: '2026-10-02', source_at: '2026-10-04T09:00:00Z', current_price: 60000,
                quote_at: '2026-10-05T00:59:30Z', fetched_at: '2026-10-05T00:59:45Z', quote_source: 'KIS:J:FHKST03010200+FHKST01010100',
                valid_until: '2026-10-05T06:30:00Z', reference_weight: .04,
                plan: { basis: 'observed_quote_reference', entry_low: 60000, entry_high: 61200, stop_price: 57000, target_price: 66000, horizon_sessions: 10 },
                ranking: { stress_mean_net_return: .03, standard_error: .005, conservative_score: .0202, correlation_penalty: 0, score: .0202, calibration_samples: 40, confirmation_samples: 20 },
                kelly: { raw_fraction: .16, fraction: .25, cap: .05, account_risk_cap: .01 },
                audit: { status: 'passed', reasons: [], independent_validation: false }, reasons: [] }],
        },
        report: { schema_version: 1, mode: 'research', as_of: '2026-10-04T10:00:00Z', input_fingerprint: 'b'.repeat(64), latest_session: '2026-10-02',
            universe: { ranked_count: 100, quality_count: 100, inspected_count: 100, scope_date: '2026-10-02' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [], forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } },
    };
}
function deferred<T>() {
    let resolve!: (value: T) => void;
    const promise = new Promise<T>(done => { resolve = done; });
    return { promise, resolve };
}
function Location() {
    const location = useLocation();
    return <output aria-label="현재 경로">{location.pathname}{location.search}</output>;
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(now); api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('saved opportunity desk lifecycle', () => {
    it('reads saved guidance without scan actions, legacy evidence or automatic API polling', async () => {
        api.fetchAuthAPI.mockResolvedValue(savedStatus());
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        expect(screen.getByRole('region', { name: '유력 종목 데스크' })).toBeInTheDocument();
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('진입 조건 충족');
        expect(screen.queryByRole('button', { name: '매수 후보 검출' })).not.toBeInTheDocument();
        expect(screen.queryByText('이전 연구 제안 · 근거 펼치기')).not.toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(600000); });
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('가격 확인 대기');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/alpha-lab', 'member');
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('clears a previous token immediately and ignores its late refresh response', async () => {
        const previous = deferred<ReturnType<typeof savedStatus>>(), next = deferred<ReturnType<typeof savedStatus>>();
        api.fetchAuthAPI.mockResolvedValueOnce(savedStatus()).mockReturnValueOnce(previous.promise).mockReturnValueOnce(next.promise);
        const view = render(<AlphaLabPanel token="old" desk />); await act(async () => {});
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('가격 확인 대기');
        view.rerender(<AlphaLabPanel token="new" desk />);
        expect(screen.queryByRole('article')).not.toBeInTheDocument();
        await act(async () => { previous.resolve(savedStatus()); });
        expect(screen.queryByRole('article')).not.toBeInTheDocument();
        await act(async () => { next.resolve(savedStatus('000660', 'SK하이닉스')); });
        expect(screen.getByRole('article', { name: /SK하이닉스/ })).toBeInTheDocument();
        expect(screen.queryByRole('article', { name: /삼성전자/ })).not.toBeInTheDocument();
    });
    it('downgrades retained guidance on failed manual refresh and hides private errors', async () => {
        api.fetchAuthAPI.mockResolvedValueOnce(savedStatus()).mockRejectedValueOnce(new Error('private trace'));
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' })); await act(async () => {});
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('가격 확인 대기');
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.queryByText(/private trace/)).not.toBeInTheDocument();
        expect(api.postAuthAPI).not.toHaveBeenCalled();
    });
    it('explains a running saved job without scheduling automatic reads', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...savedStatus(), state: 'running' });
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        expect(screen.getByText(/완료 후 저장 결과 새로고침/)).toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('가격 확인 대기');
    });
    it('rechecks freshness on focus without renewing entry expiry or fetching', async () => {
        api.fetchAuthAPI.mockResolvedValue(savedStatus());
        render(<AlphaLabPanel token="member" desk />); await act(async () => {});
        vi.setSystemTime(Date.parse('2026-10-05T06:30:00Z'));
        act(() => { window.dispatchEvent(new Event('focus')); });
        expect(screen.getByRole('article', { name: /삼성전자/ })).toHaveTextContent('가격 확인 대기');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
    it('keeps the desk independent of failed overview and opens a validated six-digit detail', async () => {
        api.fetchAuthAPI.mockImplementation(async (path: string) => {
            if (path === '/api/admin/mirofish/alpha-lab') return savedStatus();
            if (path.startsWith('/api/kr/alpha-core/')) return null;
            throw new Error('overview unavailable');
        });
        render(<MemoryRouter><AiBainDashboard /><Location /></MemoryRouter>); await act(async () => {});
        expect(screen.getByRole('region', { name: '유력 종목 데스크' })).toBeInTheDocument();
        expect(screen.getByText('데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: '삼성전자 상세 분석' }));
        expect(screen.getByLabelText('현재 경로')).toHaveTextContent('/dashboard/ai-bain/chart-predict?code=005930');
    });
    it.each(['12345', '005930&unsafe=true'])('rejects malformed %s before exposing detail navigation', async symbol => {
        api.fetchAuthAPI.mockImplementation(async (path: string) => {
            if (path === '/api/admin/mirofish/alpha-lab') return savedStatus(symbol);
            if (path.startsWith('/api/kr/alpha-core/')) return null;
            throw new Error('overview unavailable');
        });
        render(<MemoryRouter><AiBainDashboard /><Location /></MemoryRouter>); await act(async () => {});
        expect(screen.getByRole('region', { name: '유력 종목 데스크' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: '삼성전자 상세 분석' })).not.toBeInTheDocument();
        expect(screen.getByLabelText('현재 경로')).toHaveTextContent(/^\/$/);
    });
});
