import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import AccountPage from '@/pages/AccountPage';
import RenewalBanner from '@/components/layout/RenewalBanner';
import { nextPathForUser } from '@/pages/auth/LoginPage';
import { subscriptionJourney } from '@/lib/subscriptionJourney';

const state = vi.hoisted(() => ({
    user: {} as Record<string, unknown>,
    refreshUser: vi.fn(async () => {}),
    getStatus: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: state.user, token: 'member-token', refreshUser: state.refreshUser, logout: vi.fn() }),
}));
vi.mock('@/lib/api', () => ({ subscriptionAPI: { getStatus: state.getStatus }, telegramAPI: {} }));
vi.mock('@/hooks/usePWAInstall', () => ({
    usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: vi.fn() }),
}));

const member = {
    id: 56, name: '신규회원', email: 'member@example.test', role: 'user',
    status: 'approved', tier: null, is_pro_expired: false,
};
const combo = {
    id: 7, request_type: 'aibain_kongming', to_tier: 'aibain_kongming',
    from_tier: 'none', status: 'pending', amount: '50,000원',
};
const activeCombo = {
    ...member, is_kongming_active: true, kongming_expires_at: '2099-01-01T00:00:00Z',
};
const expiredCombo = {
    ...member, is_kongming_active: false, kongming_expires_at: '2025-01-01T00:00:00Z',
};

function LocationProbe() {
    const location = useLocation();
    return <output>{location.pathname}{location.search}</output>;
}

function renderApproval() {
    return render(<MemoryRouter initialEntries={['/pending-approval']}>
        <Routes>
            <Route path="/pending-approval" element={<PendingApprovalPage />} />
            <Route path="*" element={<LocationProbe />} />
        </Routes>
    </MemoryRouter>);
}

describe('standalone AI Brain and Kongming membership', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        state.user = { ...member, status: 'pending', has_pending_subscription: true };
    });

    it('identifies the standalone plan and the exact amount while it is pending', async () => {
        state.getStatus.mockResolvedValue({ requests: [combo], pending_request: combo });
        renderApproval();
        expect(await screen.findByRole('heading', { name: 'AI 브레인 + 제갈공명 승인 대기 중' })).toBeInTheDocument();
        expect(screen.getByText('50,000원')).toBeInTheDocument();
    });

    it('offers the same plan after a rejected renewal', async () => {
        state.getStatus.mockResolvedValue({
            requests: [{ ...combo, request_type: 'aibain_kongming_renewal', status: 'rejected' }],
        });
        renderApproval();
        expect(await screen.findByRole('link', { name: '재구독 신청' })).toHaveAttribute(
            'href', '/payment-request?plan=aibain_kongming&resubscribe=1',
        );
    });

    it('opens AI Brain after confirmation and auth refresh for an approved standalone member', async () => {
        state.getStatus.mockResolvedValue({
            user: { ...activeCombo, has_pending_subscription: false },
            requests: [{ ...combo, status: 'approved' }],
        });
        state.refreshUser.mockImplementation(async () => {
            state.user = { ...activeCombo, has_pending_subscription: false };
        });
        renderApproval();
        await waitFor(() => expect(screen.getByText('/dashboard/ai-bain')).toBeInTheDocument());
        expect(state.refreshUser).toHaveBeenCalled();
    });

    it('lands standalone members in AI Brain and keeps the specific plan for renewal', () => {
        expect(nextPathForUser(activeCombo, null)).toBe('/dashboard/ai-bain');
        expect(nextPathForUser(activeCombo, '/dashboard/account')).toBe('/dashboard/account');
        expect(nextPathForUser(expiredCombo, null)).toBe('/plan-select?plan=aibain_kongming&resubscribe=1&from=expired');
        expect(subscriptionJourney(activeCombo)).toBeNull();
        expect(subscriptionJourney(expiredCombo)?.payment).toBe('/payment-request?plan=aibain_kongming&resubscribe=1');
    });

    it('uses the exact 50,000 won renewal on the account page and before expiry', async () => {
        state.user = { ...activeCombo, kongming_expires_at: new Date(Date.now() + 2 * 86_400_000).toISOString() };
        state.getStatus.mockResolvedValue({ requests: [] });
        render(<MemoryRouter><RenewalBanner /><AccountPage /></MemoryRouter>);
        expect(screen.getByRole('heading', { name: 'AI 브레인 + 제갈공명' })).toBeInTheDocument();
        expect(screen.getByText('50,000원 / 30일 · 계좌이체')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '제갈공명 열기' })).toHaveAttribute('href', '/dashboard/ai-bain/catalyst-validation');
        for (const label of ['갱신 신청', '30일 연장 신청']) {
            expect(screen.getByRole('link', { name: label })).toHaveAttribute('href', '/payment-request?plan=aibain_kongming&renew=1');
        }
        await waitFor(() => expect(state.getStatus).toHaveBeenCalled());
    });

    it('offers status instead of a duplicate payment for a bundle request outside recent history', async () => {
        state.user = activeCombo;
        state.getStatus.mockResolvedValue({
            requests: [],
            pending_request: { ...combo, request_type: 'aibain_kongming_renewal' },
        });
        render(<MemoryRouter><AccountPage /></MemoryRouter>);
        expect(await screen.findByRole('link', { name: '승인 상태 확인' })).toHaveAttribute('href', '/pending-approval');
        expect(screen.queryByRole('link', { name: '30일 연장 신청' })).not.toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: '계좌이체 안내' })).not.toBeInTheDocument();
    });
});
