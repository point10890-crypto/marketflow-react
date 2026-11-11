import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KongmingCatalystValidationPage from '@/pages/dashboard/aibain/KongmingCatalystValidationPage';
import { surgeTraceFixture } from './fixtures/surgeTraceFixture';

// This independent saved-output panel has its own transport and polling suite.
vi.mock('@/components/aibain/CatalystOutcomesPanel', () => ({ default: () => null }));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ token: 'fixture-token', user: { id: 7, role: 'admin' } }),
}));

const endpoint = '/api/admin/mirofish/kongming/catalyst-validation';
const candidatesEndpoint = '/api/admin/mirofish/kongming/article-candidates';
const route = '/dashboard/ai-bain/catalyst-validation';
const articleUrl = 'https://www.businesspost.co.kr/BP?command=article_view&num=123';
const filingUrl = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261106000123';
const checked = '2026-11-07T10:00:00+09:00';
const articleTitle = '<img src=x onerror=alert(1)> 계약 기사';
const baseStyle = { state: 'market_closed', technical_pass: false, qualified: false, eligible: false, currently_eligible: false, blockers: [] };
const status = {
    items: [{
        task_id: 'article-1', symbol: '005930', name: '검증 종목', article_title: articleTitle,
        article_url: articleUrl, article_published_at: '2026-11-06T15:00:00+09:00', first_seen_at: checked, checked_at: checked,
        primary: { status: 'verified_numeric_claims', checks: [{
            status: 'verified_numeric_claims', filing: { report_nm: '영업실적 공시' }, url: filingUrl,
            claims: [{ metric: '영업이익', article_amount_krw: '12300', official_amount_krw: 12300, verified: true }],
        }] },
        styles: { scalp: baseStyle, close: baseStyle, swing: { ...baseStyle, state: 'technical_checked', technical_pass: true,
            blockers: ['same_policy_performance_or_completed_run_missing'], quote: { observed_at: checked, received_at: checked } } },
    }],
    swing_watch: {
        source_as_of: '2026-11-06', population: 103, baseline_count: 2, common_watch_count: 1,
        baseline_rows: [{ symbol: '005930', name: '스윙 관찰 종목', common_pass: true, failed_common: [], missing_common: [] }],
        watch_rows: [{ symbol: '005930', name: '스윙 관찰 종목', setups: { contraction: {
            label: '수축 셋업', complete: false, failed: ['고점 조건'], missing: ['거래대금 자료'],
        } } }],
        common_funnel: [{ label: '유동성', count: 17 }],
    },
    live: { last_run_at: checked, last_change_at: checked, age_seconds: 12, stalled: false },
    operation: { state: 'ready', market_open: false, task_count: 3, price_probed: 0 },
    history_count: 12,
    current_eligible_count: 0,
    computed_at: checked,
};
const history = { items: [{ id: 'history-1', name: '이전 검증 종목', symbol: '000660', checked_at: checked,
    primary: { status: 'no_matching_filing' }, market_state: 'closed_or_unverified', buy_eligible: false }] };

const recentCandidate = {
    id: '123', title: '최근 후보 기사', url: articleUrl, published_at: checked, first_seen_at: checked,
    entities: [{ symbol: '005930', name: '삼성전자' }, { symbol: '000660', name: 'SK하이닉스' }],
    event: { type: 'contract', certainty: 'reported_unverified' }, freshness: 'recent',
};
const articleCandidates = {
    items: [
        recentCandidate,
        { ...recentCandidate, id: '124', title: '같은 종목의 또 다른 후보', url: 'https://www.businesspost.co.kr/unrelated' },
        { ...recentCandidate, id: '121', title: '이전 후보 기사', freshness: 'older_context',
            published_at: '2026-10-30T10:00:00+09:00', first_seen_at: '2026-10-30T10:05:00+09:00', provenance: 'kongming_archive' },
    ],
    candidate_article_count: 3,
    recent_candidate_article_count: 2,
    computed_at: checked,
    operation: { state: 'ready', last_poll_at: checked, latest_published_at: checked },
};

function network() {
    let data: unknown = status;
    let historyData: unknown = history;
    let statusError = 0;
    let historyError = 0;
    let dashboardPending: Promise<void> | undefined;
    let candidateData = articleCandidates;
    let candidateError = 0;
    const fetch = vi.fn(async (input: string, init?: RequestInit) => {
        const path = new URL(input, 'http://localhost').pathname;
        expect(init?.method ?? 'GET').toBe('GET');
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer fixture-token');
        if (![endpoint, `${endpoint}-history`].includes(path)) throw new Error(`Unexpected route: ${path}`);
        if (path === endpoint && dashboardPending) await dashboardPending;
        const errorCode = path === endpoint ? statusError : historyError;
        return new Response(JSON.stringify(errorCode ? { error: 'Fixture request failure' }
            : path === endpoint ? data : historyData), { status: errorCode || 200 });
    });
    const candidateFetch = vi.fn(async (_input: string, init?: RequestInit) => {
        expect(init?.method ?? 'GET').toBe('GET');
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer fixture-token');
        return new Response(JSON.stringify(candidateError ? { error: 'Fixture candidate failure' } : candidateData),
            { status: candidateError || 200 });
    });
    vi.stubGlobal('fetch', (input: string, init?: RequestInit) => {
        const path = new URL(input, 'http://localhost').pathname;
        if (path === '/api/admin/mirofish/kongming/surge-traces') return Promise.resolve(new Response(JSON.stringify({
            ...surgeTraceFixture(), status: 'waiting', items: [],
        })));
        if (path === '/api/admin/mirofish/kongming/article-evidence-reviews') return Promise.resolve(new Response(JSON.stringify({
            schema_version: 1, kind: 'article', status: 'waiting', last_run_at: null, items: [],
        })));
        return (path === candidatesEndpoint ? candidateFetch : fetch)(input, init);
    });
    return {
        fetch,
        candidateFetch,
        setCandidates: (value: typeof articleCandidates) => { candidateData = value; },
        setCandidateError: (status: number) => { candidateError = status; },
        setData: (value: unknown) => { data = value; },
        setHistory: (value: unknown) => { historyData = value; },
        setError: (status: number, history = status) => { statusError = status; historyError = history; },
        pauseDashboard() {
            let release!: () => void;
            dashboardPending = new Promise<void>(resolve => { release = resolve; });
            return () => { dashboardPending = undefined; release(); };
        },
    };
}

function renderKongming(initialEntry = route) {
    return render(<MemoryRouter initialEntries={[initialEntry]}><KongmingCatalystValidationPage /></MemoryRouter>);
}

function independentDashboard() {
    const base = status.items[0];
    const verified = {
        ...base, article_id: '123',
        primary: { ...base.primary, source: 'OpenDART', checked_at: checked, query_start: '2026-11-03', query_end: '2026-11-07' },
        price: { status: 'verified', source: 'kis', market: 'KRX', close: 70000,
            latest_close: 71400, change_pct: 2, reference_at: checked,
            observed_at: '2026-11-07T10:01:00+09:00', latest_observed_at: '2026-11-07T10:02:00+09:00',
            fetched_at: '2026-11-07T10:03:00+09:00', refresh_status: 'source_unavailable' },
    };
    return { ...status, source: 'marketflow', swing_watch: null, live: { ...status.live, worker_interval_seconds: 60 },
        operation: { ...status.operation, pending_count: 1, disclosure_checked: 2, price_checked: 1 },
        items: [verified, { ...base, task_id: 'article-2', article_id: '121', article_title: '이전 후보 기사 검증',
            price: { status: 'awaiting_session' } }] };
}

function eligibleDashboard() {
    const row = status.items[0];
    return {
        ...status,
        current_eligible_count: 1,
        items: [{ ...row, styles: { ...row.styles, swing: {
            ...row.styles.swing, currently_eligible: true, eligible: true,
            quote: { observed_at: checked, received_at: '2026-11-07T10:00:01+09:00' },
        } } }],
    };
}

beforeEach(() => {
    sessionStorage.setItem('auth_token', 'fixture-token');
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

describe('Independent Kongming article candidates', () => {
    it('displays article-level candidates, official publisher links and expandable older articles', async () => {
        network();
        renderKongming();
        const region = within(await screen.findByRole('region', { name: '검출된 후보 리스트 · 기사 재료' }));
        expect(await region.findByRole('heading', { name: '최근 72시간 발행 · 2건' })).toBeInTheDocument();
        expect(region.getByRole('link', { name: recentCandidate.title })).toHaveAttribute('href', articleUrl);
        expect(region.getByText('같은 종목의 또 다른 후보').closest('a')).toBeNull();
        expect(region.getAllByText('000660').length).toBeGreaterThan(0);
        const archive = region.getByText('이전 기사 · 1건').closest('details')!;
        expect(archive).not.toHaveAttribute('open');
        fireEvent.click(region.getByText('이전 기사 · 1건'));
        expect(region.getByText('이전 후보 기사')).toBeVisible();
        expect(region.getByText('원본 최초 수신')).toBeVisible();
    });

    it('refreshes every 30 seconds, retains good results on failure and clears them on access denial', async () => {
        vi.useFakeTimers();
        const gateway = network();
        await act(async () => { renderKongming(); });
        const region = within(screen.getByRole('region', { name: '검출된 후보 리스트 · 기사 재료' }));
        expect(region.getByText(recentCandidate.title)).toBeInTheDocument();
        gateway.setCandidateError(503);
        await act(async () => { await vi.advanceTimersByTimeAsync(29_999); });
        expect(gateway.candidateFetch).toHaveBeenCalledTimes(1);
        await act(async () => { await vi.advanceTimersByTimeAsync(1); });
        expect(region.getByRole('alert')).toHaveTextContent('이전 목록 표시 중');
        expect(region.getByText(recentCandidate.title)).toBeInTheDocument();
        expect(screen.getByText(articleTitle)).toBeInTheDocument();

        const refreshedTitle = '자동으로 반영된 기사';
        gateway.setCandidateError(0);
        gateway.setCandidates({ ...articleCandidates, items: [{ ...recentCandidate, title: refreshedTitle }] });
        await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
        expect(region.getByText(refreshedTitle)).toBeInTheDocument();
        expect(region.queryByRole('alert')).toBeNull();

        gateway.setCandidateError(403);
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(region.getByRole('alert')).toHaveTextContent('접근 권한');
        expect(region.queryByText(refreshedTitle)).toBeNull();
        expect(gateway.candidateFetch).toHaveBeenCalledTimes(4);
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
    });

    it('shows separate article verification for the same ticker and opens the selected article with both reads scoped', async () => {
        const gateway = network();
        gateway.setData(independentDashboard());
        renderKongming();
        const region = within(screen.getByRole('region', { name: '새 종목과 재료 검증 대시보드' }));
        expect(await region.findByRole('heading', { name: '기사 재료 검증 2건' })).toBeInTheDocument();
        expect(region.getByRole('link', { name: articleTitle })).toBeInTheDocument();
        expect(region.getByRole('link', { name: '이전 후보 기사 검증' })).toBeInTheDocument();
        expect(region.getByText(/기준 분봉 종가 70000원.*비교 분봉 종가 71400원.*변동 \+2.00%/)).toBeInTheDocument();
        expect(region.getByText(/한국투자증권 KIS · KRX/)).toBeInTheDocument();
        expect(region.getByText('공시 검색 범위 2026-11-03 ~ 2026-11-07')).toBeInTheDocument();
        expect(region.getByText('시세 갱신 · 시세 자료 수신 실패 · 이전 근거 표시 중')).toBeInTheDocument();
        expect(region.getByText(/공시 처리 2건 · 시세 처리 1건 · 첫 확인 대기 1건/)).toBeInTheDocument();
        expect(region.getByText(/출처 MarketFlow.*서버 60초마다 자동 검증/)).toBeInTheDocument();
        expect(region.queryByText(/텔레그램|현재 매수 적격/)).toBeNull();

        const candidateLink = await screen.findByRole('link', { name: `${recentCandidate.title} 공시·시세 검증 보기` });
        expect(candidateLink).toHaveAttribute('href', `${route}?article_id=123#catalyst-validation`);
        fireEvent.click(candidateLink);
        const selected = within(screen.getByRole('region', { name: '새 종목과 재료 검증 대시보드' }));
        expect(await selected.findByRole('heading', { name: '기사 재료 검증 1건' })).toBeInTheDocument();
        expect(selected.getByRole('link', { name: articleTitle })).toBeInTheDocument();
        expect(selected.queryByText('이전 후보 기사 검증')).toBeNull();
        expect(gateway.fetch.mock.calls.slice(-2).map(([input]) => new URL(input, 'http://localhost').search)).toEqual([
            '?article_id=123', '?article_id=123',
        ]);
    });

    it('loads the selected earlier article and its verification history directly from the URL', async () => {
        const gateway = network();
        gateway.setData(independentDashboard());
        gateway.setHistory({ items: [
            { id: 'prev', article_id: '121', article_title: '이전 후보 확인 이력', price: { status: 'awaiting_session' } },
            { id: 'other', article_id: '123', article_title: '다른 기사 확인 이력' },
        ] });
        renderKongming(`${route}?article_id=121#catalyst-validation`);
        const region = within(screen.getByRole('region', { name: '새 종목과 재료 검증 대시보드' }));
        expect(await region.findByRole('link', { name: '이전 후보 기사 검증' })).toBeInTheDocument();
        expect(region.getAllByText(/정규장 대기/)).toHaveLength(2);
        expect(region.getByText(/이전 후보 확인 이력/)).toBeInTheDocument();
        expect(region.queryByText(/다른 기사 확인 이력/)).toBeNull();
        expect(region.queryByRole('link', { name: articleTitle })).toBeNull();
    });
});
afterEach(() => {
    cleanup();
    sessionStorage.clear();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe('Kongming catalyst validation', () => {
    it('renders saved swing, article verification and history fields with safe official links', async () => {
        const gateway = network();
        renderKongming();
        const headline = await screen.findByRole('heading', { name: '새 스윙 검토 후보 · 1종목' });
        expect(headline).toBeInTheDocument();
        const region = screen.getByRole('region', { name: '새 종목과 재료 검증 대시보드' });
        expect(within(region).getByText('1차 수식 통과 전체 2종목 명단')).toBeInTheDocument();
        expect(within(region).getByText(/유동성 → 17종목/)).toBeInTheDocument();
        expect(within(region).getByText(/고점 조건/)).toBeInTheDocument();
        expect(within(region).getByText(/현재 매수 적격 0건/)).toBeInTheDocument();
        expect(within(region).getByText(/자동검증 작동 중.*12초 전/)).toBeInTheDocument();
        expect(within(region).getByRole('link', { name: articleTitle })).toHaveAttribute('href', articleUrl);
        expect(within(region).getByText('영업실적 공시').closest('a')).toHaveAttribute('href', filingUrl);
        expect(within(region).getByText(/영업이익 · 기사 12300원 \/ 공식 12300원/)).toBeInTheDocument();
        expect(within(region).getByText('이전 검증 종목')).toBeInTheDocument();
        expect(region.querySelector('img')).toBeNull();
        expect(gateway.fetch).toHaveBeenCalledTimes(2);
    });

    it('keeps a legacy missing live clock unknown and makes unapproved URLs inert', async () => {
        const gateway = network();
        const { live: _unused, ...legacy } = status;
        gateway.setData({ ...legacy, items: [{ ...status.items[0], article_url: 'https://www.businesspost.co.kr.evil.test/BP' }] });
        renderKongming();
        expect(await screen.findByText(/자동검증 상태 확인할 수 없음/)).toBeInTheDocument();
        expect(screen.queryByText(/자동검증 작동 중/)).toBeNull();
        expect(screen.getByText(articleTitle).closest('a')).toBeNull();
    });

    it('renders an unknown status as text even when it matches a prototype property', async () => {
        const gateway = network();
        gateway.setData({ ...status, items: [{ ...status.items[0], primary: { ...status.items[0].primary, status: '__proto__' } }] });
        renderKongming();
        expect(await screen.findByText('__proto__')).toBeInTheDocument();
    });

    it('keeps expanded evidence through a transient failure and same-content recovery', async () => {
        const gateway = network();
        renderKongming();
        const details = (await screen.findByText('공식 근거·미충족·시각')).closest('details')!;
        details.open = true;
        gateway.setError(502);
        fireEvent.click(screen.getByRole('button', { name: '저장 상태 갱신' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('이전 결과 보존');
        expect(details).toHaveAttribute('open');
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
        expect(screen.queryByText(/자동검증 작동 중/)).toBeNull();
        gateway.setError(0);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: '저장 상태 갱신' })); });
        expect(screen.queryByRole('alert')).toBeNull();
        expect(details).toHaveAttribute('open');
    });

    it.each([401, 403])('stops 15-second polling and clears retained data on HTTP %s', async (error) => {
        vi.useFakeTimers();
        const gateway = network();
        await act(async () => { renderKongming(); });
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
        gateway.setError(error);
        await act(async () => { await vi.advanceTimersByTimeAsync(14_999); });
        expect(gateway.fetch).toHaveBeenCalledTimes(2);
        await act(async () => { await vi.advanceTimersByTimeAsync(1); });
        expect(screen.getByRole('alert')).toHaveTextContent('접근 권한');
        expect(screen.queryByText(articleTitle)).toBeNull();
        const stoppedAt = gateway.fetch.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(gateway.fetch).toHaveBeenCalledTimes(stoppedAt);
    });

    it('gives the history authorization denial priority over a dashboard transport failure', async () => {
        const gateway = network();
        renderKongming();
        await screen.findByText(articleTitle);
        gateway.setError(502, 403);
        fireEvent.click(screen.getByRole('button', { name: '저장 상태 갱신' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('접근 권한');
        expect(screen.queryByText(articleTitle)).toBeNull();
    });

    it('preserves evidence if optional style and setup objects are null', async () => {
        const gateway = network();
        const row = status.items[0];
        const watch = status.swing_watch;
        gateway.setData({ ...status,
            items: [
                { ...row, styles: { ...row.styles, scalp: null } },
                { ...row, task_id: 'article-2', symbol: '000660', article_title: '다른 검증 기사' },
            ],
            swing_watch: { ...watch, watch_rows: [{
                ...watch.watch_rows[0], setups: { ...watch.watch_rows[0].setups, breakout: null },
            }] },
        });
        renderKongming();
        expect(await screen.findByText(articleTitle)).toBeInTheDocument();
        expect(screen.getByText(/고점 조건/)).toBeInTheDocument();
    });

    it('removes current eligibility and its count when either quote clock expires between polls', async () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-11-07T10:00:59+09:00'));
        const gateway = network();
        gateway.setData(eligibleDashboard());
        await act(async () => { renderKongming(); });
        expect(screen.getByRole('heading', { name: /현재 매수 적격 1건/ })).toBeInTheDocument();
        expect(screen.getByText('· 현재 매수 적격')).toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
        expect(gateway.fetch).toHaveBeenCalledTimes(2);
        expect(screen.getByRole('heading', { name: /현재 매수 적격 0건/ })).toBeInTheDocument();
        expect(screen.queryByText('· 현재 매수 적격')).toBeNull();
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
    });

    it('keeps the still-current article visible when a newer article for its symbol expires', async () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-11-07T10:00:59+09:00'));
        const gateway = network();
        const dashboard = eligibleDashboard();
        const newer = dashboard.items[0];
        const olderTitle = '같은 종목의 먼저 게시된 검증 기사';
        const older = {
            ...newer, task_id: 'article-2', article_title: olderTitle, article_published_at: '2026-11-06T14:00:00+09:00',
            styles: { ...newer.styles, swing: {
                ...newer.styles.swing,
                quote: { observed_at: '2026-11-07T10:00:05+09:00', received_at: '2026-11-07T10:00:06+09:00' },
            } },
        };
        gateway.setData({ ...dashboard, items: [newer, older], current_eligible_count: 2 });
        await act(async () => { renderKongming(); });
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
        expect(screen.queryByText(olderTitle)).toBeNull();

        await act(async () => { await vi.advanceTimersByTimeAsync(1001); });
        expect(screen.getByRole('heading', { name: /현재 매수 적격 1건/ })).toBeInTheDocument();
        expect(screen.getByText('· 현재 매수 적격')).toBeInTheDocument();
        expect(screen.getByText(olderTitle)).toBeInTheDocument();
        expect(screen.queryByText(articleTitle)).toBeNull();

        const details = screen.getByText('공식 근거·미충족·시각').closest('details')!;
        details.open = true;
        gateway.setError(502);
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: '저장 상태 갱신' })); });
        expect(screen.getByText(olderTitle)).toBeInTheDocument();
        expect(screen.queryByText('· 현재 매수 적격')).toBeNull();
        expect(details).toBeInTheDocument();
        expect(details).toHaveAttribute('open');
    });

    it.each([
        { quoteExpiry: 10, validUntil: '2026-11-07T10:00:30+09:00', deadline: 10_000 },
        { quoteExpiry: 60, validUntil: '2026-11-07T10:00:08+09:00', deadline: 8_000 },
    ])('uses the earliest source quote or plan deadline', async ({ quoteExpiry, validUntil, deadline }) => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date(checked).getTime() + deadline - 500);
        const gateway = network();
        const dashboard = eligibleDashboard();
        const row = dashboard.items[0];
        gateway.setData({ ...dashboard, quote_expiry_seconds: quoteExpiry, items: [{
            ...row, styles: { ...row.styles, swing: {
                ...row.styles.swing, quote: { ...row.styles.swing.quote, plan: { valid_until: validUntil } },
            } },
        }] });
        await act(async () => { renderKongming(); });
        expect(screen.getByText('· 현재 매수 적격')).toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(501); });
        expect(screen.queryByText('· 현재 매수 적격')).toBeNull();
        expect(screen.getByRole('heading', { name: /현재 매수 적격 0건/ })).toBeInTheDocument();
    });

    it.each([
        { quoteExpiry: null, observed: checked, current: true },
        { quoteExpiry: 60, observed: 'invalid-clock', current: true },
        { quoteExpiry: 60, observed: checked, current: false },
    ])('cannot show current eligibility without a valid window and positive source verdict', async ({ quoteExpiry, observed, current }) => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-11-07T10:00:10+09:00'));
        const gateway = network();
        const dashboard = eligibleDashboard();
        const row = dashboard.items[0];
        gateway.setData({ ...dashboard, quote_expiry_seconds: quoteExpiry, items: [{
            ...row, styles: { ...row.styles, swing: {
                ...row.styles.swing, currently_eligible: current, quote: { ...row.styles.swing.quote, observed_at: observed },
            } },
        }] });
        await act(async () => { renderKongming(); });
        expect(screen.queryByText('· 현재 매수 적격')).toBeNull();
        expect(screen.getByRole('heading', { name: /현재 매수 적격 0건/ })).toBeInTheDocument();
    });

    it('waits for a foreground response before restoring the current eligibility label', async () => {
        vi.useFakeTimers();
        vi.setSystemTime(new Date('2026-11-07T10:00:10+09:00'));
        const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
        const gateway = network();
        gateway.setData(eligibleDashboard());
        await act(async () => { renderKongming(); });
        expect(screen.getByText('· 현재 매수 적격')).toBeInTheDocument();
        const release = gateway.pauseDashboard();
        visibility.mockReturnValue('hidden');
        fireEvent(document, new Event('visibilitychange'));
        visibility.mockReturnValue('visible');
        fireEvent(document, new Event('visibilitychange'));
        expect(screen.getByRole('heading', { name: /현재 매수 적격 미확인/ })).toBeInTheDocument();
        expect(screen.queryByText('· 현재 매수 적격')).toBeNull();
        expect(screen.getByText(articleTitle)).toBeInTheDocument();
        await act(async () => { release(); });
        expect(screen.getByText('· 현재 매수 적격')).toBeInTheDocument();
    });

    it('clears both snapshots on access denial even when the other request is pending', async () => {
        const gateway = network();
        renderKongming();
        await screen.findByText(articleTitle);
        const release = gateway.pauseDashboard();
        gateway.setError(0, 403);
        fireEvent.click(screen.getByRole('button', { name: '저장 상태 갱신' }));
        try {
            expect(await screen.findByRole('alert')).toHaveTextContent('접근 권한');
            expect(screen.queryByText(articleTitle)).toBeNull();
            expect(screen.queryByText('이전 검증 종목')).toBeNull();
        } finally {
            await act(async () => { release(); });
        }
        expect(screen.queryByText(articleTitle)).toBeNull();
    });
});
