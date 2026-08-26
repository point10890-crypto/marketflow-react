import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import SignupPage from '@/pages/auth/SignupPage';
import { nextPathForUser, safeNextPath } from '@/pages/auth/LoginPage';
import PricingPage from '@/pages/static/PricingPage';

const mocks = vi.hoisted(() => ({
    auth: {
        user: null as any,
        token: null as string | null,
        loading: false,
        setSession: vi.fn(),
        logout: vi.fn(),
    },
    fetch: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => mocks.auth,
}));

vi.mock('@/lib/api', () => ({
    API_BASE: 'https://api.test',
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

    it('restores a safely selected plan after login for no-tier, active, and expired members', () => {
        const planned = '/plan-select?change=1&plan=premium&aibain=1';

        expect(nextPathForUser({ status: 'pending', tier: null }, planned)).toBe(planned);
        expect(nextPathForUser({ status: 'approved', tier: 'pro' }, planned)).toBe(planned);
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
