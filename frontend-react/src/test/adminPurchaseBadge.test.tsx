import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AdminPage from '@/pages/admin/AdminPage';

const mocks = vi.hoisted(() => ({
    token: 'admin-token', getDashboard: vi.fn(), fetchAuthAPI: vi.fn(), putAuthAPI: vi.fn(), deleteAuthAPI: vi.fn(),
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: mocks.token, user: { id: 1 } }) }));
vi.mock('@/lib/api', () => ({
    adminAPI: { getDashboard: mocks.getDashboard }, fetchAuthAPI: mocks.fetchAuthAPI,
    putAuthAPI: mocks.putAuthAPI, deleteAuthAPI: mocks.deleteAuthAPI,
}));
vi.mock('@/pages/admin/tabs/DashboardTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/tabs/UsersTab', () => ({ UsersTab: () => null }));
vi.mock('@/pages/admin/tabs/SubscriptionsTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/tabs/SystemTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/tabs/JobsTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/ProExpiryTab', () => ({ default: () => null }));

const summary = (pending_count: number) => ({
    today: { count: 0, total: 0 }, month: { count: 0, total: 0 }, all: { count: 0, total: 0 }, pending_count,
});
const item = { id: 11, post_id: 12, user_id: 9, buyer_name: '테스트 입금자', status: 'pending',
    user_name: '테스트 구매자', post_title: '테스트 상품', post_price: '10000',
    created_at: '2026-11-05T01:00:00Z', approved_at: null };
const list = { purchases: [item], total: 45, page: 1, per_page: 10, total_pages: 5 };
const badge = () => screen.getByRole('status', { name: /구매 승인 대기/ });
const show = () => render(<MemoryRouter><AdminPage /></MemoryRouter>);

beforeEach(() => {
    vi.resetAllMocks(); mocks.token = 'admin-token';
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
    mocks.getDashboard.mockResolvedValue({ total_users: 47, pro_users: 5, premium_users: 2, no_tier_users: 39,
        admin_users: 1, pending_users: 1, approved_users: 46, suspended_users: 0, pending_subscriptions: 6 });
    mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary(23) : list));
    mocks.putAuthAPI.mockResolvedValue({ ...item, status: 'approved' });
    mocks.deleteAuthAPI.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('administrator purchase pending badge', () => {
    it('shows the global pending total before opening purchases, independently of page size and filters', async () => {
        show();
        await waitFor(() => expect(badge()).toHaveTextContent('23'));
        expect(mocks.fetchAuthAPI).toHaveBeenCalledWith('/api/community/purchases/summary', 'admin-token');
        fireEvent.click(screen.getByRole('button', { name: /^구매/ }));
        await screen.findByText('총 45건');
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'approved' } });
        await waitFor(() => expect(mocks.fetchAuthAPI).toHaveBeenCalledWith(expect.stringContaining('status=approved')));
        expect(badge()).toHaveTextContent('23');
    });

    it('distinguishes loading, failed lookup and confirmed zero', async () => {
        let reject!: (error: Error) => void;
        mocks.fetchAuthAPI.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
        show();
        expect(badge()).not.toHaveTextContent('0');
        await act(async () => reject(new Error('HTTP 503')));
        expect(badge()).toHaveAccessibleName(/확인 실패/);
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary(0) : list));
        fireEvent.click(screen.getByRole('button', { name: /^구매/ }));
        await waitFor(() => expect(badge()).toHaveTextContent('0'));
        expect(badge()).toHaveAccessibleName('구매 승인 대기 0건');
    });

    it('retains the confirmed count on failed refresh and refreshes when the browser regains focus', async () => {
        show();
        await waitFor(() => expect(badge()).toHaveTextContent('23'));
        mocks.fetchAuthAPI.mockRejectedValueOnce(new Error('HTTP 503'));
        fireEvent(window, new Event('focus'));
        await waitFor(() => expect(badge()).toHaveAccessibleName(/갱신 실패/));
        expect(badge()).toHaveTextContent('23');
        mocks.fetchAuthAPI.mockResolvedValueOnce(summary(7));
        fireEvent(document, new Event('visibilitychange'));
        await waitFor(() => expect(badge()).toHaveTextContent('7'));
    });

    it('updates after successful approval and ignores an earlier polling response', async () => {
        show();
        await waitFor(() => expect(badge()).toHaveTextContent('23'));
        fireEvent.click(screen.getByRole('button', { name: /^구매/ }));
        await screen.findByText('총 45건');
        let resolveOld!: (value: ReturnType<typeof summary>) => void;
        mocks.fetchAuthAPI.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
        fireEvent(window, new Event('focus'));
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary(22) : list));
        fireEvent.click(screen.getAllByRole('button', { name: /^승인$/ })[0]);
        await waitFor(() => expect(badge()).toHaveTextContent('22'));
        await act(async () => resolveOld(summary(23)));
        expect(badge()).toHaveTextContent('22');
    });

    it('does not change the count after a failed approval', async () => {
        vi.spyOn(window, 'alert').mockImplementation(() => {});
        show(); await waitFor(() => expect(badge()).toHaveTextContent('23'));
        fireEvent.click(screen.getByRole('button', { name: /^구매/ }));
        await screen.findByText('총 45건');
        mocks.putAuthAPI.mockRejectedValueOnce(new Error('HTTP 503'));
        fireEvent.click(screen.getAllByRole('button', { name: /^승인$/ })[0]);
        await waitFor(() => expect(window.alert).toHaveBeenCalled());
        expect(badge()).toHaveTextContent('23');
        vi.mocked(window.alert).mockRestore();
    });

    it('refreshes the global count after a confirmed deletion', async () => {
        vi.spyOn(window, 'confirm').mockReturnValue(true);
        show(); await waitFor(() => expect(badge()).toHaveTextContent('23'));
        fireEvent.click(screen.getByRole('button', { name: /^구매/ }));
        await screen.findByText('총 45건');
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary(22) : list));
        fireEvent.click(screen.getAllByRole('button', { name: /^삭제$/ })[0]);
        await waitFor(() => expect(badge()).toHaveTextContent('22'));
        expect(mocks.deleteAuthAPI).toHaveBeenCalledWith('/api/community/purchases/11');
        vi.mocked(window.confirm).mockRestore();
    });

    it('polls every minute while visible and stops polling while hidden', async () => {
        vi.useFakeTimers();
        show(); await act(async () => {});
        expect(badge()).toHaveTextContent('23');
        mocks.fetchAuthAPI.mockResolvedValueOnce(summary(8));
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(badge()).toHaveTextContent('8');
        const calls = mocks.fetchAuthAPI.mock.calls.length;
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(mocks.fetchAuthAPI).toHaveBeenCalledTimes(calls);
    });

    it('discards a response from the previous administrator session', async () => {
        let resolveOld!: (value: ReturnType<typeof summary>) => void;
        mocks.fetchAuthAPI.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
        const view = show();
        mocks.token = 'second-admin-token';
        mocks.fetchAuthAPI.mockResolvedValueOnce(summary(4));
        view.rerender(<MemoryRouter><AdminPage /></MemoryRouter>);
        await waitFor(() => expect(badge()).toHaveTextContent('4'));
        await act(async () => resolveOld(summary(99)));
        expect(badge()).toHaveTextContent('4');
    });
});
