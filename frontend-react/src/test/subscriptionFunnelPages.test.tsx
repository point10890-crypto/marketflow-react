import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import SignupPage from '@/pages/auth/SignupPage';
import PaymentRequestPage from '@/pages/auth/PaymentRequestPage';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import { nextPathForUser, safeNextPath } from '@/pages/auth/LoginPage';
import PricingPage from '@/pages/static/PricingPage';

const mocks = vi.hoisted(() => ({
    auth: {
        user: null as any,
        token: null as string | null,
        loading: false,
        setSession: vi.fn(),
        logout: vi.fn(),
        refreshUser: vi.fn(async () => {}),
    },
    fetch: vi.fn(),
    getStatus: vi.fn(async () => ({ requests: [] as any[] })),
    requestUpgrade: vi.fn(async () => ({})),
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => mocks.auth,
}));

vi.mock('@/lib/api', () => ({
    API_BASE: 'https://api.test',
    subscriptionAPI: {
        getStatus: mocks.getStatus,
        requestUpgrade: mocks.requestUpgrade,
    },
}));

function LocationProbe() {
    const location = useLocation();
    return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function renderAt(path: string, page: React.ReactElement, route: string) {
    return render(
        <MemoryRouter initialEntries={[path]}>
            <Routes>
                <Route path={route} element={page} />
                <Route path="*" element={<LocationProbe />} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('subscription acquisition funnel', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mocks.auth.user = null;
        mocks.auth.token = null;
        mocks.auth.loading = false;
        mocks.getStatus.mockResolvedValue({ requests: [] });
        mocks.requestUpgrade.mockResolvedValue({});
        vi.stubGlobal('fetch', mocks.fetch);
    });

    it('renders four promotional plans and sends a guest to signup with the canonical plan query', async () => {
        renderAt('/pricing', <PricingPage />, '/pricing');

        expect(screen.getByRole('heading', { name: 'Pro' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Pro + AI Brain' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Ultra Pro' })).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Ultra Pro + AI Brain' })).toBeInTheDocument();
        expect(screen.queryByText('국민은행')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /^Pro \+ AI Brain 선택하기/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/signup?plan=pro&aibain=1');
        expect(mocks.fetch).not.toHaveBeenCalled();
    });

    it('sends a signed-in visitor to change mode without submitting a subscription', async () => {
        mocks.auth.user = {
            id: 11,
            email: 'member@example.test',
            name: '회원',
            role: 'user',
            status: 'approved',
            tier: 'pro',
        };
        mocks.auth.token = 'member-token';

        renderAt('/pricing', <PricingPage />, '/pricing');
        fireEvent.click(screen.getByRole('button', { name: /Ultra Pro \+ AI Brain 선택 계속하기/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?change=1&plan=premium&aibain=1');
        expect(mocks.fetch).not.toHaveBeenCalled();
    });

    it('preserves the chosen plan through account creation and records the base requested tier', async () => {
        mocks.fetch.mockResolvedValue({
            ok: true,
            json: async () => ({
                token: 'new-token',
                user: {
                    id: 21,
                    email: 'new@example.test',
                    name: '신규회원',
                    role: 'user',
                    status: 'pending',
                    tier: null,
                },
            }),
        } as Response);

        renderAt('/signup?plan=pro&aibain=1', <SignupPage />, '/signup');
        expect(screen.getByText('Pro + AI Brain', { selector: 'div' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute(
            'href',
            '/login?next=%2Fplan-select%3Fchange%3D1%26plan%3Dpro%26aibain%3D1',
        );

        fireEvent.change(screen.getByLabelText('이름'), { target: { value: '신규회원' } });
        fireEvent.change(screen.getByLabelText('이메일'), { target: { value: 'new@example.test' } });
        fireEvent.change(screen.getByLabelText('비밀번호'), { target: { value: 'Pass1234!' } });
        fireEvent.click(screen.getByRole('button', { name: /계정 만들고 플랜 확인/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?plan=pro&aibain=1');
        expect(mocks.auth.setSession).toHaveBeenCalledWith('new-token', expect.objectContaining({ id: 21 }), true);
        const request = mocks.fetch.mock.calls[0][1] as RequestInit;
        expect(JSON.parse(String(request.body))).toEqual({
            name: '신규회원',
            email: 'new@example.test',
            password: 'Pass1234!',
            requested_tier: 'pro',
        });
    });

    it('preserves a preferred plan when an existing no-tier member visits signup', async () => {
        mocks.auth.user = {
            id: 31,
            email: 'pending@example.test',
            name: '대기회원',
            role: 'user',
            status: 'pending',
            tier: null,
        };
        mocks.auth.token = 'pending-token';

        renderAt('/signup?plan=premium&aibain=1', <SignupPage />, '/signup');

        expect(await screen.findByTestId('location')).toHaveTextContent('/plan-select?plan=premium&aibain=1');
    });

    it('marks the preferred plan and keeps the lifetime base period honest', async () => {
        mocks.auth.user = {
            id: 41,
            email: 'pending@example.test',
            name: '대기회원',
            role: 'user',
            status: 'pending',
            tier: null,
            is_pro_expired: false,
        };
        mocks.auth.token = 'pending-token';

        renderAt('/plan-select?plan=premium&aibain=1', <PlanSelectPage />, '/plan-select');

        const preferred = screen.getByRole('button', { name: /Ultra Pro \+ AI Brain/ });
        expect(preferred).toHaveAttribute('aria-pressed', 'true');
        expect(within(preferred).getAllByText('Ultra Pro 평생 + AI Brain 30일 갱신').length).toBeGreaterThan(0);
        expect(within(preferred).queryByText('원 / 30일')).not.toBeInTheDocument();

        fireEvent.click(preferred);
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=premium&aibain=1');
    });

    it('shows an active Pro member the actual 40,000 won AI Brain add-on amount', async () => {
        mocks.auth.user = {
            id: 51,
            email: 'active-pro@example.test',
            name: '활성회원',
            role: 'user',
            status: 'approved',
            tier: 'pro',
            is_pro_expired: false,
            is_aibain_active: false,
        };
        mocks.auth.token = 'active-token';

        renderAt('/plan-select?change=1&plan=pro&aibain=1', <PlanSelectPage />, '/plan-select');

        const addon = screen.getByRole('button', { name: /AI Brain 애드온/ });
        expect(within(addon).getByText('40,000')).toBeInTheDocument();
        expect(within(addon).queryByText('90,000')).not.toBeInTheDocument();
        expect(within(addon).getByText('AI Brain 40,000원으로 추가')).toBeInTheDocument();

        const currentPro = screen.getByRole('heading', { name: 'Pro' }).closest('button');
        expect(currentPro).toBeDisabled();

        fireEvent.click(addon);
        expect(await screen.findByTestId('location')).toHaveTextContent('/payment-request?plan=pro&aibain=1');
    });

    it('blocks an active Ultra Pro downgrade and prices its AI Brain add-on separately', () => {
        mocks.auth.user = {
            id: 61,
            email: 'active-ultra@example.test',
            name: '울트라회원',
            role: 'user',
            status: 'approved',
            tier: 'premium',
            is_pro_expired: false,
            is_aibain_active: false,
        };
        mocks.auth.token = 'ultra-token';

        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');

        const proCard = screen.getByRole('heading', { name: 'Pro' }).closest('button');
        const ultraCard = screen.getByRole('heading', { name: 'Ultra Pro' }).closest('button');
        const addon = screen.getByRole('button', { name: /AI Brain 애드온/ });

        expect(proCard).toBeDisabled();
        expect(proCard).toHaveTextContent('Ultra Pro에서는 하향 변경 불가');
        expect(ultraCard).toBeDisabled();
        expect(within(addon).getByText('40,000')).toBeInTheDocument();
        expect(addon).toBeEnabled();
    });

    it("hides the dead '처음으로' escape for funneled members but keeps it in change mode", () => {
        // 노티어 회원: / 는 FunnelGate 가 곧장 /plan-select 로 되돌리므로 버튼 숨김 (로그아웃만 남음)
        mocks.auth.user = {
            id: 71, email: 'parked@example.test', name: '대기', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'parked-token';
        const { unmount } = renderAt('/plan-select', <PlanSelectPage />, '/plan-select');
        expect(screen.queryByRole('button', { name: /처음으로/ })).toBeNull();
        expect(screen.getByRole('button', { name: /로그아웃/ })).toBeInTheDocument();
        unmount();

        // 활성 구독자(change=1): FunnelGate 통과 대상이므로 랜딩 이동 버튼 유지
        mocks.auth.user = {
            id: 72, email: 'active@example.test', name: '활성', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: false,
        };
        mocks.auth.token = 'active-token';
        renderAt('/plan-select?change=1', <PlanSelectPage />, '/plan-select');
        expect(screen.getByRole('button', { name: /처음으로/ })).toBeInTheDocument();
    });

    it('refreshes auth state on mount and window focus so an admin tier grant unparks the user', () => {
        mocks.auth.user = {
            id: 81, email: 'granted@example.test', name: '부여대상', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'granted-token';
        const { unmount } = renderAt('/plan-select', <PlanSelectPage />, '/plan-select');
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(1);
        fireEvent(window, new Event('focus'));
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(2);
        unmount();

        mocks.auth.refreshUser.mockClear();
        renderAt('/payment-request?plan=pro', <PaymentRequestPage />, '/payment-request');
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(1);
        fireEvent(window, new Event('focus'));
        expect(mocks.auth.refreshUser).toHaveBeenCalledTimes(2);
    });

    it("maps the stale 'Already on ... tier' 400 to a refresh + dashboard instead of a dead-end error", async () => {
        mocks.auth.user = {
            id: 82, email: 'granted@example.test', name: '부여됨', role: 'user', status: 'pending', tier: null,
        };
        mocks.auth.token = 'granted-token';
        mocks.requestUpgrade.mockRejectedValue(new Error('Already on pro tier'));

        renderAt('/payment-request?plan=pro', <PaymentRequestPage />, '/payment-request');
        fireEvent.click(screen.getByRole('button', { name: /승인 신청/ }));

        expect(await screen.findByTestId('location')).toHaveTextContent('/dashboard');
        expect(mocks.auth.refreshUser).toHaveBeenCalled();
    });

    it('treats an expired-Pro renewal wait as pending, not an active upgrade', async () => {
        mocks.auth.user = {
            id: 91, email: 'expired@example.test', name: '만료회원', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: true,
        };
        mocks.auth.token = 'expired-token';
        mocks.getStatus.mockResolvedValue({
            requests: [{
                id: 1, status: 'pending', from_tier: 'pro', to_tier: 'pro',
                request_type: 'renewal', amount: '110,000원', depositor_name: '만료회원',
            }],
        });

        renderAt('/pending-approval', <PendingApprovalPage />, '/pending-approval');

        expect(await screen.findByRole('heading', { name: '승인 대기 중' })).toBeInTheDocument();
        expect(screen.queryByText('업그레이드 대기 중')).toBeNull();
        // 만료 재구독자는 대시보드 버튼(ApprovedGuard 가 다시 plan-select 로 튕김) 대신 로그아웃 노출
        expect(screen.queryByRole('button', { name: /대시보드로 돌아가기/ })).toBeNull();
        expect(screen.getByRole('button', { name: '로그아웃' })).toBeInTheDocument();
        expect(screen.getByText('110,000원')).toBeInTheDocument();
    });

    it('restores a safely selected plan after login for no-tier, active, and expired members', () => {
        const planned = '/plan-select?change=1&plan=premium&aibain=1';

        expect(nextPathForUser({ status: 'pending', tier: null }, planned)).toBe(planned);
        expect(nextPathForUser({ status: 'approved', tier: 'pro' }, planned)).toBe(planned);
        // 구독 신청 제출(requested_tier 기록) 회원은 재입금 안내 대신 승인 대기로
        expect(nextPathForUser({ status: 'pending', tier: null, requested_tier: 'pro' }, null))
            .toBe('/pending-approval');
        expect(nextPathForUser({ status: 'pending', tier: null }, null)).toBe('/plan-select');
        expect(nextPathForUser({ status: 'expired', tier: 'pro', is_pro_expired: true }, planned)).toBe(
            '/plan-select?plan=premium&aibain=1&resubscribe=1&from=expired',
        );
        expect(safeNextPath('https://evil.example/plan-select')).toBeNull();
        expect(safeNextPath('//evil.example/plan-select')).toBeNull();
    });

    it('keeps promotional pricing mutation-free and auth pages on document scrolling', () => {
        const src = resolve(__dirname, '..');
        const pricing = readFileSync(resolve(src, 'pages/static/PricingPage.tsx'), 'utf8');
        const signup = readFileSync(resolve(src, 'pages/auth/SignupPage.tsx'), 'utf8');
        const planSelect = readFileSync(resolve(src, 'pages/auth/PlanSelectPage.tsx'), 'utf8');

        expect(pricing).toContain('PLAN_PAYMENT_META');
        expect(pricing).toContain('planToQuery');
        expect(pricing).not.toMatch(/subscriptionAPI|requestUpgrade|BANK_ACCOUNT/);
        expect(signup).toContain('min-h-[100dvh]');
        expect(planSelect).toContain('min-h-[100dvh]');
        expect(planSelect).not.toContain('fixed inset-0');
    });
});
