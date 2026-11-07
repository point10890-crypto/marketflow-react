import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ControlCenterPage from '@/pages/admin/ControlCenterPage';
import { validateSnapshot, type CcSnapshot } from '@/lib/controlCenterApi';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'admin-token', user: { role: 'admin' } }) }));

const snapshot = (over: Partial<CcSnapshot> = {}): CcSnapshot => ({
    schema: 'marketflow.control_center.v1',
    generated_at: new Date().toISOString(),
    overall: 'fail',
    monitor: { status: 'ok', detail: '정상', age_seconds: 20 },
    families: {
        process: { status: 'fail', counts: { ok: 3, fail: 1, warn: 0, unknown: 0, skipped: 0 } },
        security: { status: 'ok', counts: { ok: 1, fail: 0, warn: 0, unknown: 0, skipped: 0 } },
    },
    pages: [
        { path: '/dashboard/kr/closing-bet', label: '종가베팅', critical: true, status: 'fail',
          parts: [{ kind: 'endpoint', target: '/api/kr/jongga-v2/latest', status: 'fail', detail: 'HTTP 500' }] },
        { path: '/dashboard/us', label: 'US Overview', critical: true, status: 'ok', parts: [] },
    ],
    failing: [{ check_id: 'port:flask_primary', family: 'process', target: 'Flask 운영 API', severity: 'critical', status: 'fail',
        detail: '5003 포트 응답 없음', latency_ms: 1500, last_change_at: new Date(Date.now() - 600000).toISOString(), last_observed_at: null }],
    warning: [],
    open_incidents: [{ id: 1, check_id: 'port:flask_primary', family: 'process', target: 'Flask', severity: 'critical',
        opened_at: new Date().toISOString(), resolved_at: null, last_detail: '5003 포트 응답 없음', occurrences: 3, flapping: 0 }],
    counts: { checks: 5, fail: 1, warn: 0, critical_fail: 1, open_incidents: 1 },
    ...over,
});

describe('ControlCenterPage', () => {
    beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); });

    it('shows overall status, failing pages first, failures and open incidents', async () => {
        mockApi.fetchAuthAPI.mockImplementation(async (path: string) => {
            if (path === '/api/admin/control-center/summary') return snapshot();
            if (path.startsWith('/api/admin/control-center/checks/')) return {
                check_id: 'port:flask_primary', state: null,
                history: [{ status: 'fail', latency_ms: 1, detail: 'x', observed_at: '2026-11-07T10:00:00+09:00' },
                          { status: 'ok', latency_ms: 1, detail: 'y', observed_at: '2026-11-07T09:59:00+09:00' }],
            };
            throw new Error(`unexpected ${path}`);
        });
        render(<ControlCenterPage />);
        expect(await screen.findByRole('heading', { name: /운영 관제 센터/ })).toBeInTheDocument();
        expect(mockApi.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/control-center/summary', 'admin-token', undefined, expect.any(AbortSignal));
        const pages = screen.getByRole('region', { name: '메뉴 화면 상태' });
        const items = within(pages).getAllByRole('listitem');
        expect(items[0]).toHaveTextContent('종가베팅');           // 장애 화면이 먼저
        expect(screen.getByText('1건 (치명 1)')).toBeInTheDocument();
        expect(screen.getAllByText('5003 포트 응답 없음').length).toBeGreaterThan(0);
        await userEvent.click(screen.getByRole('button', { name: /port:flask_primary/ }));
        expect(await screen.findByLabelText('최근 2회 관측')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /재시작|restart/i })).toBeNull();      // 조치 버튼 없음
    });

    it('warns loudly when the monitor itself is stale', async () => {
        mockApi.fetchAuthAPI.mockResolvedValue(snapshot({ monitor: { status: 'fail', detail: '관제 실행기가 12분째 멈춤' } }));
        render(<ControlCenterPage />);
        expect(await screen.findByText(/관제 실행기 이상: 관제 실행기가 12분째 멈춤/)).toBeInTheDocument();
    });

    it('surfaces malformed responses instead of rendering them', async () => {
        mockApi.fetchAuthAPI.mockResolvedValue({ schema: 'other' });
        render(<ControlCenterPage />);
        await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('관제 응답 형식'));
    });

    it('cancels pending history when closed and ignores its result after reopening', async () => {
        let resolveOld!: (data: unknown) => void;
        const historyCalls: AbortSignal[] = [];
        mockApi.fetchAuthAPI.mockImplementation((path: string, _token: string, _timeout: unknown, signal: AbortSignal) => {
            if (path.endsWith('/summary')) return Promise.resolve(snapshot());
            historyCalls.push(signal);
            if (historyCalls.length === 1) return new Promise(resolve => { resolveOld = resolve; });
            return Promise.resolve({ check_id: 'port:flask_primary', state: null, history: [] });
        });
        render(<ControlCenterPage />);
        const row = await screen.findByRole('button', { name: /port:flask_primary/ });
        await userEvent.click(row);
        expect(row).toHaveAttribute('aria-expanded', 'true');
        await userEvent.click(row);
        expect(historyCalls[0].aborted).toBe(true);
        await userEvent.click(row);
        expect(await screen.findByText('최근 24시간 관측 이력이 없습니다.')).toBeInTheDocument();
        await act(async () => resolveOld({
            check_id: 'port:flask_primary', state: null,
            history: [{ status: 'fail', detail: '이전 응답', observed_at: '2026-11-07T10:00:00+09:00' }],
        }));
        expect(screen.queryByLabelText('최근 1회 관측')).not.toBeInTheDocument();
    });

    it('shows a failed recent-incidents request without hiding open incidents', async () => {
        mockApi.fetchAuthAPI.mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error('사건 조회 오류'));
        render(<ControlCenterPage />);
        await userEvent.click(await screen.findByRole('button', { name: '최근 이력 보기' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('사건 조회 오류');
        expect(within(screen.getByRole('region', { name: '열린 사건 1' })).getByText('port:flask_primary')).toBeInTheDocument();
    });

    it('clearly labels retained data after a refresh error', async () => {
        mockApi.fetchAuthAPI.mockResolvedValueOnce(snapshot()).mockRejectedValueOnce(new Error('연결 실패'));
        render(<ControlCenterPage />);
        await userEvent.click(await screen.findByRole('button', { name: '관제 새로고침' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('마지막으로 받은 결과를 표시합니다.');
        expect(screen.getByText('1건 (치명 1)')).toBeInTheDocument();
    });

    it('keeps one summary request in flight and aborts it on navigation', async () => {
        vi.useFakeTimers();
        try {
            vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible');
            mockApi.fetchAuthAPI.mockImplementation(() => new Promise(() => {}));
            const { unmount } = render(<ControlCenterPage />);
            expect(screen.getByRole('status')).toHaveTextContent('관제 상태를 불러오는 중');
            const signal: AbortSignal = mockApi.fetchAuthAPI.mock.calls[0][3];
            await act(async () => {
                vi.advanceTimersByTime(60_000);
                document.dispatchEvent(new Event('visibilitychange'));
            });
            expect(mockApi.fetchAuthAPI).toHaveBeenCalledTimes(1);
            unmount();
            expect(signal.aborted).toBe(true);
            await act(async () => {
                vi.advanceTimersByTime(60_000);
                document.dispatchEvent(new Event('visibilitychange'));
            });
            expect(mockApi.fetchAuthAPI).toHaveBeenCalledTimes(1);
        } finally {
            vi.restoreAllMocks();
            vi.useRealTimers();
        }
    });

    it('shows incomplete coverage and each runner tier independently', async () => {
        mockApi.fetchAuthAPI.mockResolvedValue(snapshot({
            overall: 'unknown',
            monitor: { status: 'unknown', detail: '일부 실행 정보 없음', tiers: {
                fast: { status: 'ok', detail: '1분 전 실행' },
                standard: { status: 'unknown', detail: '아직 실행 기록 없음' },
                deep: { status: 'fail', detail: '최근 실행이 오래됨' },
            } },
            counts: { unknown: 12, skipped: 3 },
        }));
        render(<ControlCenterPage />);
        const runner = within(await screen.findByRole('region', { name: '관제 실행기' }));
        expect(runner.getByText('확인 불가 12 · 판정 안 함 3')).toBeInTheDocument();
        expect(runner.getByText('아직 실행 기록 없음')).toBeInTheDocument();
        expect(runner.getByText('최근 실행이 오래됨')).toBeInTheDocument();
    });

    it('validator rejects bad statuses', () => {
        expect(() => validateSnapshot({ ...snapshot(), overall: 'great' })).toThrow();
        expect(() => validateSnapshot({ ...snapshot(), failing: [{ check_id: 1 }] })).toThrow();
        expect(validateSnapshot(snapshot()).overall).toBe('fail');
    });
});
