import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import * as authContext from '@/contexts/AuthContext';
import * as candidateDesk from '@/lib/candidateDesk';
import CandidateDeskPanel from '@/components/aibain/CandidateDeskPanel';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { validateAlphaLabStatus } from '@/lib/alphaLabApi';
import { candidateDeskFixture, candidateDeskNow, candidateEntryNow, candidateMonitoringFixture, candidateStatusFixture, contextualCandidateDeskFixture } from './fixtures/candidateDeskFixture';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => api);
beforeEach(() => { vi.spyOn(Date, 'now').mockReturnValue(candidateDeskNow); api.fetchAuthAPI.mockReset(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('candidate desk boundary', () => {
    it('accepts identified finite source-bound candidates without mutating the payload', () => {
        const raw = candidateDeskFixture(); const original = structuredClone(raw);
        const parsed = candidateDesk.validateCandidateDesk(raw, candidateDeskNow);
        expect(parsed?.candidates).toHaveLength(3);
        expect(candidateDesk.candidateDeskEntryAvailable(parsed!, candidateDeskNow)).toBe(true);
        expect(raw).toEqual(original);
    });
    it.each([
        ['unknown policy', (v: any) => { v.policy_version = 'unreviewed-v4'; }],
        ['invalid decision identity', (v: any) => { v.decision_id = 'old'; }],
        ['invalid source identity', (v: any) => { v.input_fingerprint = 'old'; }],
        ['future creation', (v: any) => { v.generated_at = '2026-10-23T11:45:00Z'; }],
        ['future capture', (v: any) => { v.source.captured_at = '2026-10-23T11:40:00Z'; }],
        ['uncompleted session', (v: any) => { v.generated_at = '2026-10-22T11:00:00Z'; v.source.captured_at = '2026-10-22T10:50:00Z'; }],
        ['backdated entry', (v: any) => { v.entry_session = '2026-10-22'; v.valid_until = '2026-10-22T06:30:00Z'; }],
        ['expiry outside official close', (v: any) => { v.valid_until = '2026-10-23T07:00:00Z'; }],
        ['foreign source', (v: any) => { v.source.provider = 'NAVER'; }],
        ['unverified numeric claim', (v: any) => { v.candidates[0].strength_score = Infinity; }],
        ['wrong quote session', (v: any) => { v.candidates[0].quote_session = '2026-10-21'; }],
        ['duplicate symbol', (v: any) => { v.candidates[1].symbol = v.candidates[0].symbol; }],
        ['duplicate rank', (v: any) => { v.candidates[1].rank = 1; }],
        ['bad stop', (v: any) => { v.candidates[0].plan.stop_price = 62000; }],
        ['bad target', (v: any) => { v.candidates[0].plan.target_price = 61000; }],
        ['inconsistent loss', (v: any) => { v.candidates[0].plan.loss_fraction = .08; }],
        ['excess weight', (v: any) => { v.candidates[0].risk.reference_weight = .06; }],
        ['zero Kelly', (v: any) => { v.candidates[0].risk.raw_kelly = 0; }],
        ['live execution', (v: any) => { v.live_orders = true; }],
        ['approved exposure', (v: any) => { v.candidates[0].risk.approved_exposure = .05; }],
        ['missing pooled coverage', (v: any) => { v.evidence.confirmation.block_count = 2; }],
        ['negative stressed economics', (v: any) => { v.evidence.formation.stress_mean_net_return = -.01; }],
        ['invalid wins', (v: any) => { v.evidence.formation.wins = 31; }],
        ['unsupported certainty claim', (v: any) => { v.candidates[0].reason_facts = ['수익 보장']; }],
    ])('suppresses malformed proposals: %s', (_, change) => {
        const raw = candidateDeskFixture(); change(raw);
        expect(candidateDesk.validateCandidateDesk(raw, candidateDeskNow)).toBeUndefined();
    });
    it('allows held zero-sample evidence and ignores additional fields at the boundary', () => {
        const raw: any = candidateDeskFixture(0); raw.state = 'held'; raw.entry_session = null; raw.valid_until = null;
        raw.evidence.formation = raw.evidence.confirmation = { samples: 0, wins: 0, win_rate: null, mean_net_return: null,
            stress_mean_net_return: null, block_count: 0, unique_symbols: 0 };
        raw.extra_audit = { fixed: true };
        expect(candidateDesk.validateCandidateDesk(raw, candidateDeskNow)?.evidence.formation.mean_net_return).toBeNull();
    });
    it('preserves a valid ranking gap when a higher-ranked plan was rejected without padding', () => {
        const raw = candidateDeskFixture(2); raw.candidates[1].rank = 3;
        expect(candidateDesk.validateCandidateDesk(raw, candidateDeskNow)?.candidates.map(row => row.rank)).toEqual([1, 3]);
    });
    it.each(['held', 'running', 'failed'])('holds retained %s proposals', state => {
        const raw = candidateDeskFixture(); raw.state = state;
        const desk = candidateDesk.validateCandidateDesk(raw, candidateDeskNow)!;
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateDeskNow)).toBe(false);
    });
    it('holds expired, stale and externally blocked proposals', () => {
        const desk = candidateDesk.validateCandidateDesk(candidateDeskFixture(), candidateDeskNow)!;
        expect(candidateDesk.candidateDeskEntryAvailable(desk, Date.parse('2026-10-23T06:30:00Z'))).toBe(false);
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateDeskNow, true)).toBe(false);
        const raw = candidateDeskFixture(); raw.source.captured_at = '2026-10-14T11:40:00Z'; raw.latest_session = '2026-10-14';
        raw.candidates.forEach(row => { row.quote_session = '2026-10-14'; });
        const stale = candidateDesk.validateCandidateDesk(raw, candidateDeskNow)!;
        expect(candidateDesk.candidateDeskEntryAvailable(stale, candidateDeskNow)).toBe(false);
    });
    it('preserves old API responses and marks only invalid optional desk unavailable', () => {
        const legacy = candidateStatusFixture();
        expect(validateAlphaLabStatus(legacy).candidate_desk).toBeUndefined();
        const raw = { ...legacy, candidate_desk: { ...candidateDeskFixture(), policy_version: 'invalid' } };
        const parsed = validateAlphaLabStatus(raw);
        expect(parsed.report).toEqual(legacy.report);
        expect(parsed.candidate_desk).toBeUndefined();
        expect(parsed.candidate_desk_unavailable).toBe(true);
    });
});

describe('candidate desk cards', () => {
    it.each([1, 2, 3])('renders %i candidates with plans and working symbol navigation', count => {
        const onSelectSymbol = vi.fn();
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(candidateDeskFixture(count), candidateDeskNow)} now={candidateDeskNow} onSelectSymbol={onSelectSymbol} />);
        const panel = screen.getByRole('region', { name: '시장 비교 후보' });
        expect(within(panel).getAllByRole('article')).toHaveLength(count);
        const first = within(panel).getByRole('article', { name: '1위 삼성전자 005930' });
        expect(first).toHaveTextContent('조건부 매수 제안');
        expect(within(first).getByText('기준 진입').nextElementSibling).toHaveTextContent('60,000원');
        expect(within(first).getByText('추격 상한 (+2%)').nextElementSibling).toHaveTextContent('61,200원');
        expect(first).not.toHaveTextContent('60,000원 ~ 61,200원');
        expect(first).toHaveTextContent('상한 초과·손절선 이하 시 진입하지 않습니다. 실제 시가로 가격을 다시 계산합니다.');
        expect(first).toHaveTextContent('57,000원'); expect(first).toHaveTextContent('66,000원');
        expect(first).toHaveTextContent('최대 10거래일'); expect(first).toHaveTextContent('연구 참고 비중 5.0%');
        expect(first).toHaveTextContent('KIS · KRX'); expect(first).toHaveTextContent('2026-10-22 종가');
        expect(first).toHaveTextContent('60거래일 이동평균 위');
        fireEvent.click(within(first).getByRole('button', { name: '삼성전자 005930 상세 분석' }));
        expect(onSelectSymbol).toHaveBeenCalledWith('005930');
        expect(panel).not.toHaveTextContent(/수익 보장|상승 확률/);
    });
    it('shows the empty funnel and exact rejection categories', () => {
        const raw = candidateDeskFixture(0); raw.state = 'held'; raw.reasons = ['confirmation_samples_insufficient'];
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.getByText('현재 조건을 통과한 후보가 없습니다.')).toBeVisible();
        expect(screen.getByLabelText('후보 선별 단계')).toHaveTextContent('검사 종목52');
        expect(screen.getByText(/confirmation_samples_insufficient/)).toBeVisible();
        fireEvent.click(screen.getByText('과거 검증 근거 · 한계'));
        expect(screen.getByText(/독립 시행/)).toBeVisible();
    });
    it('renders the detector source facts and funnel labels in Korean without changing their numbers', () => {
        const raw = candidateDeskFixture(1);
        raw.candidates[0].reason_facts = ['20-session return 12.30%; cohort median 5.00%.',
            '60-session return 22.10%; SMA20 above SMA60.', '20-session average traded value KRW 1,234,567,890.',
            'Prior-20-high ratio 0.980; volume ratio capped at 3: 1.50.'];
        raw.funnel[0].label = 'Inspected quality-cohort symbols';
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.getByRole('article')).toHaveTextContent('20거래일 수익률 12.30% · 코호트 중앙값 5.00%');
        expect(screen.getByRole('article')).toHaveTextContent('60거래일 수익률 22.10%');
        expect(screen.getByRole('article')).toHaveTextContent('20거래일 평균 거래대금 1,234,567,890원');
        expect(screen.getByLabelText('후보 선별 단계')).toHaveTextContent('검사 종목52');
    });
    it.each(['held', 'running', 'failed'])('marks retained %s cards unavailable for new entry', state => {
        const raw = candidateDeskFixture(1); raw.state = state;
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.getByRole('article')).toHaveTextContent('신규 진입 불가');
        expect(screen.queryByText('조건부 매수 제안')).not.toBeInTheDocument();
    });
    it('removes actionable language at expiry without hiding the saved reference plan', () => {
        const desk = candidateDesk.validateCandidateDesk(candidateDeskFixture(1), candidateDeskNow);
        const view = render(<CandidateDeskPanel desk={desk} now={candidateDeskNow} />);
        expect(screen.getByText('조건부 매수 제안')).toBeVisible();
        view.rerender(<CandidateDeskPanel desk={desk} now={Date.parse('2026-10-23T06:30:00Z')} />);
        expect(screen.queryByText('조건부 매수 제안')).not.toBeInTheDocument();
        expect(screen.getByRole('article')).toHaveTextContent('신규 진입 불가');
        expect(screen.getByRole('article')).toHaveTextContent('60,000원');
        expect(screen.getByRole('article')).toHaveTextContent('61,200원');
    });
    it('renders an unavailable state for malformed optional payloads', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...candidateStatusFixture(), candidate_desk: { policy_version: 'invalid' } });
        render(<AlphaLabPanel desk />);
        expect(await screen.findByText('시장 비교 후보를 확인할 수 없습니다. 저장 결과를 새로고침해 주세요.')).toBeVisible();
        expect(screen.queryByText('조건부 매수 제안')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: '저장 결과 새로고침' })).toBeVisible();
    });
    it('leads the existing desk with the new candidate panel and preserves legacy diagnostics', async () => {
        api.fetchAuthAPI.mockResolvedValue({ ...candidateStatusFixture(), candidate_desk: candidateDeskFixture(1) });
        render(<AlphaLabPanel desk />);
        expect(await screen.findByText('조건부 매수 제안')).toBeVisible();
        expect(screen.getByText('기존 실험 · 관측 근거')).toBeVisible();
        expect(screen.queryByText(/저장된 유력 종목 후보가 없습니다/)).not.toBeInTheDocument();
    });
    it.each([true, false])('prioritizes saved proposals before admin search while preserving legacy order: candidate desk %s', async hasCandidateDesk => {
        vi.spyOn(authContext, 'useAuth').mockReturnValue({
            user: { id: 1, email: 'admin@example.test', name: '관리자', tier: 'pro', role: 'admin', status: 'approved' },
            token: 'test-admin-token', loading: false, login: vi.fn(), logout: vi.fn(), isAdmin: () => true,
            refreshUser: vi.fn(), setSession: vi.fn(),
        });
        api.fetchAuthAPI.mockResolvedValue({ ...candidateStatusFixture(), ...(hasCandidateDesk ? { candidate_desk: candidateDeskFixture(1) } : {}) });
        render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AlphaLabPanel isAdmin /></MemoryRouter>);
        await screen.findByText('기존 실험 후보 · 제외 근거');
        const adminSearch = screen.getByRole('region', { name: '관리자 전용 종목 검색 분석' });
        if (hasCandidateDesk) {
            const proposals = screen.getByRole('region', { name: '시장 비교 후보' });
            expect(proposals.compareDocumentPosition(adminSearch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        } else {
            const legacy = screen.getByText('기존 실험 후보 · 제외 근거');
            expect(adminSearch.compareDocumentPosition(legacy) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        }
    });
    it('expires the mounted candidate desk at the official close without a network read', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date('2026-10-23T06:29:59Z'));
        const monitoring = candidateMonitoringFixture(1); monitoring.checked_at = '2026-10-23T06:29:59Z';
        Object.assign(monitoring.quotes[0], { quote_at: '2026-10-23T06:29:30Z', fetched_at: '2026-10-23T06:29:55Z' });
        api.fetchAuthAPI.mockResolvedValue({ ...candidateStatusFixture(), candidate_desk: { ...candidateDeskFixture(1), monitoring } });
        render(<AlphaLabPanel desk />); await act(async () => {});
        expect(screen.getByText('조건부 매수 제안')).toBeVisible();
        await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
        expect(screen.queryByText('조건부 매수 제안')).not.toBeInTheDocument();
        expect(screen.getByRole('article')).toHaveTextContent('신규 진입 불가');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
});

describe('candidate entry-day monitoring', () => {
    it('shows fresh bound current and opening prices while accepting an opening below the reference close', () => {
        const raw = { ...contextualCandidateDeskFixture(1), monitoring: candidateMonitoringFixture(1) };
        const desk = candidateDesk.validateCandidateDesk(raw, candidateEntryNow);
        expect(desk?.monitoring?.quotes[0].price).toBe(60500);
        render(<CandidateDeskPanel desk={desk} now={candidateEntryNow} />);
        const card = screen.getByRole('article');
        expect(card).toHaveTextContent('실험적 조건부 매수 후보');
        expect(card).toHaveTextContent('현재 관측 60,500원');
        expect(card).toHaveTextContent('시가 59,000원');
        expect(card).toHaveTextContent('연구 참고 비중 1.0%');
    });
    it('suppresses a skipped price plan without holding the other fresh candidate', () => {
        const raw = { ...contextualCandidateDeskFixture(2), monitoring: candidateMonitoringFixture(2) };
        Object.assign(raw.monitoring.quotes[1], { state: 'skip', price: 63000, opening_price: 62000 });
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateEntryNow)} now={candidateEntryNow} />);
        const cards = screen.getAllByRole('article');
        expect(cards[0]).toHaveTextContent('실험적 조건부 매수 후보');
        expect(cards[0]).toHaveTextContent('연구 참고 비중 1.0%');
        expect(cards[1]).toHaveTextContent('진입 제외 · 가격 조건 이탈');
        expect(cards[1]).toHaveTextContent('연구 참고 비중 0.0%');
        expect(cards[1]).not.toHaveTextContent('실험적 조건부 매수 후보');
        expect(cards[1]).toHaveTextContent('기준 진입60,000원');
    });
    it('isolates a malformed quote to its own candidate', () => {
        const raw = { ...contextualCandidateDeskFixture(2), monitoring: candidateMonitoringFixture(2) };
        raw.monitoring.quotes[0].price = Infinity;
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateEntryNow)} now={candidateEntryNow} />);
        const cards = screen.getAllByRole('article');
        expect(cards[0]).toHaveTextContent('시가 확인 대기');
        expect(cards[0]).toHaveTextContent('연구 참고 비중 0.0%');
        expect(cards[1]).toHaveTextContent('실험적 조건부 매수 후보');
    });
    it.each([[120000, true], [120001, false], [181000, false]])('requires a quote acquired within 120 seconds: %i ms', (age, accepted) => {
        const raw = { ...contextualCandidateDeskFixture(1), monitoring: candidateMonitoringFixture(1) };
        raw.monitoring.quotes[0].fetched_at = '2026-10-23T00:05:00Z';
        raw.monitoring.quotes[0].quote_at = new Date(candidateEntryNow - age).toISOString();
        const desk = candidateDesk.validateCandidateDesk(raw, candidateEntryNow);
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateEntryNow)).toBe(accepted);
        render(<CandidateDeskPanel desk={desk} now={candidateEntryNow} />);
        expect(screen.getByRole('article')).toHaveTextContent(accepted ? '실험적 조건부 매수 후보' : '시가 확인 대기');
    });
    it.each(['foreign symbol', 'malformed row'])('discards a %s while retaining its independently valid peer', defect => {
        const raw: any = { ...contextualCandidateDeskFixture(2), monitoring: candidateMonitoringFixture(2) };
        if (defect === 'foreign symbol') raw.monitoring.quotes[1].symbol = '999999';
        else raw.monitoring.quotes[1] = null;
        const desk = candidateDesk.validateCandidateDesk(raw, candidateEntryNow);
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateEntryNow)).toBe(true);
        render(<CandidateDeskPanel desk={desk} now={candidateEntryNow} />);
        const cards = screen.getAllByRole('article');
        expect(cards[0]).toHaveTextContent('실험적 조건부 매수 후보');
        expect(cards[0]).toHaveTextContent('현재 관측 60,500원');
        expect(cards[1]).toHaveTextContent('시가 확인 대기');
        expect(cards[1]).toHaveTextContent('연구 참고 비중 0.0%');
    });
    it('holds only the candidate whose quote identity is duplicated', () => {
        const raw = { ...contextualCandidateDeskFixture(2), monitoring: candidateMonitoringFixture(2) };
        raw.monitoring.quotes.push({ ...raw.monitoring.quotes[0] });
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateEntryNow)} now={candidateEntryNow} />);
        const cards = screen.getAllByRole('article');
        expect(cards[0]).toHaveTextContent('시가 확인 대기');
        expect(cards[0]).toHaveTextContent('연구 참고 비중 0.0%');
        expect(cards[1]).toHaveTextContent('실험적 조건부 매수 후보');
        expect(cards[1]).toHaveTextContent('현재 관측 60,500원');
    });
    it.each([
        ['missing monitor', (v: any) => { delete v.monitoring; }],
        ['unavailable monitor', (v: any) => { v.monitoring = { state: 'unavailable', checked_at: null, decision_id: null, quotes: [] }; }],
        ['foreign decision', (v: any) => { v.monitoring.decision_id = 'c'.repeat(64); }],
        ['stale monitor', (v: any) => { v.monitoring.state = 'stale'; }],
        ['failed monitor', (v: any) => { v.monitoring.state = 'failed'; }],
        ['unknown monitor state', (v: any) => { v.monitoring.state = 'buy'; }],
        ['future check', (v: any) => { v.monitoring.checked_at = '2026-10-23T00:05:01Z'; }],
        ['old check', (v: any) => { v.monitoring.checked_at = '2026-10-22T23:57:59Z'; }],
        ['future quote', (v: any) => { v.monitoring.quotes[0].quote_at = '2026-10-23T00:05:01Z'; }],
        ['old quote', (v: any) => { v.monitoring.quotes[0].quote_at = '2026-10-22T23:57:59Z'; }],
        ['future fetch', (v: any) => { v.monitoring.quotes[0].fetched_at = '2026-10-23T00:05:01Z'; }],
        ['fetch before quote', (v: any) => { v.monitoring.quotes[0].fetched_at = '2026-10-23T00:04:00Z'; }],
        ['old quote session', (v: any) => { v.monitoring.quotes[0].quote_at = '2026-10-22T00:04:30Z'; }],
        ['foreign quote source', (v: any) => { v.monitoring.quotes[0].source = 'NAVER'; }],
        ['missing opening', (v: any) => { delete v.monitoring.quotes[0].opening_price; }],
        ['stop touched opening', (v: any) => { v.monitoring.quotes[0].opening_price = 57000; }],
        ['above-ceiling quote', (v: any) => { v.monitoring.quotes[0].price = 62000; }],
        ['target reached quote', (v: any) => { v.monitoring.quotes[0].price = 66000; }],
        ['unknown quote identity', (v: any) => { v.monitoring.quotes[0].symbol = '035420'; }],
        ['duplicate quote identity', (v: any) => { v.monitoring.quotes.push({ ...v.monitoring.quotes[0] }); }],
    ])('waits for a usable opening instead of exposing an active proposal: %s', (_, change) => {
        const raw: any = { ...contextualCandidateDeskFixture(1), monitoring: candidateMonitoringFixture(1) }; change(raw);
        const desk = candidateDesk.validateCandidateDesk(raw, candidateEntryNow);
        expect(desk).toBeDefined();
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateEntryNow)).toBe(false);
        render(<CandidateDeskPanel desk={desk} now={candidateEntryNow} />);
        const card = screen.getByRole('article');
        expect(card).toHaveTextContent('시가 확인 대기');
        expect(card).toHaveTextContent('연구 참고 비중 0.0%');
        expect(card).not.toHaveTextContent('실험적 조건부 매수 후보');
    });
    it('retains a future conditional plan before entry day while the monitor is waiting', () => {
        const raw = { ...contextualCandidateDeskFixture(1), monitoring: { state: 'waiting', checked_at: '2026-10-22T12:00:00Z', decision_id: 'a'.repeat(64), quotes: [] } };
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.getByRole('article')).toHaveTextContent('실험적 조건부 매수 후보');
    });
    it('waits before the entry-day market opens', () => {
        const beforeOpen = Date.parse('2026-10-22T23:59:59Z');
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(contextualCandidateDeskFixture(1), beforeOpen)} now={beforeOpen} />);
        expect(screen.getByRole('article')).toHaveTextContent('시가 확인 대기');
        expect(screen.getByRole('article')).not.toHaveTextContent('실험적 조건부 매수 후보');
    });
    it('expires mounted quote authorization after seven minutes without a network read', async () => {
        vi.mocked(Date.now).mockRestore(); vi.useFakeTimers(); vi.setSystemTime(new Date(candidateEntryNow));
        api.fetchAuthAPI.mockResolvedValue({ ...candidateStatusFixture(), candidate_desk: { ...contextualCandidateDeskFixture(1), monitoring: candidateMonitoringFixture(1) } });
        render(<AlphaLabPanel desk />); await act(async () => {});
        expect(screen.getByRole('article')).toHaveTextContent('실험적 조건부 매수 후보');
        await act(async () => { await vi.advanceTimersByTimeAsync(420001); });
        expect(screen.getByRole('article')).toHaveTextContent('시가 확인 대기');
        expect(screen.getByRole('article')).not.toHaveTextContent('실험적 조건부 매수 후보');
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(1);
    });
});

describe('experimental contextual candidate boundary', () => {
    it('accepts causally cut local evidence while preserving the negative v3 comparison', () => {
        const raw = contextualCandidateDeskFixture(); const original = structuredClone(raw);
        const desk = candidateDesk.validateCandidateDesk(raw, candidateDeskNow);
        expect(desk?.candidates).toHaveLength(2);
        expect(desk?.evidence.confirmation.mean_net_return).toBe(-.025);
        expect(desk?.candidates[0].model_evidence?.expected_net_return).toBe(.012);
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateDeskNow)).toBe(true);
        expect(raw).toEqual(original);
    });
    it('keeps negative global economics disqualifying for the original v3 policy', () => {
        const raw = contextualCandidateDeskFixture(); raw.policy_version = 'cross-sectional-candidates-v3';
        expect(candidateDesk.validateCandidateDesk(raw, candidateDeskNow)).toBeUndefined();
    });
    it.each([
        ['missing model', (v: any) => { delete v.model; }],
        ['unknown model', (v: any) => { v.model.name = 'untested-v2'; }],
        ['nonexperimental model', (v: any) => { v.model.status = 'validated'; }],
        ['false holdout claim', (v: any) => { v.model.comparison_interpretation = 'v4_holdout'; }],
        ['claimed forward success', (v: any) => { v.model.validation = 'passed'; }],
        ['same-day training cutoff', (v: any) => { v.model.training_end = v.latest_session; v.candidates.forEach((row: any) => { row.model_evidence.training_end = v.latest_session; }); }],
        ['foreign local cutoff', (v: any) => { v.candidates[0].model_evidence.training_end = '2026-10-07'; }],
        ['missing local evidence', (v: any) => { delete v.candidates[0].model_evidence; }],
        ['small local sample', (v: any) => { Object.assign(v.candidates[0].model_evidence, { samples: 29, wins: 10, win_rate: 10 / 29 }); }],
        ['few market blocks', (v: any) => { v.candidates[0].model_evidence.block_count = 4; }],
        ['few source symbols', (v: any) => { v.candidates[0].model_evidence.unique_symbols = 4; }],
        ['self-neighbor contamination', (v: any) => { v.candidates[0].model_evidence.neighbors_exclude_target = false; }],
        ['negative local average', (v: any) => { v.candidates[0].model_evidence.mean_net_return = -.001; }],
        ['negative local stress', (v: any) => { v.candidates[0].model_evidence.stress_mean_net_return = -.001; }],
        ['nonpositive expected return', (v: any) => { v.candidates[0].model_evidence.expected_net_return = 0; }],
        ['nonpositive stressed expectation', (v: any) => { v.candidates[0].model_evidence.expected_stress_net_return = 0; }],
        ['nonfinite expectation', (v: any) => { v.candidates[0].model_evidence.expected_net_return = Infinity; }],
        ['inconsistent local wins', (v: any) => { v.candidates[0].model_evidence.win_rate = .99; }],
        ['more than one-percent weight', (v: any) => { v.candidates[0].risk.reference_weight = .0101; }],
        ['local approved exposure', (v: any) => { v.candidates[0].risk.approved_exposure = .01; }],
    ])('suppresses unsupported v4 evidence: %s', (_, change) => {
        const raw = contextualCandidateDeskFixture(); change(raw);
        expect(candidateDesk.validateCandidateDesk(raw, candidateDeskNow)).toBeUndefined();
    });
    it('accepts a short-history held desk with no training cutoff and no proposals', () => {
        const raw: any = contextualCandidateDeskFixture(0); raw.state = 'held'; raw.model.training_end = null;
        const desk = candidateDesk.validateCandidateDesk(raw, candidateDeskNow);
        expect(desk?.candidates).toHaveLength(0);
        expect(candidateDesk.candidateDeskEntryAvailable(desk, candidateDeskNow)).toBe(false);
    });
    it('preserves v4 through the optional API boundary', () => {
        const status = validateAlphaLabStatus({ ...candidateStatusFixture(), candidate_desk: contextualCandidateDeskFixture(1) });
        expect(status.candidate_desk?.policy_version).toBe('contextual-candidates-v4');
        expect(status.candidate_desk_unavailable).toBeUndefined();
    });
});

describe('experimental contextual candidate cards', () => {
    it('translates contextual source facts and displays observed losing-majority frequencies honestly', () => {
        const raw = contextualCandidateDeskFixture(2);
        raw.candidates.forEach((row, index) => {
            Object.assign(row.model_evidence, { samples: 60, wins: index ? 29 : 26, win_rate: (index ? 29 : 26) / 60, block_count: index ? 32 : 30, unique_symbols: index ? 33 : 31 });
            row.reason_facts = ['Other-symbol context: 60 events, 30 calendar blocks.',
                'Experimental cost-stress expectation 1.25%; forward validation collecting.'];
        });
        raw.funnel.push({ id: 'training_events', label: 'Formation-only training events', count: 490 },
            { id: 'model_context', label: 'Other-symbol positive context qualified', count: 2 });
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        const cards = screen.getAllByRole('article');
        expect(cards).toHaveLength(2);
        expect(cards[0]).toHaveTextContent('관측 빈도 43.3%');
        expect(cards[1]).toHaveTextContent('관측 빈도 48.3%');
        expect(cards[0]).toHaveTextContent('다른 종목 유사 사례 60건 · 달력 블록 30개');
        expect(cards[0]).toHaveTextContent('실험 모델 비용 2배 추정 1.25% · 전향 검증 중');
        expect(cards[0]).not.toHaveTextContent(/Other-symbol|Experimental cost|forward validation|60\.0%/);
        expect(screen.getByLabelText('후보 선별 단계')).toHaveTextContent('학습 거래 사례490');
        expect(screen.getByLabelText('후보 선별 단계')).toHaveTextContent('유사 조건 통과2');
    });
    it('separates the experimental proposal, local history and model estimate from the negative control', () => {
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(contextualCandidateDeskFixture(1), candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.getByText('실험적 조건부 매수 후보 · 전향 검증 중')).toBeVisible();
        const card = screen.getByRole('article', { name: '1위 삼성전자 005930' });
        expect(card).toHaveTextContent('연구 참고 비중 1.0%');
        expect(card).toHaveTextContent('종목당 상한 1%');
        const local = within(card).getByRole('region', { name: '삼성전자 유사 사례 통계' });
        expect(local).toHaveTextContent('완료 50건 · 달력 블록 8개 · 종목 12개');
        expect(local).toHaveTextContent('유사 사례 순평균 2.50%');
        expect(local).toHaveTextContent('모델 추정 순수익 1.20%');
        expect(local).toHaveTextContent('비용 2배 추정 0.90%');
        expect(local).toHaveTextContent('미래 승률로 보정되지 않은 모델 추정값입니다.');
        expect(local).toHaveTextContent('학습 마감 2026-10-08 · 해당 종목 제외');
        fireEvent.click(screen.getByText('기존 정책 대조군 · 한계'));
        expect(screen.getByRole('heading', { name: 'v3 대조군 · 최근 126거래일' })).toBeVisible();
        expect(screen.getByText(/비용 차감 평균 -2.50% · 비용 2배 평균 -2.89%/)).toBeVisible();
        expect(screen.getByText('v3의 조건 없는 과거 대조군입니다. v4의 미사용 검증 구간이나 검증된 투자 우위를 뜻하지 않습니다.')).toBeVisible();
    });
    it.each(['held', 'running', 'failed'])('never displays a retained %s v4 proposal as available', state => {
        const raw = contextualCandidateDeskFixture(1); raw.state = state;
        render(<CandidateDeskPanel desk={candidateDesk.validateCandidateDesk(raw, candidateDeskNow)} now={candidateDeskNow} />);
        expect(screen.queryByText('실험적 조건부 매수 후보 · 전향 검증 중')).not.toBeInTheDocument();
        expect(screen.getByRole('article')).toHaveTextContent('신규 진입 불가');
    });
});
