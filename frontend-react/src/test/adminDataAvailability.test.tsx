import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AdminPage from '@/pages/admin/AdminPage';
import SubscriptionsTab from '@/pages/admin/tabs/SubscriptionsTab';
import PurchaseAdminPage from '@/pages/community/PurchaseAdminPage';

const mocks = vi.hoisted(() => ({
    getDashboard: vi.fn(), getSubscriptions: vi.fn(), getFunnelSummary: vi.fn(), getUsers: vi.fn(),
    getNotifications: vi.fn(), getUnreadCount: vi.fn(), fetchAuthAPI: vi.fn(),
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'test-token', user: { id: 1 } }) }));
vi.mock('@/lib/api', () => ({
    adminAPI: { ...mocks, markRead: vi.fn(), markAllRead: vi.fn() },
    fetchAuthAPI: mocks.fetchAuthAPI, putAuthAPI: vi.fn(), deleteAuthAPI: vi.fn(),
}));
vi.mock('@/pages/admin/tabs/UsersTab', () => ({ UsersTab: () => null }));
vi.mock('@/pages/admin/tabs/SystemTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/tabs/JobsTab', () => ({ default: () => null }));
vi.mock('@/pages/admin/ProExpiryTab', () => ({ default: () => null }));

const dashboard = {
    total_users: 47, pro_users: 5, premium_users: 2, no_tier_users: 39, admin_users: 1,
    pending_users: 1, approved_users: 46, suspended_users: 0, pending_subscriptions: 3,
};
const subscription = {
    id: 8, user_id: 9, user_email: 'member@example.test', user_name: '확인할회원',
    request_type: 'subscription', from_tier: 'none', to_tier: 'pro', status: 'pending',
    payment_id: null, admin_note: null, depositor_name: null, amount: '50,000원',
    created_at: '2026-11-03T01:00:00Z', processed_at: null,
};
const purchase = {
    id: 11, post_id: 12, user_id: 9, buyer_name: '확인할입금자', status: 'pending',
    user_name: '확인할구매자', post_title: '구매상품', post_price: '10000',
    created_at: '2026-11-03T01:00:00Z', approved_at: null,
};
const purchaseList = { purchases: [purchase], total: 1, page: 1, per_page: 20, total_pages: 1 };
const summary = { today: { count: 2, total: 20000 }, month: { count: 4, total: 40000 }, all: { count: 8, total: 80000 }, pending_count: 1 };
const unavailable = () => Promise.reject(new Error('HTTP 503'));
const show = (element: React.ReactElement) => render(<MemoryRouter>{element}</MemoryRouter>);

beforeEach(() => {
    vi.resetAllMocks();
    mocks.getDashboard.mockResolvedValue(dashboard);
    mocks.getUsers.mockResolvedValue({ users: [], total: 0, total_pages: 0 });
    mocks.getFunnelSummary.mockResolvedValue({ days: 30, since: '2026-10-04', counts: {}, users: { registered: 4, requested: 2, approved: 1 }, conversion: { register_to_request: 0.5, request_to_approve: 0.5, register_to_approve: 0.25 }, median_request_to_approve_hours: 1, approved_requests_sampled: 1 });
    mocks.getNotifications.mockResolvedValue({ notifications: [], total: 0, page: 1, total_pages: 1 });
    mocks.getUnreadCount.mockResolvedValue({ unread_count: 0 });
    mocks.getSubscriptions.mockResolvedValue({ requests: [subscription], pending_signups: [], expired_members: [] });
    mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary : purchaseList));
});
afterEach(cleanup);

describe('admin data availability', () => {
    it('does not declare the queue complete before dashboard data loads and retries a failed GET', async () => {
        let reject!: (reason: Error) => void;
        mocks.getDashboard.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
        show(<AdminPage />);
        expect(screen.queryByText('모두 처리 완료')).not.toBeInTheDocument();
        expect(screen.getByText(/대시보드.*불러오는 중/)).toBeInTheDocument();
        await act(async () => reject(new Error('HTTP 503')));
        expect(await screen.findByRole('alert')).toHaveTextContent(/대시보드.*불러오지 못/);
        expect(screen.queryByText('모두 처리 완료')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /대시보드.*다시 시도/ }));
        expect(await screen.findByText('47')).toBeInTheDocument();
        expect(screen.getByText('구독 승인 대기')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('retains the previous dashboard values after a failed background refresh', async () => {
        show(<AdminPage />);
        expect(await screen.findByText('47')).toBeInTheDocument();
        mocks.getDashboard.mockImplementationOnce(unavailable);
        Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' });
        fireEvent(document, new Event('visibilitychange'));
        expect(await screen.findByRole('alert')).toHaveTextContent(/이전.*표시/);
        expect(screen.getByText('47')).toBeInTheDocument();
        expect(screen.getByText('구독 승인 대기')).toBeInTheDocument();
    });

    it('rejects malformed dashboard data instead of declaring zero work', async () => {
        mocks.getDashboard.mockResolvedValueOnce({ error: 'unavailable' });
        show(<AdminPage />);
        expect(await screen.findByRole('alert')).toHaveTextContent(/대시보드/);
        expect(screen.queryByText('모두 처리 완료')).not.toBeInTheDocument();
    });

    it('shows failed subscription loading without an empty queue and retries into existing requests', async () => {
        mocks.getSubscriptions.mockImplementationOnce(unavailable);
        show(<SubscriptionsTab onCountChange={() => {}} />);
        expect(await screen.findByRole('alert')).toHaveTextContent(/구독.*불러오지 못/);
        expect(screen.queryByText('대기 중인 구독 요청이 없습니다')).not.toBeInTheDocument();
        expect(screen.queryByText(/대기 중 \(0\)/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }));
        expect(await screen.findByText('확인할회원')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('keeps subscription rows on refresh failure and clears the warning after recovery', async () => {
        show(<SubscriptionsTab onCountChange={() => {}} />);
        expect(await screen.findByText('확인할회원')).toBeInTheDocument();
        mocks.getSubscriptions.mockImplementationOnce(unavailable);
        fireEvent.click(screen.getByRole('button', { name: /새로고침/ }));
        expect(await screen.findByRole('alert')).toHaveTextContent(/이전.*표시/);
        expect(screen.getByText('확인할회원')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /다시 시도/ }));
        await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
        expect(screen.getByText('확인할회원')).toBeInTheDocument();
    });

    it('does not treat a malformed subscription response as an empty result', async () => {
        mocks.getSubscriptions.mockResolvedValueOnce({});
        show(<SubscriptionsTab onCountChange={() => {}} />);
        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(screen.queryByText('대기 중인 구독 요청이 없습니다')).not.toBeInTheDocument();
    });

    it('keeps purchase list and revenue availability visible and retries both after an outage', async () => {
        mocks.fetchAuthAPI.mockImplementation(unavailable);
        show(<PurchaseAdminPage />);
        await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0));
        expect(screen.queryByText('총 0건')).not.toBeInTheDocument();
        expect(screen.queryByText('구매 신청 내역이 없습니다.')).not.toBeInTheDocument();
        expect(screen.getByText(/매출.*불러오지 못/)).toBeInTheDocument();
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary : purchaseList));
        fireEvent.click(screen.getAllByRole('button', { name: /다시 시도/ })[0]);
        expect(await screen.findByText('총 1건')).toBeInTheDocument();
        expect(screen.getAllByText('확인할입금자').length).toBeGreaterThan(0);
        expect(screen.getByText('80,000원')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('preserves purchase rows and revenue when refresh fails, then clears both warnings', async () => {
        show(<PurchaseAdminPage />);
        expect(await screen.findByText('총 1건')).toBeInTheDocument();
        expect(screen.getByText('80,000원')).toBeInTheDocument();
        mocks.fetchAuthAPI.mockImplementation(unavailable);
        fireEvent.click(screen.getByRole('button', { name: /새로고침/ }));
        await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0));
        expect(screen.getByText('총 1건')).toBeInTheDocument();
        expect(screen.getAllByText('확인할입금자').length).toBeGreaterThan(0);
        expect(screen.getByText('80,000원')).toBeInTheDocument();
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary : purchaseList));
        fireEvent.click(screen.getAllByRole('button', { name: /다시 시도/ })[0]);
        await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    });

    it('shows a confirmed empty purchase result only after a valid response', async () => {
        mocks.fetchAuthAPI.mockImplementation((url: string) => Promise.resolve(url.includes('/summary') ? summary : { ...purchaseList, purchases: [], total: 0 }));
        show(<PurchaseAdminPage />);
        expect(await screen.findByText('구매 신청 내역이 없습니다.')).toBeInTheDocument();
        expect(screen.getByText('총 0건')).toBeInTheDocument();
    });

    it('rejects malformed purchase data and summary without displaying zero or a successful empty state', async () => {
        mocks.fetchAuthAPI.mockResolvedValue({});
        show(<PurchaseAdminPage />);
        await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
        expect(screen.queryByText('총 0건')).not.toBeInTheDocument();
        expect(screen.queryByText('구매 신청 내역이 없습니다.')).not.toBeInTheDocument();
        expect(screen.queryByText('0원')).not.toBeInTheDocument();
    });

    it('ignores an older purchase response after a different filter has finished loading', async () => {
        let resolveFirst!: (data: typeof purchaseList) => void;
        let listCalls = 0;
        mocks.fetchAuthAPI.mockImplementation((url: string) => {
            if (url.includes('/summary')) return Promise.resolve(summary);
            if (++listCalls === 1) return new Promise(resolve => { resolveFirst = resolve; });
            return Promise.resolve({ ...purchaseList, purchases: [{ ...purchase, buyer_name: '최근조회입금자', status: 'approved' }] });
        });
        show(<PurchaseAdminPage />);
        fireEvent.change(screen.getByRole('combobox'), { target: { value: 'approved' } });
        await waitFor(() => expect(screen.getAllByText('최근조회입금자').length).toBeGreaterThan(0));
        await act(async () => resolveFirst(purchaseList));
        expect(screen.queryByText('확인할입금자')).not.toBeInTheDocument();
        expect(screen.getAllByText('최근조회입금자').length).toBeGreaterThan(0);
    });

    it('does not replace unavailable funnel and notifications with zero or empty success states', async () => {
        mocks.getFunnelSummary.mockImplementationOnce(unavailable);
        mocks.getNotifications.mockImplementationOnce(unavailable);
        show(<AdminPage />);
        await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2));
        expect(screen.queryByText('알림이 없습니다')).not.toBeInTheDocument();
        expect(screen.getByText(/퍼널.*불러오지 못/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /알림.*다시 시도/ }));
        expect(await screen.findByText('알림이 없습니다')).toBeInTheDocument();
    });
});
