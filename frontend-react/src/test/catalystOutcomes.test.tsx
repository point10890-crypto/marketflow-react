import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CatalystOutcomesPanel from '@/components/aibain/CatalystOutcomesPanel';
import { catalystOutcomeSourceUrl, validateCatalystOutcomes } from '@/lib/catalystOutcomes';
import { catalystOutcomesFixture as fixture } from './fixtures/catalystOutcomesFixture';

const api = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock('@/lib/api', async importOriginal => ({ ...await importOriginal<typeof import('@/lib/api')>(),
    fetchWithTimeout: async (...args: unknown[]) => {
        const result = await api.get(...args);
        return result instanceof Response ? result : new Response(JSON.stringify(result));
    },
}));
function show(token = 'member') {
    return render(<StrictMode><MemoryRouter><CatalystOutcomesPanel token={token} /></MemoryRouter></StrictMode>);
}
beforeEach(() => { api.get.mockReset().mockResolvedValue(fixture()); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('historical catalyst outcomes panel', () => {
    it('shows candidates before cases, denominators, fractional returns and daily reference prices', async () => {
        show();
        const panel = within(screen.getByRole('region', { name: '재료 이후 상승 추적' }));
        const candidate = await panel.findByRole('article', { name: '상승 지속 후보 1위 삼성전자' });
        expect(panel.getAllByRole('article')[0]).toBe(candidate);
        expect(within(candidate).getByText(/점수 72.5/)).toBeVisible();
        expect(within(candidate).queryByText('72.5%')).toBeNull();
        expect(panel.getByText(/상승 4건 \/ 완료 9건/)).toBeVisible();
        expect(panel.getByText(/보존 재료 15건/)).toBeVisible();
        expect(panel.getByText(/가격 확보 6 \/ 8종목/)).toBeVisible();
        expect(panel.getByText(/매일 10:00 · 15:00/)).toBeVisible();
        expect(panel.getByText(/한국시간/)).toBeVisible();
        expect(panel.getByText(/수익 확률이 아닙니다/)).toBeVisible();
        expect(within(candidate).getByText(/2026-11-10 KIS 완료 일봉/)).toBeVisible();
        expect(panel.getByText('+9.65%')).toBeVisible();
        expect(panel.getByText('-2.35%')).toBeVisible();
        expect(panel.getByRole('link', { name: '반도체 수요 개선 보도' })).toHaveAttribute('rel', 'noopener noreferrer');
        expect(api.get).toHaveBeenLastCalledWith(expect.stringContaining('filter=rising&page=1&page_size=10'),
            { headers: { Authorization: 'Bearer member' }, signal: expect.any(AbortSignal), cache: 'no-store' }, 8000);
    });
    it('allows all retained cases, exact six-digit search and pagination without triggering collection', async () => {
        show(); await screen.findByText('+9.65%');
        fireEvent.click(screen.getByRole('button', { name: '전체 사례' }));
        await act(async () => {});
        expect(api.get.mock.lastCall?.[0]).toContain('filter=all&page=1&page_size=10');
        fireEvent.change(screen.getByRole('textbox', { name: '종목 코드' }), { target: { value: '삼성' } });
        const before = api.get.mock.calls.length;
        fireEvent.click(screen.getByRole('button', { name: '검색' }));
        expect(screen.getByText('종목 코드는 숫자 6자리로 입력해 주세요.')).toBeVisible();
        expect(api.get).toHaveBeenCalledTimes(before);
        fireEvent.change(screen.getByRole('textbox', { name: '종목 코드' }), { target: { value: '005930' } });
        fireEvent.click(screen.getByRole('button', { name: '검색' })); await act(async () => {});
        expect(api.get.mock.lastCall?.[0]).toContain('symbol=005930');
        fireEvent.click(screen.getByRole('button', { name: '다음 사례' })); await act(async () => {});
        expect(api.get.mock.lastCall?.[0]).toContain('page=2');
    });
    it('distinguishes retrospective timing and limited verification from predictive evidence', async () => {
        const view = fixture(); view.cases[0].analysis_basis = 'retrospective'; view.cases[0].verification = 'unexpected_status';
        api.get.mockResolvedValue(view); show();
        expect(await screen.findByText(/사후 수집 · 예측 통계 제외/)).toBeVisible();
        expect(screen.getByText(/검증 범위 미확인/)).toBeVisible();
        expect(screen.getByText(/수신 시각/)).toBeVisible();
        expect(screen.getByText(/관련 공시 확인 · 보도 주장 미확정/)).toBeVisible();
    });
    it.each(['missing', 'partial', 'stale', 'failed'])('explains %s and missing candidates', async status => {
        const view = fixture(); view.status = status; view.candidates = []; view.cases = [];
        view.operation.pending_symbols = 3; api.get.mockResolvedValue(view); show();
        expect(await screen.findByText('현재 조건을 통과한 상승 지속 후보가 없습니다.')).toBeVisible();
        expect(screen.getByText(/가격 수집 대기 3종목/)).toBeVisible();
        expect(screen.getByText(/보존된 자료만 포함/)).toBeVisible();
    });
    it.each(['partial', 'complete_with_gaps'])('does not imply pending work when %s has no pending symbols', async state => {
        const view = fixture(); view.status = 'partial'; view.operation.state = state;
        api.get.mockResolvedValue(view); show(); await screen.findByText('+9.65%');
        expect(screen.getByText(state === 'complete_with_gaps' ? /일부 원본 미완료 · 보존 기록 분석 완료/ : /일부 자료 누락 · 저장 결과 확인/)).toBeVisible();
        expect(screen.queryByText(/일부 자료 수집 중/)).toBeNull();
    });
    it('distinguishes upstream source gaps from completed retained-record analysis', async () => {
        const view = fixture(); view.status = 'partial';
        Object.assign(view.operation, { state: 'complete_with_gaps', error: 'source_coverage_partial' });
        api.get.mockResolvedValue(view); show(); await screen.findByText('+9.65%');
        expect(screen.getByText(/일부 원본 미완료 · 보존 기록 분석 완료/)).toBeVisible();
        expect(screen.queryByText(/일부 자료 처리에 실패/)).toBeNull();
        expect(screen.queryByText(/일부 자료 수집 중/)).toBeNull();
    });
    it.each([401, 403])('clears private output and stops polling on %s', async status => {
        vi.useFakeTimers(); show(); await act(async () => {});
        api.get.mockResolvedValue(new Response('{}', { status }));
        await act(async () => { fireEvent.click(screen.getByRole('button', { name: '상승 추적 저장 결과 새로고침' })); });
        expect(screen.getByRole('alert')).toHaveTextContent('이용 권한');
        expect(screen.queryByRole('article')).toBeNull();
        const calls = api.get.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(120000); });
        expect(api.get).toHaveBeenCalledTimes(calls);
    });
    it('polls every 30 seconds only while visible and aborts an obsolete query', async () => {
        vi.useFakeTimers(); show(); await act(async () => {});
        const before = api.get.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(api.get).toHaveBeenCalledTimes(before + 1);
        vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
        fireEvent(document, new Event('visibilitychange'));
        await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(api.get).toHaveBeenCalledTimes(before + 1);
        vi.restoreAllMocks();
        api.get.mockImplementation(() => new Promise(() => {}));
        fireEvent(document, new Event('visibilitychange')); await act(async () => {});
        const previousSignal = api.get.mock.lastCall?.[1].signal as AbortSignal;
        fireEvent.click(screen.getByRole('button', { name: '전체 사례' })); await act(async () => {});
        expect(previousSignal.aborted).toBe(true);
    });
    it('aborts unmounted requests and clears the previous account immediately', async () => {
        const page = show(); await screen.findByText('+9.65%');
        api.get.mockImplementation(() => new Promise(() => {}));
        page.rerender(<MemoryRouter><CatalystOutcomesPanel token="new-member" /></MemoryRouter>);
        expect(screen.queryByRole('article')).toBeNull();
        const signal = api.get.mock.lastCall?.[1].signal as AbortSignal;
        page.unmount(); expect(signal.aborted).toBe(true);
    });
    it('does not fetch an initially hidden document or overlap an unfinished read', async () => {
        vi.useFakeTimers();
        vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
        show(); await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
        expect(api.get).not.toHaveBeenCalled();
        vi.restoreAllMocks(); api.get.mockImplementation(() => new Promise(() => {}));
        fireEvent(document, new Event('visibilitychange'));
        await act(async () => { await vi.advanceTimersByTimeAsync(90000); });
        expect(api.get).toHaveBeenCalledTimes(1);
    });
    it('ignores a completed response from a superseded filter', async () => {
        let finish: ((value: ReturnType<typeof fixture>) => void) | undefined;
        api.get.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
        show(); const previous = finish;
        api.get.mockResolvedValue(fixture());
        fireEvent.click(screen.getByRole('button', { name: '전체 사례' }));
        await screen.findByText('+9.65%');
        const old = fixture(); old.candidates[0].name = '이전 조회 종목';
        await act(async () => { previous?.(old); });
        expect(screen.queryByText(/이전 조회 종목/)).toBeNull();
    });
    it('keeps revised outcomes out of the headline returns and unsafe source URLs as text', async () => {
        const view = fixture(); view.cases[0].horizons['10'].source_revision = true;
        view.cases[0].url = 'javascript:alert(1)'; api.get.mockResolvedValue(view); show();
        expect(await screen.findByText('원본 수정')).toBeVisible();
        expect(screen.queryByText('+9.65%')).toBeNull();
        expect(screen.queryByRole('link', { name: view.cases[0].title })).toBeNull();
        expect(screen.getByText(view.cases[0].title)).toBeVisible();
    });
    it('states next-session close entry and close-based excursions consistently', async () => {
        show(); await screen.findByText('+9.65%');
        expect(screen.getByText(/관측 기준일 다음 거래일 종가 진입/)).toBeVisible();
        expect(screen.queryByText(/시가 진입/)).toBeNull();
        fireEvent.click(screen.getByText('진입·청산과 가격 근거'));
        expect(within(screen.getByRole('article', { name: '삼성전자 과거 재료 event-1' })).getByText(/기준일 다음 거래일 종가 진입/)).toBeVisible();
        expect(screen.getAllByText(/종가 기준 최대 상승/)).toHaveLength(3);
        expect(screen.getAllByText(/종가 기준 최대 하락/)).toHaveLength(3);
    });
    it('shows withdrawn cases as excluded while retaining archived returns and server counts', async () => {
        const view = fixture(); Object.assign(view.cases[0], { exclusion: 'withdrawn' });
        Object.assign(view.coverage, { matured_events: 8, positive_events: 3, excluded_events: 4 });
        api.get.mockResolvedValue(view); show();
        expect(await screen.findByText('철회된 재료 · 통계·후보 선정 제외')).toBeVisible();
        expect(screen.getByText('+9.65%')).toBeVisible();
        expect(screen.getByText(/상승 3건 \/ 완료 8건/)).toBeVisible();
        expect(screen.getByText('상승·완료 집계는 철회된 재료를 제외합니다.')).toBeVisible();
        expect(screen.getAllByText('보존 수익 · 통계 제외')).toHaveLength(2);
    });
    it('renders generic read failure and clears old financial values', async () => {
        show(); await screen.findByText('+9.65%');
        api.get.mockRejectedValue(new Error('private error detail'));
        fireEvent.click(screen.getByRole('button', { name: '상승 추적 저장 결과 새로고침' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('조회가 지연');
        expect(screen.queryByText('+9.65%')).toBeNull(); expect(screen.queryByText('private error detail')).toBeNull();
    });
});

describe('catalyst outcomes contract', () => {
    it('accepts complete and pending horizons with retained source provenance', () => {
        expect(validateCatalystOutcomes(fixture()).cases[0].horizons['20'].net_return).toBeNull();
    });
    it.each([undefined, null, 'withdrawn', 'source_revision'])('accepts optional case exclusion %s', exclusion => {
        const view = fixture(); if (exclusion !== undefined) Object.assign(view.cases[0], { exclusion });
        expect(validateCatalystOutcomes(view).cases[0].exclusion).toBe(exclusion);
    });
    it.each([42, {}, '', 'withdrawn\u0000'])('rejects malformed case exclusion %s', exclusion => {
        const view = fixture(); Object.assign(view.cases[0], { exclusion });
        expect(() => validateCatalystOutcomes(view)).toThrow();
    });
    it.each(['symbol', 'price', 'date', 'clock', 'rank', 'duplicate', 'denominator', 'incomplete-return'])('rejects malformed %s', issue => {
        const view = fixture();
        if (issue === 'symbol') view.candidates[0].symbol = '005930&force=true';
        if (issue === 'price') view.candidates[0].price = NaN;
        if (issue === 'date') view.as_of_session = '2026-02-30';
        if (issue === 'clock') view.generated_at = '2026-11-11T10:00:00';
        if (issue === 'rank') view.candidates[0].rank = 0;
        if (issue === 'duplicate') view.cases.push(view.cases[0]);
        if (issue === 'denominator') view.coverage.positive_events = 10;
        if (issue === 'incomplete-return') view.cases[0].horizons['20'].status = 'completed';
        expect(() => validateCatalystOutcomes(view)).toThrow();
    });
    it.each(['javascript:alert(1)', 'http://localhost:5001/private', 'https://127.0.0.1/a', 'https://user:pass@news.example.com/a', 'https://news.internal/a'])('does not link unsafe source %s', url => {
        expect(catalystOutcomeSourceUrl(url)).toBeNull();
    });
});
