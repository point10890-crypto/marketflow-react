import { render, screen, within } from '@testing-library/react';
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

    it('renders the agent-automation story, AI Brain flagship, plan source of truth, and disclosure', () => {
        mocks.auth.user = null;
        mocks.auth.loading = false;
        render(
            <MemoryRouter>
                <LandingPage />
            </MemoryRouter>,
        );

        const main = screen.getByRole('main');
        expect(within(main).getByRole('heading', { level: 1, name: /세 시장을 살피고.*종목의 근거를 찾다/ })).toBeInTheDocument();
        for (const market of ['국내주식', '미국주식', '가상자산']) {
            expect(within(main).getByRole('heading', { name: market })).toBeInTheDocument();
        }
        expect(within(main).getByRole('link', { name: 'AI 브레인 알아보기' })).toHaveAttribute('href', '#ai-brain');
        expect(within(main).getByRole('link', { name: /AI 브레인으로 시작/ })).toHaveAttribute(
            'href',
            '/signup?plan=pro&aibain=1',
        );
        expect(within(main).getByRole('heading', { name: '입금 후 신청' })).toBeInTheDocument();
        expect(within(main).getByRole('heading', { name: '승인 후 이용' })).toBeInTheDocument();
        expect(screen.getByText(/자동 주문이나 투자 자문을 수행하지 않습니다/)).toBeInTheDocument();

        for (const meta of Object.values(PLAN_PAYMENT_META).filter(meta => meta.tier !== 'aibain_kongming')) {
            const card = within(main).getByRole('article', { name: meta.label });
            expect(within(card).getByText(meta.amount)).toBeInTheDocument();
            expect(within(card).getByText(meta.period)).toBeInTheDocument();
        }
        expect(within(main).getByRole('link', { name: 'Pro + AI Brain 선택' }))
            .toHaveAttribute('href', '/signup?plan=pro&aibain=1');

        // AI Brain 애드온 단독 요금(50,000원/30일) — 기존 구독자용 노출 필수
        expect(screen.getByText('AI Brain + 제갈공명')).toBeInTheDocument();
        expect(screen.getAllByText('50,000원').length).toBeGreaterThan(0);
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

    it('pairs the active Ultra Pro offer with its add-on price and tier', () => {
        mocks.auth.user = { role: 'user', status: 'approved', tier: 'premium' };
        mocks.auth.loading = false;
        render(<MemoryRouter><LandingPage /></MemoryRouter>);

        const main = within(screen.getByRole('main'));
        expect(main.queryByRole('article', { name: /^Pro$/ })).not.toBeInTheDocument();
        const addon = within(main.getByRole('article', { name: 'AI Brain + 제갈공명' }));
        expect(addon.getByText('50,000원')).toBeInTheDocument();
        expect(addon.getByRole('link', { name: 'AI 브레인 추가·연장' }))
            .toHaveAttribute('href', '/plan-select?change=1&plan=premium&aibain=1');
    });

    it('sends a legacy active AI member straight to their existing service', () => {
        mocks.auth.user = {
            role: 'user', status: 'approved', tier: null,
            is_kongming_active: true, kongming_expires_at: new Date(Date.now() + 86400000).toISOString(),
        };
        mocks.auth.loading = false;
        render(<MemoryRouter><LandingPage /></MemoryRouter>);

        expect(screen.getByRole('link', { name: 'AI 브레인 열기' })).toHaveAttribute('href', '/dashboard/ai-bain');
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
