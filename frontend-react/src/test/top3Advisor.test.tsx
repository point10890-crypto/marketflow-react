import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Top3AdvisorPanel from '@/components/aibain/Top3AdvisorPanel';
import { validateTop3Advisor } from '@/lib/top3Advisor';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', async importOriginal => ({ ...await importOriginal<typeof import('@/lib/api')>(),
    fetchWithTimeout: async (...args: unknown[]) => {
        const result = await api.get(...args);
        return result instanceof Response ? result : new Response(JSON.stringify(result), { status: 200 });
    },
}));
import { advisorFixture as fixture } from './fixtures/top3AdvisorFixture';
const origin = '2026-11-06T11:31:00Z';
function show(token = 'member') {
    return render(<StrictMode><MemoryRouter><Top3AdvisorPanel token={token} /></MemoryRouter></StrictMode>);
}
beforeEach(() => { api.get.mockReset().mockResolvedValue(fixture()); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('TOP3 advisor dashboard', () => {
    it('shows the verified regular session, fixed order, entry ceiling and research exposure', async () => {
        const view = fixture();
        Object.assign(view, { source_basis: 'candidate-regular-v1', source_session: '2026-11-06',
            source_price_basis: 'KRX_regular_0900_1530_OHLC', source_policy: 'krx-regular-ohlc-v1' });
        view.debate.ranking_basis = 'sealed_contextual';
        view.top3.forEach(row => Object.assign(row, { basis: 'candidate-regular-v1',
            risk: { reference_weight: .01, approved_exposure: 0, live_orders: false } }));
        Object.assign(view.top3[0], { plan: { entry_price: 95000, entry_upper: 101000, stop_price: 90000, target_price: 120000 } });
        api.get.mockResolvedValue(view); show();
        expect(await screen.findByText('KRX 정규장 OHLC · 2026-11-06')).toBeVisible();
        expect(screen.getByText('저장된 후보 순위 · 근거 검토 완료')).toBeVisible();
        const card = screen.getByRole('article', { name: '어드바이저 1위 코웨이' });
        fireEvent.click(within(card).getByText('가격·진입 조건·출처 보기'));
        expect(within(card).getByText('95,000원 ~ 101,000원')).toBeVisible();
        expect(within(card).getByText('참고 비중 1% · 승인 비중 0%')).toBeVisible();
        Object.assign(view.top3[0], { risk: { approved_exposure: .01, live_orders: false } });
        expect(() => validateTop3Advisor(view)).toThrow();
    });
    it('preserves issued entry ranges when there is no single entry_price', async () => {
        const view = fixture();
        Object.assign(view.top3[0], { basis: 'issued_opportunities', plan: { entry_low: 95000, entry_high: 101000, stop_price: 90000, target_price: 120000 } });
        api.get.mockResolvedValue(view); show();
        const card = await screen.findByRole('article', { name: '어드바이저 1위 코웨이' });
        fireEvent.click(within(card).getByText('가격·진입 조건·출처 보기'));
        expect(within(card).getByText('95,000원 ~ 101,000원')).toBeVisible();
        expect(within(card).getByText('90,000원')).toBeVisible();
    });
    it('shows all three saved ranks, evidence gaps and held status without claiming buy approval', async () => {
        show();
        const panel = within(screen.getByRole('region', { name: 'TOP3 어드바이저' }));
        expect(await panel.findByRole('heading', { name: '코웨이' })).toBeVisible();
        expect(panel.getAllByRole('article')).toHaveLength(3);
        expect(panel.getAllByText('진입 조건 확인 필요')).toHaveLength(3);
        expect(panel.getByText(/최근 뉴스 0종목/)).toBeVisible();
        expect(panel.getByText(/공시 검증 0종목/)).toBeVisible();
        expect(panel.queryByText(/BUY|매수 승인/)).toBeNull();
        expect(panel.getByRole('link', { name: '코웨이 차트·가격 조건 보기' })).toHaveAttribute('href', '/dashboard/ai-bain/chart-predict?code=021240');
        expect(panel.getByText(/선정 자료/).querySelector('time')).toHaveAttribute('dateTime', origin);
        expect(api.get).toHaveBeenCalledWith(expect.stringContaining('/api/admin/mirofish/alpha-lab/top3-advisor'),
            { headers: { Authorization: 'Bearer member' }, signal: expect.any(AbortSignal) }, 8000);
    });
    it('shows partial debate and fallback as incomplete research, with no synthetic third pick', async () => {
        const view = fixture(); view.status = 'degraded'; view.top3 = view.top3.slice(0, 2);
        view.debate.debate_complete = false; view.debate.ranking_basis = 'deterministic_research';
        view.debate.stages[0].status = 'SUCCESS_FALLBACK'; view.debate.stages[1].status = 'WAITING';
        api.get.mockResolvedValue(view); show();
        expect(await screen.findByText('저장 지표 순위 · 토론 미완료')).toBeVisible();
        expect(screen.getAllByRole('article')).toHaveLength(2);
        expect(screen.getByText('대체 모델 완료')).toBeInTheDocument();
    });
    it.each(['stale', 'missing', 'unavailable'])('keeps a visible explanation for %s', async status => {
        const view = fixture(); view.status = status; view.top3 = [];
        api.get.mockResolvedValue(view); show();
        expect(await screen.findByText(/현재 표시할 TOP3가 없습니다/)).toBeVisible();
        expect(screen.getByRole('button', { name: 'TOP3 저장 결과 새로고침' })).toBeVisible();
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('refreshes saved GETs only and clears stale results on read failure', async () => {
        show(); await screen.findByRole('heading', { name: '코웨이' });
        api.get.mockRejectedValue(new Error('private response not displayed'));
        fireEvent.click(screen.getByRole('button', { name: 'TOP3 저장 결과 새로고침' }));
        expect(await screen.findByText(/TOP3 조회가 지연/)).toBeVisible();
        expect(screen.queryByRole('heading', { name: '코웨이' })).toBeNull();
        expect(screen.queryByText(/private response/)).toBeNull();
    });
    it.each([401, 403])('clears private results and stops polling after %s', async status => {
        vi.useFakeTimers(); show(); await act(async () => {});
        api.get.mockResolvedValue(new Response(JSON.stringify({ error: 'denied' }), { status }));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'TOP3 저장 결과 새로고침' })); });
        expect(screen.getByText(/이용 권한을 확인/)).toBeVisible();
        expect(screen.queryByRole('article')).toBeNull();
        const calls = api.get.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
        expect(api.get).toHaveBeenCalledTimes(calls);
    });
    it('polls visible pages without overlapping or generating new analysis', async () => {
        vi.useFakeTimers(); show(); await act(async () => {});
        const before = api.get.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(api.get).toHaveBeenCalledTimes(before + 1);
        api.get.mockImplementation(() => new Promise(() => {}));
        await act(async () => { await vi.advanceTimersByTimeAsync(90000); });
        expect(api.get).toHaveBeenCalledTimes(before + 2);
    });
    it('resets data when the authenticated session changes', async () => {
        const page = show(); await screen.findByRole('heading', { name: '코웨이' });
        api.get.mockImplementation(() => new Promise(() => {}));
        page.rerender(<MemoryRouter><Top3AdvisorPanel token="another-user" /></MemoryRouter>);
        expect(screen.queryByRole('article')).toBeNull();
    });
});

describe('advisor response contract', () => {
    it('accepts the saved public response', () => { expect(validateTop3Advisor(fixture()).top3).toHaveLength(3); });
    it.each(['duplicates', 'rank', 'stale-picks', 'unknown-source', 'invalid-price', 'invalid-date', 'false-complete'])('rejects %s before display', issue => {
        const view = fixture();
        if (issue === 'duplicates') view.top3[1].symbol = view.top3[0].symbol;
        if (issue === 'rank') view.top3[0].rank = 0;
        if (issue === 'stale-picks') view.status = 'stale';
        if (issue === 'unknown-source') view.top3[0].risks[0].evidence_ids = ['invented'];
        if (issue === 'invalid-price') view.top3[0].reference_price = NaN;
        if (issue === 'invalid-date') view.generated_at = 'yesterday';
        if (issue === 'false-complete') view.debate.stages[1].status = 'WAITING';
        expect(() => validateTop3Advisor(view)).toThrow();
    });
});
