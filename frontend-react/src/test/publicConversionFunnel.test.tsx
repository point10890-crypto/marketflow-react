import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import LandingPage from '@/pages/LandingPage';
import {
    PublicShell,
    getPublicAccountAction,
} from '@/components/public/PublicShell';
import { PLAN_PAYMENT_META } from '@/lib/billingInfo';

const mocks = vi.hoisted(() => ({
    auth: {
        user: null as any,
        loading: false,
    },
    install: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => mocks.auth,
}));

vi.mock('@/hooks/usePWAInstall', () => ({
    usePWAInstall: () => ({
        canInstall: false,
        isInstalled: true,
        isIOS: false,
        install: mocks.install,
    }),
}));

describe('public conversion funnel', () => {
    it('maps every account state to a safe existing route', () => {
        expect(getPublicAccountAction(null)).toMatchObject({ to: '/signup', label: '무료 계정 만들기' });
        expect(getPublicAccountAction(null, true)).toMatchObject({ disabled: true, label: '계정 확인 중' });
        expect(getPublicAccountAction({ status: 'unknown' })).toMatchObject({ disabled: true });
        expect(getPublicAccountAction({ role: 'admin', status: 'approved' })).toMatchObject({ to: '/admin', label: '관리 콘솔' });
        expect(getPublicAccountAction({ status: 'expired', tier: 'pro' })).toMatchObject({
            to: '/plan-select?resubscribe=1&from=expired',
            label: '재구독',
        });
        expect(getPublicAccountAction({ status: 'pending', tier: null, requested_tier: 'pro' })).toMatchObject({
            to: '/pending-approval',
            label: '승인 상태',
        });
        expect(getPublicAccountAction({ status: 'pending', tier: null })).toMatchObject({
            to: '/plan-select',
            label: '플랜 선택',
        });
        expect(getPublicAccountAction({ status: 'approved', tier: 'pro' })).toMatchObject({
            to: '/dashboard',
            label: '대시보드',
        });
        expect(getPublicAccountAction({ status: 'approved', tier: 'premium' })).toMatchObject({
            to: '/dashboard',
            label: '대시보드',
        });
    });

    it('provides a skip link, one main landmark, and truthful anonymous actions', () => {
        mocks.auth.user = null;
        mocks.auth.loading = false;
        render(
            <MemoryRouter>
                <PublicShell section="test"><p>공개 본문</p></PublicShell>
            </MemoryRouter>,
        );

        expect(screen.getByRole('link', { name: '본문으로 건너뛰기' })).toHaveAttribute('href', '#main-content');
        expect(screen.getByRole('main')).toHaveAttribute('id', 'main-content');
        expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute('href', '/login');
        expect(screen.getByRole('link', { name: '무료 계정 만들기' })).toHaveAttribute('href', '/signup');
    });

    it('renders the Claw evidence-first story, plan source of truth, and disclosure', () => {
        mocks.auth.user = null;
        mocks.auth.loading = false;
        render(
            <MemoryRouter>
                <LandingPage />
            </MemoryRouter>,
        );

        expect(screen.getByRole('heading', { name: /시장을 계속 관찰하고/ })).toBeInTheDocument();
        expect(screen.getByText('화면 예시 · 실제 종목 아님')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: /작동 방식 보기/ })).toHaveAttribute('href', '#how-it-works');
        expect(screen.getByText('불확실하면 HOLD')).toBeInTheDocument();
        expect(screen.getByText(/자동 주문이나 투자 자문을 수행하지 않습니다/)).toBeInTheDocument();

        for (const meta of Object.values(PLAN_PAYMENT_META)) {
            expect(screen.getByText(meta.label)).toBeInTheDocument();
            expect(screen.getByText(meta.amount)).toBeInTheDocument();
            expect(screen.getByText(meta.period)).toBeInTheDocument();
        }
    });

    it('labels the active-member pricing action as a plan change instead of a dashboard link', () => {
        mocks.auth.user = { role: 'user', status: 'approved', tier: 'pro' };
        mocks.auth.loading = false;
        render(
            <MemoryRouter>
                <LandingPage />
            </MemoryRouter>,
        );

        expect(screen.getByRole('link', { name: /플랜 변경 · AI Brain 추가/ })).toHaveAttribute(
            'href',
            '/plan-select?change=1',
        );
    });

    it('keeps legacy hype, ads, and nested landing scrollers out of the page', () => {
        const source = readFileSync(resolve(__dirname, '../pages/LandingPage.tsx'), 'utf-8');
        expect(source).not.toMatch(/마크 미너비니|Mark Minervini|33,500%|220%|정확한 매수|최적의 진입|24시간|\bBUY\b/);
        expect(source).not.toContain('AdSlot');
        expect(source).not.toContain('landing-root');
        expect(source).not.toContain('fixed inset-0');
        expect(source).not.toContain('overflow-y-auto');
    });
});
