import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SurgeTracePanel from '@/components/aibain/SurgeTracePanel';
import { validateSurgeTraces } from '@/lib/surgeTrace';
import { surgeTraceFixture } from './fixtures/surgeTraceFixture';

const endpoint = '/api/admin/mirofish/kongming/surge-traces';
let payload: unknown;
let httpStatus: number;
let transport: ReturnType<typeof vi.fn>;
function show(token = 'fixture-member') { return render(<StrictMode><SurgeTracePanel token={token} /></StrictMode>); }
beforeEach(() => {
    payload = surgeTraceFixture(); httpStatus = 200;
    sessionStorage.setItem('auth_token', 'fixture-member');
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    transport = vi.fn(async () => new Response(JSON.stringify(payload), { status: httpStatus }));
    vi.stubGlobal('fetch', transport);
    vi.spyOn(console, 'error').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); sessionStorage.clear(); });

describe('surge trace dashboard', () => {
    it('renders exact observed values and separate price/discovery clocks from saved authenticated GET', async () => {
        show();
        const card = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        expect(within(card).getByText('+6.37%')).toBeVisible();
        expect(within(card).getByText('71,200원')).toBeVisible();
        expect(within(card).getByText('2,345,678,910원')).toBeVisible();
        expect(within(card).getByText('유력 재료 후보')).toBeVisible();
        expect(within(card).getByText('시세 관측').parentElement?.querySelector('time')).toHaveAttribute('dateTime', '2026-11-10T10:00:00+09:00');
        expect(within(card).getByText('서비스 최초 발견').parentElement?.querySelector('time')).toHaveAttribute('dateTime', '2026-11-10T10:05:00+09:00');
        expect(transport).toHaveBeenCalledTimes(1);
        expect(transport.mock.calls[0][0]).toContain(endpoint);
        const init = transport.mock.calls[0][1] as RequestInit;
        expect(init.method ?? 'GET').toBe('GET');
        expect(new Headers(init.headers).get('Authorization')).toBe('Bearer fixture-member');
    });
    it('keeps publication, receipt, uncertain date order and negative material visible in evidence details', async () => {
        show(); const card = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        fireEvent.click(within(card).getByText('재료 근거·발표 시각 보기'));
        expect(within(card).getByText('관측 전 발표')).toBeVisible();
        expect(within(card).getByText('관측 후 보도')).toBeVisible();
        expect(within(card).getByText('당일 선후 미확인')).toBeVisible();
        expect(within(card).getAllByText('관측 후 확보한 자료')).toHaveLength(3);
        expect(within(card).getByText('부정 재료')).toBeVisible();
        expect(within(card).getByText('호재·위험 혼재')).toBeVisible();
        expect(within(card).getByText('2026-11-10 (시간 미확인)')).toBeVisible();
        const link = within(card).getByRole('link', { name: '삼성전자 공급 계약 발표' });
        expect(link).toHaveAttribute('target', '_blank');
        expect(link).toHaveAttribute('rel', 'noopener noreferrer');
        expect(within(card).getAllByText('최초 수신')).toHaveLength(3);
    });
    it('filters the saved list by company or code without another network request', async () => {
        show(); await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        fireEvent.change(screen.getByRole('searchbox', { name: '급등 종목 이름 또는 코드 검색' }), { target: { value: '000660' } });
        expect(screen.queryByRole('article', { name: '삼성전자 급등 이유' })).toBeNull();
        expect(screen.getByRole('article', { name: 'SK하이닉스 급등 이유' })).toBeVisible();
        fireEvent.change(screen.getByRole('searchbox'), { target: { value: '없는종목' } });
        expect(screen.getByText('저장된 결과에 일치하는 종목이 없습니다.')).toBeVisible();
        expect(transport).toHaveBeenCalledTimes(1);
    });
    it('distinguishes a source error from an empty successful source without inventing a count', async () => {
        show(); const card = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        fireEvent.click(within(card).getByText('출처 확인·수집 상태'));
        expect(within(card).getByText(/Google 뉴스 · 수집 실패/)).toBeVisible();
        expect(within(card).getByText(/결과 수 미확인/)).toBeVisible();
        const unresolved = screen.getByRole('article', { name: 'SK하이닉스 급등 이유' });
        expect(within(unresolved).getByText('원인 미확인')).toBeVisible();
        fireEvent.click(within(unresolved).getByText('출처 확인·수집 상태'));
        expect(within(unresolved).getByText(/OpenDART · 관련 자료 없음/)).toBeVisible();
    });
    it.each(['no_surge', 'waiting', 'unavailable'])('shows an honest empty state for %s', async status => {
        payload = { ...surgeTraceFixture(), status, items: [] };
        show(); expect(await screen.findByText('현재 표시할 급등 관측 결과가 없습니다.')).toBeVisible();
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('labels historical prices and unknown statuses without treating them as ready', async () => {
        const view = surgeTraceFixture(); view.operation.source_status = 'historical'; view.items[0].status = 'new_server_status'; payload = view;
        show(); const card = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        expect(screen.getByText(/장외 저장 관측/)).toBeVisible();
        expect(within(card).getByText('미확인')).toBeVisible();
    });
    it('separates same-day off-hours stored prices from older session observations', async () => {
        vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-11-10T11:00:00+09:00'));
        const view = surgeTraceFixture(); view.operation.source_status = 'historical';
        view.items[0].limitations = ['historical_observation']; view.items[1].session = '2026-11-09'; payload = view;
        show(); const sameDay = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        expect(within(sameDay).queryByText(/과거 세션/)).toBeNull();
        expect(within(sameDay).getByText('저장 시세 관측 · 현재 시세가 아닙니다.')).toBeVisible();
        fireEvent.click(within(sameDay).getByText('출처 확인·수집 상태'));
        expect(within(sameDay).getByText('저장된 시세 관측이며 현재 시세가 아닙니다.')).toBeVisible();
        expect(within(screen.getByRole('article', { name: 'SK하이닉스 급등 이유' })).getByText('과거 세션 관측 · 현재 시세가 아닙니다.')).toBeVisible();
    });
    it('explains archival freshness, revised timing and opposing evidence instead of hiding limitations', async () => {
        const view = surgeTraceFixture();
        view.items[0].limitations = ['omni_archive_freshness_unknown', 'evidence_revision_timing_unknown', 'risk_or_opposing_evidence'];
        view.operation.source_status = 'unknown_market_status'; payload = view;
        show(); const card = await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        expect(screen.getByText(/시장 운영 상태 미확인/)).toBeVisible();
        fireEvent.click(within(card).getByText('출처 확인·수집 상태'));
        expect(within(card).getByText('보관된 Omni 기사 조회이며 최신 수집 상태는 확인되지 않았습니다.')).toBeVisible();
        expect(within(card).getByText('정정된 기사 내용의 발표 선후는 확인되지 않았습니다.')).toBeVisible();
        expect(within(card).getByText('위험·반대 재료도 함께 확인됐습니다.')).toBeVisible();
    });
    it.each([401, 403])('clears existing results and stops all polling after real HTTP %s', async status => {
        show(); await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        httpStatus = status; fireEvent.click(screen.getByRole('button', { name: '급등 저장 결과 새로고침' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('이용 권한');
        expect(screen.queryByRole('article')).toBeNull();
        const count = transport.mock.calls.length;
        vi.useFakeTimers(); await act(async () => { await vi.advanceTimersByTimeAsync(90000); });
        expect(transport).toHaveBeenCalledTimes(count);
        expect(screen.getByRole('button', { name: '급등 저장 결과 새로고침' })).toBeDisabled();
    });
    it('clears stale results after a server error', async () => {
        show(); await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        httpStatus = 503; fireEvent.click(screen.getByRole('button', { name: '급등 저장 결과 새로고침' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('조회');
        expect(screen.queryByRole('article')).toBeNull();
    });
    it('does not poll while hidden and reuses an outstanding request', async () => {
        vi.useFakeTimers(); Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
        show(); await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(transport).not.toHaveBeenCalled();
        transport.mockImplementation(() => new Promise(() => {}));
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
        await act(async () => { document.dispatchEvent(new Event('visibilitychange')); await vi.advanceTimersByTimeAsync(60000); });
        expect(transport).toHaveBeenCalledTimes(1);
    });
    it('removes prior user results immediately and ignores a late prior user response', async () => {
        const page = show(); await screen.findByRole('article', { name: '삼성전자 급등 이유' });
        let release!: (response: Response) => void;
        transport.mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }));
        fireEvent.click(screen.getByRole('button', { name: '급등 저장 결과 새로고침' }));
        transport.mockImplementation(() => new Promise(() => {})); sessionStorage.setItem('auth_token', 'another-user');
        page.rerender(<StrictMode><SurgeTracePanel token="another-user" /></StrictMode>);
        expect(screen.queryByRole('article')).toBeNull();
        await act(async () => { release(new Response(JSON.stringify(surgeTraceFixture()))); });
        expect(screen.queryByRole('article')).toBeNull();
    });
});

describe('surge trace response validation', () => {
    it.each(['unsafe-link', 'invalid-time', 'invalid-price', 'duplicate-row', 'malformed-evidence', 'too-many-rows'])('rejects %s before display', issue => {
        const view = surgeTraceFixture();
        if (issue === 'unsafe-link') view.items[0].evidence[0].url = 'javascript:alert(1)';
        if (issue === 'invalid-time') view.items[0].price_observed_at = '2026-11-10T10:00:00';
        if (issue === 'invalid-price') view.items[0].price = NaN;
        if (issue === 'duplicate-row') view.items[1].id = view.items[0].id;
        if (issue === 'malformed-evidence') view.items[0].evidence[0].direction = 'buy-now';
        if (issue === 'too-many-rows') view.items = Array.from({ length: 21 }, (_, i) => ({ ...view.items[0], id: String(i) }));
        expect(() => validateSurgeTraces(view)).toThrow();
    });
    it('preserves explicit unknown metadata and valid date-only disclosures', () => {
        const view = surgeTraceFixture();
        const unknown = { ...view, source_as_of: null, items: [{ ...view.items[0], first_detected_at: null, summary: null }] };
        expect(validateSurgeTraces(unknown).items[0].first_detected_at).toBeNull();
    });
});
