import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AdminStockAnalysisPanel from '@/components/aibain/AdminStockAnalysisPanel';
import { analysisNow, stockAnalysis } from './adminStockAnalysisFixtures';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn(), postAuthAPI: vi.fn() }));
const auth = vi.hoisted(() => ({ token: 'admin-token' as string | null, role: 'admin', status: 'approved', loading: false }));
vi.mock('@/lib/api', () => api);
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: auth.token, user: { role: auth.role, status: auth.status }, loading: auth.loading }) }));
const endpoint = '/api/admin/mirofish/stock-analysis';
function CurrentPath() { const location = useLocation(); return <output aria-label="현재 경로">{location.pathname}{location.search}{location.hash}</output>; }
function renderPage(code = '042700') { return render(<MemoryRouter initialEntries={[`/dashboard/ai-bain/chart-predict?code=003690&view=evidence${code ? `&adminCode=${code}` : ''}#kept`]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><AdminStockAnalysisPanel /><CurrentPath /></MemoryRouter>); }
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(r => { resolve = r; }); return { promise, resolve }; }

describe('embedded admin selected-stock analysis panel', () => {
    beforeEach(() => {
        vi.useRealTimers(); vi.spyOn(Date, 'now').mockReturnValue(Date.parse(analysisNow));
        auth.token = 'admin-token'; auth.role = 'admin'; auth.status = 'approved'; auth.loading = false; api.fetchAuthAPI.mockReset(); api.postAuthAPI.mockReset();
        api.fetchAuthAPI.mockResolvedValue(stockAnalysis());
    });
    afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

    it('restores only the requested saved result and makes reference prices prominent on WAIT', async () => {
        const value = stockAnalysis(); value.result!.candidate.proposal.action = 'wait'; value.result!.candidate.proposal.label = '진입 대기'; value.result!.candidate.proposal.proposed_weight = 0;
        api.fetchAuthAPI.mockResolvedValue(value); renderPage();
        const card = await screen.findByRole('article', { name: /한미반도체 042700/ });
        expect(within(card).getByText('WAIT · 진입 대기')).toBeInTheDocument();
        for (const price of ['100,000원', '92,000원', '116,000원']) expect(within(card).getAllByText(price).length).toBeGreaterThan(0);
        expect(within(card).getByText('0.0%')).toBeInTheDocument();
        expect(screen.getByText(/저장 스냅샷/)).toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledWith(`${endpoint}/042700`, 'admin-token', 15000);
        expect(api.postAuthAPI).not.toHaveBeenCalled();
        expect(screen.getByRole('heading', { level: 3, name: '관리자 전용 종목 검색 분석' })).toBeInTheDocument();
        expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: '관리자 대시보드' })).not.toBeInTheDocument();
    });

    it('resolves names with keyboard selection, updates the URL and waits for an explicit analysis click', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/search?')
            ? { candidates: [{ symbol: '042700', name: '한미반도체', market: 'KR' }, { symbol: '005930', name: '삼성전자', market: 'KR' }] } : stockAnalysis('005930', '삼성전자')));
        renderPage('');
        await userEvent.type(screen.getByRole('combobox', { name: '종목명 또는 코드' }), '삼성');
        await screen.findByRole('option', { name: /삼성전자/ });
        await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}');
        await screen.findByRole('article', { name: /삼성전자 005930/ });
        expect(screen.getByLabelText('현재 경로')).toHaveTextContent('?code=003690&view=evidence&adminCode=005930#kept');
        expect(api.postAuthAPI).not.toHaveBeenCalled();
        api.postAuthAPI.mockResolvedValue(stockAnalysis('005930', '삼성전자'));
        await userEvent.click(screen.getByRole('button', { name: '분석 실행' }));
        expect(api.postAuthAPI).toHaveBeenCalledWith(endpoint, { symbol: '005930' }, 'admin-token', 30000);
    });

    it('keeps IME Enter local then resolves the committed chosung through the admin search', async () => {
        api.fetchAuthAPI.mockImplementation((path: string) => Promise.resolve(path.includes('/search?')
            ? { candidates: [{ symbol: '042700', name: '한미반도체', market: 'KR' }] } : stockAnalysis()));
        renderPage(''); const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        fireEvent.compositionStart(input); fireEvent.change(input, { target: { value: 'ㅎㅁㅂㄷㅊ' } });
        fireEvent.keyDown(input, { key: 'Enter', keyCode: 229, isComposing: true });
        expect(api.fetchAuthAPI).not.toHaveBeenCalled(); expect(api.postAuthAPI).not.toHaveBeenCalled();
        fireEvent.compositionEnd(input); fireEvent.submit(input.closest('form')!);
        await screen.findByRole('article', { name: /한미반도체/ });
        expect(api.fetchAuthAPI.mock.calls[0][0]).toContain('/stock-analysis/search?q=');
    });

    it('polls an async job with saved GET, suppresses retained BUY and prevents duplicate starts', async () => {
        vi.useFakeTimers(); vi.setSystemTime(new Date(analysisNow));
        const pending = deferred<ReturnType<typeof stockAnalysis>>();
        renderPage(); await act(async () => {});
        const running = stockAnalysis(); running.state = 'running'; running.result = null;
        api.postAuthAPI.mockReturnValue(pending.promise);
        fireEvent.click(screen.getByRole('button', { name: '분석 실행' }));
        fireEvent.click(screen.getByRole('button', { name: /분석 시작 중/ }));
        expect(api.postAuthAPI).toHaveBeenCalledOnce(); expect(screen.queryByText('BUY · 매수 제안')).not.toBeInTheDocument();
        await act(async () => { pending.resolve(running); });
        expect(screen.getByText('WAIT · 진입 대기')).toBeInTheDocument();
        api.fetchAuthAPI.mockResolvedValue(stockAnalysis());
        await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
        expect(screen.getByText('BUY · 매수 제안')).toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(2); expect(api.postAuthAPI).toHaveBeenCalledOnce();
    });

    it('retains references after a failed read but hides BUY until a valid retry', async () => {
        renderPage(); await screen.findByText('BUY · 매수 제안');
        api.fetchAuthAPI.mockRejectedValue(new Error('SECRET transport diagnostics'));
        await userEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        await screen.findByRole('alert');
        expect(screen.queryByText('BUY · 매수 제안')).not.toBeInTheDocument();
        expect(screen.getByText('WAIT · 진입 대기')).toBeInTheDocument(); expect(screen.getByText('92,000원')).toBeInTheDocument();
        expect(screen.queryByText(/SECRET/)).not.toBeInTheDocument();
        api.fetchAuthAPI.mockResolvedValue(stockAnalysis());
        await userEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        await screen.findByText('BUY · 매수 제안');
    });

    it('expires BUY while idle without fetching or recomputing and still shows reference values', async () => {
        vi.useFakeTimers(); vi.setSystemTime(new Date(analysisNow));
        const value = stockAnalysis(); value.result!.candidate.proposal.valid_until = '2026-10-01T10:00:02Z';
        api.fetchAuthAPI.mockResolvedValue(value); renderPage(); await act(async () => {});
        expect(screen.getByText('BUY · 매수 제안')).toBeInTheDocument();
        vi.spyOn(Date, 'now').mockImplementation(() => new Date().getTime());
        await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
        expect(screen.getByText('WAIT · 진입 대기')).toBeInTheDocument(); expect(screen.getByText('92,000원')).toBeInTheDocument();
        expect(api.fetchAuthAPI).toHaveBeenCalledOnce(); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('discards an old-symbol response after a newer selected code has finished', async () => {
        const slow = deferred<ReturnType<typeof stockAnalysis>>();
        api.fetchAuthAPI.mockImplementation((path: string) => path.endsWith('/042700') ? slow.promise : Promise.resolve(stockAnalysis('005930', '삼성전자')));
        renderPage(); const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        fireEvent.change(input, { target: { value: '005930' } }); fireEvent.submit(input.closest('form')!);
        await screen.findByRole('article', { name: /삼성전자/ });
        await act(async () => { slow.resolve(stockAnalysis()); });
        expect(screen.queryByRole('article', { name: /한미반도체/ })).not.toBeInTheDocument();
    });

    it('clears prior-account evidence immediately and ignores a response for the old token', async () => {
        const slow = deferred<ReturnType<typeof stockAnalysis>>();
        const view = renderPage(); await screen.findByRole('article', { name: /한미반도체/ });
        api.fetchAuthAPI.mockReturnValue(slow.promise); auth.token = 'other-admin';
        view.rerender(<MemoryRouter><AdminStockAnalysisPanel /></MemoryRouter>);
        expect(screen.queryByRole('article', { name: /한미반도체/ })).not.toBeInTheDocument();
        view.unmount(); await act(async () => { slow.resolve(stockAnalysis()); });
    });

    it('rejects an identity-mismatched saved response and can select a six-digit code after search fails', async () => {
        api.fetchAuthAPI.mockResolvedValue(stockAnalysis('005930', '삼성전자')); renderPage();
        await screen.findByRole('alert'); expect(screen.queryByRole('article')).not.toBeInTheDocument();
        const input = screen.getByRole('combobox', { name: '종목명 또는 코드' });
        fireEvent.change(input, { target: { value: '005930' } }); fireEvent.submit(input.closest('form')!);
        await waitFor(() => expect(screen.getByRole('article', { name: /삼성전자/ })).toBeInTheDocument());
    });

    it('stops a timed-out running poll and lets the operator recheck saved progress without a new analysis', async () => {
        vi.useFakeTimers(); vi.setSystemTime(new Date(analysisNow)); vi.spyOn(Date, 'now').mockImplementation(() => new Date().getTime());
        const value = stockAnalysis(); value.state = 'running'; api.fetchAuthAPI.mockResolvedValue(value);
        renderPage(); await act(async () => {});
        vi.setSystemTime(new Date(Date.parse(analysisNow) + 8 * 60000));
        await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
        expect(screen.getByRole('alert')).toHaveTextContent('분석이 예상보다 오래 걸립니다.');
        const count = api.fetchAuthAPI.mock.calls.length;
        await act(async () => { await vi.advanceTimersByTimeAsync(30000); });
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(count); expect(api.postAuthAPI).not.toHaveBeenCalled();
        fireEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' })); await act(async () => {});
        expect(api.fetchAuthAPI).toHaveBeenCalledTimes(count + 1); expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it.each([
        { role: 'user', token: 'pro-token', status: 'approved', loading: false },
        { role: 'user', token: 'ai-brain-token', status: 'approved', loading: false },
        { role: 'admin', token: null, status: 'approved', loading: false },
        { role: 'admin', token: 'admin-token', status: 'unknown', loading: false },
        { role: 'admin', token: 'admin-token', status: 'suspended', loading: false },
        { role: 'admin', token: 'admin-token', status: 'rejected', loading: false },
        { role: 'admin', token: 'admin-token', status: 'approved', loading: true },
    ])('never mounts private data for unresolved or non-admin auth %j', state => {
        Object.assign(auth, state); renderPage();
        expect(screen.queryByRole('heading', { name: '관리자 전용 종목 검색 분석' })).not.toBeInTheDocument();
        expect(api.fetchAuthAPI).not.toHaveBeenCalled(); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('unmounts the private result and discards a late response after an admin is downgraded', async () => {
        const slow = deferred<ReturnType<typeof stockAnalysis>>();
        const view = renderPage(); await screen.findByRole('article', { name: /한미반도체/ });
        api.fetchAuthAPI.mockReturnValue(slow.promise);
        await userEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        auth.role = 'user'; view.rerender(<MemoryRouter><AdminStockAnalysisPanel /><CurrentPath /></MemoryRouter>);
        expect(screen.queryByRole('article')).not.toBeInTheDocument();
        await act(async () => { slow.resolve(stockAnalysis()); });
        expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it.each(['suspended', 'rejected'])('immediately unmounts a private BUY and ignores a late read when admin status changes to %s', async status => {
        const slow = deferred<ReturnType<typeof stockAnalysis>>();
        const view = renderPage(); await screen.findByText('BUY · 매수 제안');
        api.fetchAuthAPI.mockReturnValue(slow.promise);
        await userEvent.click(screen.getByRole('button', { name: '저장 결과 새로고침' }));
        auth.status = status; view.rerender(<MemoryRouter><AdminStockAnalysisPanel /><CurrentPath /></MemoryRouter>);
        expect(screen.queryByRole('article')).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: '관리자 전용 종목 검색 분석' })).not.toBeInTheDocument();
        await act(async () => { slow.resolve(stockAnalysis()); });
        expect(screen.queryByRole('article')).not.toBeInTheDocument(); expect(api.postAuthAPI).not.toHaveBeenCalled();
    });

    it('uses the embedded analysis action in WAIT guidance instead of a global detection action', async () => {
        const value = stockAnalysis(); const p = value.result!.candidate.proposal;
        p.action = 'wait'; p.label = '진입 대기'; p.proposed_weight = 0;
        p.next_step = '매수 후보 검출 갱신 후 다시 확인하세요.';
        api.fetchAuthAPI.mockResolvedValue(value); renderPage();
        await screen.findByRole('article', { name: /한미반도체/ });
        expect(screen.getByText(/다음 행동 ·.*분석 실행/)).toBeInTheDocument();
        expect(screen.queryByText(/다음 행동 ·.*검출 갱신/)).not.toBeInTheDocument();
    });
});
