import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Sidebar from '@/components/layout/Sidebar';
import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import PaymentRequestPage from '@/pages/auth/PaymentRequestPage';

const mocks = vi.hoisted(() => ({
    user: null as any, logout: vi.fn(), refreshUser: vi.fn(async () => {}),
    getStatus: vi.fn(), requestUpgrade: vi.fn(),
}));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: mocks.user, token: 'member-token', loading: false,
    logout: mocks.logout, refreshUser: mocks.refreshUser }) }));
vi.mock('@/hooks/usePWAInstall', () => ({ usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: vi.fn() }) }));
vi.mock('@/lib/api', () => ({ API_BASE: 'https://api.test', subscriptionAPI: { getStatus: mocks.getStatus, requestUpgrade: mocks.requestUpgrade } }));

function Path() { const location = useLocation(); return <output aria-label="현재 경로">{location.pathname}{location.search}</output>; }
function show({ mobile = false, path = '/dashboard', onClose = vi.fn() } = {}) {
    return render(<MemoryRouter initialEntries={[path]}><Routes>
        <Route path="/dashboard" element={<Sidebar mobile={mobile} isOpen={mobile} onClose={onClose} />} />
        <Route path="/plan-select" element={<PlanSelectPage />} />
        <Route path="/payment-request" element={<PaymentRequestPage />} />
        <Route path="/pending-approval" element={<h1>신청 진행 상태</h1>} />
        <Route path="/admin" element={<h1>관리자 페이지</h1>} />
    </Routes><Path /></MemoryRouter>);
}
beforeEach(() => {
    vi.clearAllMocks();
    mocks.user = { id: 8, name: '테스트회원', email: 'member@example.test', role: 'user', tier: 'pro',
        status: 'approved', is_pro_expired: false, is_aibain_active: false, has_pending_subscription: false };
    mocks.getStatus.mockResolvedValue({ requests: [] });
});
afterEach(cleanup);

describe('profile membership upgrade entry', () => {
    it.each([false, true])('opens the existing upgrade flow and closes the mobile menu (%s)', async mobile => {
        const onClose = vi.fn(); show({ mobile, onClose });
        const grade = screen.getByRole('link', { name: '현재 등급 Pro, 등급 업그레이드' });
        expect(grade).toHaveAttribute('href', '/plan-select?change=1');
        expect(screen.getByRole('link', { name: '등급 업그레이드' })).toHaveAttribute('href', '/plan-select?change=1');
        fireEvent.click(grade);
        expect(await screen.findByRole('heading', { name: '등급 업그레이드', level: 1 })).toBeInTheDocument();
        expect(screen.getByText('현재 이용: Pro')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Pro', level: 3 }).closest('button')).toBeDisabled();
        if (mobile) expect(onClose).toHaveBeenCalledOnce();
        fireEvent.click(screen.getByRole('heading', { name: 'Ultra Pro', level: 3 }).closest('button')!);
        await waitFor(() => expect(screen.getByLabelText('현재 경로')).toHaveTextContent('/payment-request?plan=premium'));
        expect(mocks.getStatus).toHaveBeenCalledWith('member-token');
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('routes an already pending upgrade to status before another plan can be selected', async () => {
        mocks.user.has_pending_subscription = true;
        show(); fireEvent.click(screen.getByRole('link', { name: '신청 상태 확인' }));
        expect(await screen.findByText('신청 진행 상태')).toBeInTheDocument();
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('also catches a pending request when the profile cache has not received it yet', async () => {
        mocks.getStatus.mockResolvedValue({ requests: [], pending_request: { id: 9, status: 'pending' } });
        show(); fireEvent.click(screen.getByRole('link', { name: '등급 업그레이드' }));
        fireEvent.click(screen.getByRole('heading', { name: 'Ultra Pro', level: 3 }).closest('button')!);
        expect(await screen.findByText('신청 진행 상태')).toBeInTheDocument();
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('preserves the Ultra Pro base and offers its existing AI Brain add-on', () => {
        mocks.user.tier = 'premium'; show();
        fireEvent.click(screen.getByRole('link', { name: '플랜 · AI Brain 관리' }));
        expect(screen.getByText('현재 이용: Ultra Pro')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Pro', level: 3 }).closest('button')).toBeDisabled();
        expect(screen.getByRole('heading', { name: 'Ultra Pro', level: 3 }).closest('button')).toBeDisabled();
        expect(screen.getByRole('button', { name: /AI Brain 40,000원으로 추가/ })).toBeEnabled();
    });

    it('explains that an Ultra Pro member with AI Brain has no additional tier to buy', () => {
        mocks.user.tier = 'premium'; mocks.user.is_aibain_active = true; show();
        fireEvent.click(screen.getByRole('link', { name: '플랜 · AI Brain 관리' }));
        expect(screen.getByRole('heading', { name: '플랜 · AI Brain 관리', level: 1 })).toBeInTheDocument();
        expect(screen.getByText(/추가 등급 업그레이드가 필요하지 않습니다/)).toBeInTheDocument();
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('uses an explicit no-pending flag rather than a leftover cached request', () => {
        mocks.user.pending_subscription_request = { id: 9, status: 'pending' }; show();
        expect(screen.getByRole('link', { name: '등급 업그레이드' })).toHaveAttribute('href', '/plan-select?change=1');
        expect(screen.queryByRole('link', { name: '신청 상태 확인' })).not.toBeInTheDocument();
    });

    it('keeps blocked accounts outside a new payment workflow', () => {
        mocks.user.status = 'suspended'; show();
        expect(screen.getByRole('link', { name: '계정 상태 확인' })).toHaveAttribute('href', '/pending-approval');
        expect(screen.queryByRole('link', { name: '등급 업그레이드' })).not.toBeInTheDocument();
    });

    it('shows a renewal action when the actual Pro expiration has passed', () => {
        mocks.user.pro_expires_at = '2020-01-01T00:00:00'; show();
        expect(screen.getByRole('link', { name: '재구독 신청' })).toHaveAttribute('href', '/plan-select?resubscribe=1&from=expired');
    });

    it('does not describe an unsubscribed member named Admin as an administrator', () => {
        mocks.user.name = 'Admin'; mocks.user.tier = null; show();
        expect(screen.getByRole('link', { name: '현재 등급 미구독, 구독 신청' })).toHaveAttribute('href', '/plan-select');
        expect(screen.queryByRole('link', { name: '관리자 페이지' })).not.toBeInTheDocument();
    });

    it('gives real administrators a management entry without a payment workflow', () => {
        mocks.user.role = 'admin'; show();
        expect(screen.getByRole('link', { name: '현재 등급 관리자, 관리자 페이지' })).toHaveAttribute('href', '/admin');
        expect(screen.queryByRole('link', { name: '등급 업그레이드' })).not.toBeInTheDocument();
        expect(mocks.requestUpgrade).not.toHaveBeenCalled();
    });

    it('keeps sign-out independent of both subscription links', () => {
        show(); fireEvent.click(screen.getByRole('button', { name: 'Sign Out' }));
        expect(mocks.logout).toHaveBeenCalledOnce();
        expect(screen.getByLabelText('현재 경로')).toHaveTextContent('/dashboard');
    });
});
