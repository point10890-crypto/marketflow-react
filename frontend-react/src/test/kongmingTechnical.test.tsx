import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import KongmingTechnicalPanel from '@/components/aibain/KongmingTechnicalPanel';
import { fetchTechnicalProfiles, queueTechnicalProfile, validateTechnicalProfiles } from '@/lib/kongmingTechnical';
import { kongmingTechnicalFixture } from './fixtures/kongmingTechnicalFixture';

const endpoint = '/api/admin/mirofish/kongming/technical-profiles';
let payload: unknown;
let httpStatus: number;
let transport: ReturnType<typeof vi.fn>;
function show(token: string | undefined = 'fixture-member') {
    return render(<StrictMode><KongmingTechnicalPanel token={token} /></StrictMode>);
}
beforeEach(() => {
    payload = kongmingTechnicalFixture(); httpStatus = 200;
    sessionStorage.setItem('auth_token', 'fixture-member');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    transport = vi.fn(async (_input: string, init?: RequestInit) => new Response(JSON.stringify(init?.method === 'POST'
        ? { schema_version: 1, status: 'queued', symbol: JSON.parse(String(init.body)).symbol } : payload), { status: init?.method === 'POST' ? 202 : httpStatus }));
    vi.stubGlobal('fetch', transport);
    vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

describe('technical profile validation and client', () => {
    it.each(['nonfinite-total', 'negative-zone', 'wrong-symbol', 'duplicate-symbol', 'unknown-schema', 'invalid-date', 'unknown-method', 'missing-level', 'string-number'])('rejects %s instead of displaying unreliable values', issue => {
        const view = kongmingTechnicalFixture();
        const data = view as unknown as Record<string, unknown>;
        const row = view.items[0] as unknown as Record<string, unknown>;
        if (issue === 'nonfinite-total') row.total_volume = Infinity;
        if (issue === 'negative-zone') view.items[0].bins[0].volume = -1;
        if (issue === 'wrong-symbol') row.symbol = '123';
        if (issue === 'duplicate-symbol') view.items.push(view.items[0]);
        if (issue === 'unknown-schema') data.schema_version = 2;
        if (issue === 'invalid-date') row.window_end = '2026-02-31';
        if (issue === 'unknown-method') row.method = 'predicted_holdings';
        if (issue === 'missing-level') delete row.support;
        if (issue === 'string-number') row.reference_price = '71150';
        expect(() => validateTechnicalProfiles(view)).toThrow();
    });
    it('keeps absent levels nullable and accepts uppercase alphanumeric symbols', () => {
        const view = kongmingTechnicalFixture();
        const row = { ...view.items[0], symbol: '0008T0', support: null, resistance: null };
        expect(validateTechnicalProfiles({ ...view, items: [row] }).items[0]).toMatchObject({ symbol: '0008T0', support: null, resistance: null });
    });
    it('rejects invalid symbols before any network request and limits POST to the symbol', async () => {
        await expect(queueTechnicalProfile('bad/code')).rejects.toThrow();
        await expect(fetchTechnicalProfiles('12')).rejects.toThrow();
        expect(transport).not.toHaveBeenCalled();
        await queueTechnicalProfile('0008T0');
        const [url, init] = transport.mock.calls[0] as [string, RequestInit];
        expect(url).toContain(endpoint); expect(init.method).toBe('POST');
        expect(JSON.parse(String(init.body))).toEqual({ symbol: '0008T0' });
        expect(new Headers(init.headers).get('Authorization')).toBe('Bearer fixture-member');
    });
    it('rejects a queue receipt for a different symbol', async () => {
        transport.mockResolvedValueOnce(new Response(JSON.stringify({ schema_version: 1, status: 'queued', symbol: '000660' }), { status: 202 }));
        await expect(queueTechnicalProfile('005930')).rejects.toThrow();
    });
    it('accepts the bounded 500-symbol saved universe and rejects an oversized response', () => {
        const view = kongmingTechnicalFixture();
        view.items = Array.from({ length: 500 }, (_, index) => ({ ...view.items[0], symbol: String(index).padStart(6, '0') }));
        expect(validateTechnicalProfiles(view).items).toHaveLength(500);
        view.items.push({ ...view.items[0], symbol: '999999' });
        expect(() => validateTechnicalProfiles(view)).toThrow();
    });
    it('filters a saved lookup by a validated alphanumeric code without queuing', async () => {
        await fetchTechnicalProfiles('0008T0');
        const [url, init] = transport.mock.calls[0];
        expect(new URL(url, 'http://localhost').searchParams.get('symbol')).toBe('0008T0');
        expect(init.method ?? 'GET').toBe('GET');
    });
});

describe('technical analysis panel', () => {
    it('shows saved totals, reference close, actual dates and all 24 readable bins', async () => {
        show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        expect(card.getByText('약 2.4만주')).toBeVisible();
        expect(card.getByText('약 17억원')).toBeVisible();
        expect(card.getByText('기준 종가').parentElement).toHaveTextContent('71,150원');
        expect(card.getByText(/2026-10-16.*2026-11-12/)).toBeVisible();
        expect(card.getByRole('list', { name: '가격대별 추정 거래량' }).children).toHaveLength(24);
        expect(card.getByRole('list', { name: '가격대별 추정 거래량' })).toHaveTextContent('70,000');
        expect(card.getByText(/일봉 OHLCV.*균등.*추정/)).toBeVisible();
        expect(screen.getByText(/보유 물량이나 호가 잔량/)).toBeVisible();
        expect(transport).toHaveBeenCalledTimes(1);
        expect(transport.mock.calls[0][1]?.method ?? 'GET').toBe('GET');
    });
    it('uses compact Korean units and whole-won ranges while retaining exact source values', async () => {
        const view = kongmingTechnicalFixture();
        view.items[0].total_traded_value = 76000000000000;
        Object.assign(view.items[0].bins[15], { low: 71500.333333, high: 71600.666667, volume: 39523951.4986, traded_value: 8387435528886 });
        payload = view; show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        expect(card.getByText('약 76조원')).toHaveAttribute('title', '76,000,000,000,000원');
        const level = within(card.getByLabelText('저항 후보'));
        expect(level.getByText('약 71,500원 ~ 71,601원')).toHaveAttribute('title', '71,500.333333원 ~ 71,600.666667원');
        expect(level.getByText('약 3,952만주')).toHaveAttribute('title', '39,523,951.4986주');
        expect(level.getByText('약 8.4조원')).toHaveAttribute('title', '8,387,435,528,886원');
        expect(level.getByText(/추정 거래대금/)).toBeVisible();
        expect(card.getByRole('list', { name: '가격대별 추정 거래량' })).toHaveTextContent('약 3,952만주');
    });
    it('keeps positive estimates below one share or won distinct from zero', async () => {
        const view = kongmingTechnicalFixture();
        Object.assign(view.items[0].bins[15], { volume: 0.4, traded_value: 0.3 });
        payload = view; show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        const level = within(card.getByLabelText('저항 후보'));
        expect(level.getByText('1주 미만')).toHaveAttribute('title', '0.4주');
        expect(level.getByText('1원 미만')).toHaveAttribute('title', '0.3원');
    });
    it('does not fabricate missing support or resistance', async () => {
        const view = kongmingTechnicalFixture();
        payload = { ...view, items: [{ ...view.items[0], support: null, resistance: null }] };
        show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        expect(card.getByLabelText('지지 후보')).toHaveTextContent('해당 가격대 없음');
        expect(card.getByLabelText('저항 후보')).toHaveTextContent('해당 가격대 없음');
        expect(card.getByLabelText('지지 후보')).not.toHaveTextContent('0원');
    });
    it('explains insufficient history without charts or made-up totals', async () => {
        const view = kongmingTechnicalFixture();
        payload = { ...view, items: [{ ...view.items[0], status: 'insufficient_history', reason: 'missing_sessions', sessions_used: 6,
            reference_price: null, total_volume: null, total_traded_value: null, poc: null, support: null, resistance: null, current_zone: null, bins: [] }] };
        show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        expect(card.getByText(/6.*20.*거래일/)).toBeVisible();
        expect(card.queryByRole('list', { name: '가격대별 추정 거래량' })).toBeNull();
        expect(card.getByText(/거래일 자료.*부족.*계산하지/)).toBeVisible();
    });
    it('explains a zero-volume window separately from missing history', async () => {
        const view = kongmingTechnicalFixture();
        payload = { ...view, items: [{ ...view.items[0], status: 'insufficient_history', reason: 'zero_volume_window',
            reference_price: null, total_volume: null, total_traded_value: null, poc: null, support: null, resistance: null, current_zone: null, bins: [] }] };
        show();
        const card = within(await screen.findByRole('article', { name: '삼성전자 20일 매물대' }));
        expect(card.getByText(/거래량이 없어/)).toBeVisible();
        expect(card.queryByRole('list', { name: '가격대별 추정 거래량' })).toBeNull();
        expect(card.queryByText(/거래일 자료.*부족/)).toBeNull();
    });
    it('searches known Korean names without requesting a job and queues a manual alphanumeric code only on submit', async () => {
        show(); await screen.findByRole('article');
        const input = screen.getByRole('searchbox', { name: '기술 분석 종목명 또는 코드' });
        fireEvent.change(input, { target: { value: '삼성' } });
        expect(screen.getByRole('button', { name: '삼성전자 005930 선택' })).toBeVisible();
        expect(transport.mock.calls.every(call => call[1]?.method !== 'POST')).toBe(true);
        fireEvent.change(input, { target: { value: '0008t0' } });
        fireEvent.click(screen.getByRole('button', { name: '매물대 조회 요청' }));
        expect(await screen.findByText(/0008T0.*수집 대기/)).toBeVisible();
        const posts = transport.mock.calls.filter(call => call[1]?.method === 'POST');
        expect(posts).toHaveLength(1); expect(JSON.parse(posts[0][1].body)).toEqual({ symbol: '0008T0' });
    });
    it('shows recent candidate shortcuts by collection time instead of server name order', async () => {
        const view = kongmingTechnicalFixture();
        payload = { ...view, items: [...view.items, { ...view.items[0], symbol: '000660', name: 'SK하이닉스', fetched_at: '2026-11-13T20:31:00+09:00' }] };
        show();
        expect(await screen.findByRole('article', { name: 'SK하이닉스 20일 매물대' })).toBeVisible();
        const shortcuts = screen.getAllByRole('button', { name: /선택$/ });
        expect(shortcuts[0]).toHaveAccessibleName('SK하이닉스 000660 선택');
        fireEvent.click(shortcuts[1]);
        expect(screen.getByRole('article', { name: '삼성전자 20일 매물대' })).toBeVisible();
        expect(transport.mock.calls.every(call => call[1]?.method !== 'POST')).toBe(true);
    });
    it('reads saved results on visible polling without POST or other paid endpoints', async () => {
        vi.useFakeTimers(); show();
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(transport.mock.calls.length).toBeGreaterThan(1);
        for (const [url, init] of transport.mock.calls) {
            expect(new URL(String(url), 'http://localhost').pathname).toBe(endpoint);
            expect(init?.method ?? 'GET').toBe('GET');
        }
    });
    it('replaces the queued notice with the completed saved profile on a later poll', async () => {
        vi.useFakeTimers(); show(); await act(async () => {});
        fireEvent.change(screen.getByRole('searchbox'), { target: { value: '0008T0' } });
        fireEvent.click(screen.getByRole('button', { name: '매물대 조회 요청' }));
        await act(async () => {});
        expect(screen.getByText(/0008T0.*수집 대기/)).toBeVisible();
        const view = kongmingTechnicalFixture();
        payload = { ...view, items: [...view.items, { ...view.items[0], symbol: '0008T0', name: '신규 종목' }] };
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(screen.getByRole('article', { name: '신규 종목 20일 매물대' })).toBeVisible();
        expect(screen.queryByText(/0008T0.*수집 대기/)).toBeNull();
        expect(transport.mock.calls.filter(call => call[1]?.method === 'POST')).toHaveLength(1);
    });
    it('waits while hidden and prevents overlapping saved requests', async () => {
        vi.useFakeTimers(); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
        show(); await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(transport).not.toHaveBeenCalled();
        transport.mockImplementation(() => new Promise(() => {}));
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
        await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(60000); });
        expect(transport).toHaveBeenCalledTimes(1);
    });
    it('keeps prior data explicitly stale after a temporary error but clears it on access denial', async () => {
        show(); await screen.findByRole('article');
        httpStatus = 503; fireEvent.click(screen.getByRole('button', { name: '매물대 저장 결과 새로고침' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('이전에 저장된 자료');
        expect(screen.getByRole('article')).toBeVisible();
        httpStatus = 403; fireEvent.click(screen.getByRole('button', { name: '매물대 저장 결과 새로고침' }));
        await act(async () => {});
        expect(screen.queryByRole('article')).toBeNull();
        expect(screen.getByRole('button', { name: '매물대 조회 요청' })).toBeDisabled();
    });
    it('clears private results on logout and ignores a late prior-session response', async () => {
        const page = show(); await screen.findByRole('article');
        let release!: (reply: Response) => void;
        transport.mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }));
        fireEvent.click(screen.getByRole('button', { name: '매물대 저장 결과 새로고침' }));
        sessionStorage.removeItem('auth_token');
        page.rerender(<StrictMode><KongmingTechnicalPanel /></StrictMode>);
        expect(screen.queryByRole('article')).toBeNull();
        await act(async () => { release(new Response(JSON.stringify(kongmingTechnicalFixture()))); });
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('does not request member data when no token is provided', async () => {
        render(<KongmingTechnicalPanel />); await act(async () => {});
        expect(transport).not.toHaveBeenCalled();
    });
});
