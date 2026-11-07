import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KongmingArticleCandidatesPanel from '@/pages/dashboard/aibain/KongmingArticleCandidatesPanel';
import AlphaLabPanel from '@/components/aibain/AlphaLabPanel';
import { evolutionStatusFixture } from './fixtures/evolutionFixture';
import { evidenceSourceUrl, validateEvidenceReviews } from '@/lib/evidenceReview';

const articleEndpoint = '/api/admin/mirofish/kongming/article-candidates';
const reviewEndpoint = '/api/admin/mirofish/kongming/article-evidence-reviews';
const generated = '2026-11-08T01:10:00Z';
const cutoff = '2026-11-08T01:00:00Z';
const url = 'https://www.businesspost.co.kr/BP?command=article_view&num=123';
export function reviewFixture(kind: 'article' | 'candidate' = 'article') {
    return {
        schema_version: 1, kind, status: 'ready', last_run_at: generated, empty_reason: null,
        items: [{ id: 'review-123', input_fingerprint: 'c'.repeat(64), source_input_fingerprint: kind === 'candidate' ? 'b'.repeat(64) : null,
            decision_id: kind === 'candidate' ? 'a'.repeat(64) : null, article_id: kind === 'article' ? '123' : null,
            candidate_basis: kind === 'candidate' ? 'research_watchlist' : null, original_status: kind === 'candidate' ? 'held' : null,
            generated_at: generated, source_cutoff_at: cutoff, source_origin_at: cutoff, status: 'SUCCESS_PRIMARY', provider: 'anthropic', model: 'claude-haiku-4-5',
            fallback_reason: null, freshness: 'current', review_scope: 'current_evidence_not_original_decision',
            rows: [{ symbol: '005930', name: '삼성전자', market: 'KR',
                strengths: [{ text: '계약 공시와 보도의 대상 기업이 일치합니다.', claim_status: 'inference', evidence_ids: ['article:123'], quotes: [{ evidence_id: 'article:123', quote: '계약을 체결했다' }] }],
                risks: [{ text: '매출 반영 시점은 추가 확인이 필요합니다.', claim_status: 'missing', evidence_ids: ['article:123'], quotes: [] }],
                what_to_watch: [{ text: '후속 공시와 거래량을 함께 확인하세요.', claim_status: 'inference', evidence_ids: ['article:123'], quotes: [] }] }],
            sources: [{ evidence_id: 'article:123', title: '계약 보도 원문', url, published_at: cutoff, fetched_at: cutoff,
                source: 'BusinessPost', verification_status: 'reported_unverified' }] }],
    };
}
function articles(id = '123') {
    return { items: [{ id, title: '후보 기사', url, published_at: cutoff, first_seen_at: cutoff,
        entities: [{ symbol: '005930', name: '삼성전자' }], event: { type: 'contract', certainty: 'reported_unverified' }, freshness: 'recent' }],
        candidate_article_count: 1, recent_candidate_article_count: 1, operation: { state: 'ready' } };
}
function network() {
    let payload = reviewFixture(); let status = 200; let articleId = '123'; let reads = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), 'http://localhost').pathname;
        expect(init?.method ?? 'GET').toBe('GET');
        expect(new Headers(init?.headers).get('Authorization')).toBe('Bearer member-token');
        if (path === articleEndpoint) return new Response(JSON.stringify(articles(articleId)));
        if (path !== reviewEndpoint) throw new Error(`Unexpected route ${path}`);
        reads++;
        return new Response(JSON.stringify(status === 200 ? payload : { error: 'not displayed' }), { status });
    }));
    return { setStatus: (value: number) => { status = value; }, setPayload: (value: typeof payload) => { payload = value; },
        setArticleId: (value: string) => { articleId = value; }, reads: () => reads };
}
function renderArticles() { return render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><KongmingArticleCandidatesPanel /></MemoryRouter>); }
async function visibleRefresh() { await act(async () => { document.dispatchEvent(new Event('visibilitychange')); }); }
beforeEach(() => {
    sessionStorage.setItem('auth_token', 'member-token');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
});
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe('saved article AI evidence', () => {
    it('accepts the collector alphanumeric article symbol contract', () => {
        const review = reviewFixture(); review.items[0].rows[0].symbol = '12345A';
        expect(validateEvidenceReviews(review, 'article').items[0].rows[0].symbol).toBe('12345A');
        const candidate = reviewFixture('candidate'); candidate.items[0].rows[0].symbol = '12345A';
        expect(() => validateEvidenceReviews(candidate, 'candidate')).toThrow();
    });
    it('renders saved findings, actual provider, both clocks and source links without changing article facts', async () => {
        network(); renderArticles();
        const panel = within(await screen.findByRole('region', { name: '재료 AI 분석' }));
        expect(await panel.findByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
        expect(panel.getByText(/Anthropic/)).toHaveTextContent('claude-haiku-4-5');
        expect(panel.getByText(/분석 작성/).querySelector('time')).toHaveAttribute('dateTime', generated);
        expect(panel.getByText(/자료 기준/).querySelector('time')).toHaveAttribute('dateTime', cutoff);
        expect(panel.getByRole('link', { name: '계약 보도 원문' })).toHaveAttribute('href', url);
        expect(screen.getByRole('link', { name: '후보 기사' })).toHaveAttribute('href', url);
    });
    it('retains saved findings with their original clock during a read outage', async () => {
        const gateway = network(); renderArticles(); await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.');
        gateway.setStatus(503); await visibleRefresh();
        const panel = within(screen.getByRole('region', { name: '재료 AI 분석' }));
        expect(await panel.findByText(/조회 지연.*이전 저장 결과/)).toBeVisible();
        expect(panel.getByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
        expect(panel.getByText(/분석 작성/).querySelector('time')).toHaveAttribute('dateTime', generated);
    });
    it.each([401, 403])('clears saved findings and stops polling after access status %s', async (status) => {
        vi.useFakeTimers(); const gateway = network(); renderArticles(); await act(async () => {});
        expect(screen.getByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
        gateway.setStatus(status); await visibleRefresh();
        expect(screen.getByText(/AI 분석의 접근 권한/)).toBeVisible();
        expect(screen.queryByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeNull();
        const calls = gateway.reads(); await visibleRefresh();
        await act(async () => { await vi.advanceTimersByTimeAsync(600_000); });
        expect(gateway.reads()).toBe(calls);
    });
    it('hides a review immediately when its article leaves the current source list', async () => {
        const gateway = network(); renderArticles(); await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.');
        gateway.setArticleId('124'); fireEvent.click(screen.getByRole('button', { name: '기사 후보 갱신' }));
        await screen.findByRole('link', { name: '후보 기사 공시·시세 검증 보기' });
        await act(async () => {});
        expect(screen.queryByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeNull();
    });
    it('identifies fallback and stale evidence and never links a lookalike domain', async () => {
        const gateway = network(); const payload = reviewFixture(); payload.status = 'degraded';
        Object.assign(payload.items[0], { status: 'SUCCESS_FALLBACK', provider: 'deepseek', model: 'deepseek-chat',
            fallback_reason: 'insufficient_credit', freshness: 'stale' });
        payload.items[0].sources[0].url = 'https://www.businesspost.co.kr.evil.test/BP?command=article_view&num=123';
        gateway.setPayload(payload); renderArticles();
        const panel = within(await screen.findByRole('region', { name: '재료 AI 분석' }));
        expect(await panel.findByText(/대체 분석.*DeepSeek/)).toBeVisible();
        expect(panel.getByText(/크레딧 부족/)).toBeVisible();
        expect(panel.getByText(/이전 자료 기준/)).toBeVisible();
        expect(panel.queryByRole('link', { name: '계약 보도 원문' })).toBeNull();
    });
    it('describes a current successful fallback without claiming a delayed analysis', async () => {
        const gateway = network(); const payload = reviewFixture(); payload.status = 'degraded';
        Object.assign(payload.items[0], { status: 'SUCCESS_FALLBACK', provider: 'deepseek', model: 'deepseek-chat', fallback_reason: 'insufficient_balance' });
        gateway.setPayload(payload); renderArticles();
        expect(await screen.findByText(/대체 분석.*DeepSeek/)).toBeVisible();
        expect(screen.getByText(/기본 모델 크레딧 부족/)).toBeVisible();
        expect(screen.queryByText(/분석 갱신 지연/)).toBeNull();
    });
    it('finishes the initial saved read through a StrictMode effect restart', async () => {
        network(); render(<StrictMode><MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><KongmingArticleCandidatesPanel /></MemoryRouter></StrictMode>);
        expect(await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
    });
    it.each([['inference', 'AI 해석'], ['reported', '원문 보고'], ['verified', '공시 수치 대조'], ['missing', '미확인']])('labels a %s finding as %s', async (status, label) => {
        const gateway = network(); const payload = reviewFixture();
        payload.items[0].rows[0].strengths[0].claim_status = status; gateway.setPayload(payload); renderArticles();
        const finding = (await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.')).closest('li')!;
        expect(within(finding).getByText(label)).toBeVisible();
    });
    it('shows the omitted finding count while preserving the validated findings', async () => {
        const gateway = network(); const payload = reviewFixture(); Object.assign(payload.items[0], { omitted_findings: 2 });
        gateway.setPayload(payload); renderArticles();
        expect(await screen.findByText('근거 검증을 통과하지 못한 해석 2개 제외')).toBeVisible();
        expect(screen.getByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
    });
    it.each([undefined, 0])('does not show omitted interpretations when count is %s', async count => {
        const gateway = network(); const payload = reviewFixture(); Object.assign(payload.items[0], { omitted_findings: count });
        gateway.setPayload(payload); renderArticles();
        expect(await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
        expect(screen.queryByText(/근거 검증을 통과하지 못한 해석/)).toBeNull();
    });
});

describe('evidence provenance boundary', () => {
    it.each([-1, 1.5, 25, null, '2', NaN])('rejects invalid omitted finding count %s', count => {
        const review = reviewFixture(); Object.assign(review.items[0], { omitted_findings: count });
        expect(() => validateEvidenceReviews(review, 'article')).toThrow();
    });
    it('accepts the maximum omitted finding count', () => {
        const review = reviewFixture(); Object.assign(review.items[0], { omitted_findings: 24 });
        expect(() => validateEvidenceReviews(review, 'article')).not.toThrow();
    });
    it('rejects findings whose report or interpretation status is absent', () => {
        const review = reviewFixture(); Object.assign(review.items[0].rows[0].strengths[0], { claim_status: undefined });
        expect(() => validateEvidenceReviews(review, 'article')).toThrow();
    });
    it('rejects a finding pointing to evidence absent from the saved sources', () => {
        const review = reviewFixture(); review.items[0].rows[0].strengths[0].evidence_ids = ['fabricated'];
        expect(() => validateEvidenceReviews(review, 'article')).toThrow();
    });
    it('rejects a quote assigned to a different finding source', () => {
        const review = reviewFixture(); review.items[0].rows[0].strengths[0].quotes[0].evidence_id = 'foreign';
        expect(() => validateEvidenceReviews(review, 'article')).toThrow();
    });
    it('rejects a cutoff newer than the claimed generated time', () => {
        const review = reviewFixture(); review.items[0].source_cutoff_at = '2026-11-09T01:00:00Z';
        expect(() => validateEvidenceReviews(review, 'article')).toThrow();
    });
    it.each(['http://www.businesspost.co.kr/BP?command=article_view&num=123',
        'https://www.businesspost.co.kr@evil.test/BP?command=article_view&num=123',
        'javascript:alert(1)', 'https://dart.fss.or.kr/redirect?url=https://evil.test'])('does not activate unsafe source URL %s', url => {
        expect(evidenceSourceUrl(url)).toBeNull();
    });
    it('allows an exact official disclosure URL', () => {
        const url = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261108000123';
        expect(evidenceSourceUrl(url)).toBe(url);
    });
});

describe('candidate comparison binding', () => {
    function candidateNetwork() {
        let snapshot = evolutionStatusFixture(undefined);
        let review = reviewFixture('candidate');
        let status = 200;
        const requests: string[] = [];
        vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
            const path = new URL(String(input), 'http://localhost').pathname;
            expect(init?.method ?? 'GET').toBe('GET');
            requests.push(new Headers(init?.headers).get('Authorization') ?? '');
            if (path === '/api/admin/mirofish/alpha-lab') return new Response(JSON.stringify(snapshot));
            if (path === '/api/admin/mirofish/alpha-lab/candidate-review') return new Response(JSON.stringify(status === 200 ? review : {}), { status });
            throw new Error(`Unexpected route ${path}`);
        }));
        return { setSnapshot: (value: typeof snapshot) => { snapshot = value; },
            setReview: (value: typeof review) => { review = value; }, setStatus: (value: number) => { status = value; }, requests };
    }
    it('labels research candidates separately and preserves the held quantitative board', async () => {
        candidateNetwork(); render(<AlphaLabPanel token="member-token" desk />);
        const panel = within(await screen.findByRole('region', { name: '상위 후보 근거 비교' }));
        expect(await panel.findByText('연구 후보 1종목 비교')).toBeVisible();
        expect(panel.getByText(/기존 판단 보류 상태와 가격·비중을 유지/)).toBeVisible();
        expect(panel.getByText(/선정 기준/).querySelector('time')).toHaveAttribute('dateTime', cutoff);
        expect(panel.getByText('1. 삼성전자')).toHaveTextContent('005930');
        expect(screen.queryByRole('button', { name: '매수 후보 검출' })).toBeNull();
    });
    it.each(['decision_id', 'input_fingerprint'] as const)('hides old findings when the current board %s changes', async key => {
        const gateway = candidateNetwork(); render(<AlphaLabPanel token="member-token" desk />);
        await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.');
        const next = evolutionStatusFixture(undefined); next.opportunity_engine[key] = 'd'.repeat(64);
        if (key === 'input_fingerprint') next.report.input_fingerprint = 'd'.repeat(64);
        gateway.setSnapshot(next); fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        await act(async () => {});
        expect(screen.queryByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeNull();
        expect(screen.getByText(/현재 자료에 연결된 AI 분석/)).toBeVisible();
    });
    it('does not retain a saved review across account change and denied read', async () => {
        const gateway = candidateNetwork(); const ui = render(<AlphaLabPanel token="member-token" desk />);
        await screen.findByText('계약 공시와 보도의 대상 기업이 일치합니다.');
        gateway.setStatus(403); ui.rerender(<AlphaLabPanel token="other-member" desk />);
        expect(screen.queryByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeNull();
        expect(await screen.findByText(/AI 분석의 접근 권한/)).toBeVisible();
        expect(gateway.requests).toContain('Bearer other-member');
    });
    it('shows deterministic evidence as unverified during a complete model outage', async () => {
        const gateway = candidateNetwork(); const review = reviewFixture('candidate');
        Object.assign(review.items[0], { status: 'UNVERIFIED', provider: null, model: null, fallback_reason: 'providers_unavailable' });
        review.status = 'unavailable'; gateway.setReview(review);
        render(<AlphaLabPanel token="member-token" desk />);
        expect(await screen.findByText('AI 확인 미완료 · 저장 근거')).toBeVisible();
        expect(screen.queryByText(/AI 분석 · Anthropic/)).toBeNull();
        expect(screen.getByText('계약 공시와 보도의 대상 기업이 일치합니다.')).toBeVisible();
    });
    it('distinguishes evidence added to the current review from the original selection evidence', async () => {
        const gateway = candidateNetwork(); const review = reviewFixture('candidate');
        Object.assign(review.items[0].sources[0], { available_at_original_decision: false });
        gateway.setReview(review); render(<AlphaLabPanel token="member-token" desk />);
        await screen.findByText('연구 후보 1종목 비교');
        fireEvent.click(screen.getByText('출처·인용 확인 (1개)'));
        expect(screen.getByText('선정 이후 추가 자료')).toBeVisible();
        expect(screen.queryByText('선정 당시 자료')).toBeNull();
    });
});
