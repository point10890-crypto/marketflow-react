/**
 * RenewalBanner — Pro 만료 임박(D-7) 갱신 배너.
 * AI Brain 활성으로 Pro 카운터가 일시정지(is_pro_paused)된 구독자는 pro_expires_at 이
 * 동결값이므로 가짜 "Pro 만료 임박" 경고를 절대 보지 않아야 한다.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import RenewalBanner from '@/components/layout/RenewalBanner';

const authState = vi.hoisted(() => ({
    user: null as Record<string, unknown> | null,
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: authState.user }),
}));

function isoDaysFromNow(days: number): string {
    return new Date(Date.now() + days * 86_400_000).toISOString();
}

const proExpiringSoon = {
    id: 1,
    email: 'pro@example.test',
    name: 'Pro',
    role: 'user',
    status: 'approved',
    tier: 'pro',
    is_pro_expired: false,
    is_pro_paused: false,
    pro_expires_at: isoDaysFromNow(3),
};

function renderBanner() {
    return render(
        <MemoryRouter>
            <RenewalBanner />
        </MemoryRouter>,
    );
}

describe('RenewalBanner', () => {
    beforeEach(() => {
        sessionStorage.clear();
        authState.user = null;
    });

    it('shows the renewal banner for an active Pro within D-7', () => {
        authState.user = proExpiringSoon;
        renderBanner();
        expect(screen.getByRole('status')).toHaveTextContent('Pro 이용 기간이 3일 뒤 만료됩니다.');
    });

    it('CTA links straight to the renewal payment page (plan-select current card is disabled)', () => {
        authState.user = proExpiringSoon;
        renderBanner();
        const cta = screen.getByRole('link', { name: /갱신 신청/ });
        expect(cta).toHaveAttribute('href', '/payment-request?plan=pro&renew=1');
    });

    it('hides the Pro-expiry banner while the Pro clock is paused by an active AI Brain add-on', () => {
        authState.user = {
            ...proExpiringSoon,
            is_pro_paused: true,
            pro_paused_at: isoDaysFromNow(-1),
        };
        renderBanner();
        expect(screen.queryByRole('status')).toBeNull();
    });

    it('still shows the AI Brain add-on renewal banner for a paused-Pro subscriber near add-on expiry', () => {
        authState.user = {
            ...proExpiringSoon,
            is_pro_paused: true,
            pro_paused_at: isoDaysFromNow(-1),
            is_aibain_active: true,
            aibain_expires_at: isoDaysFromNow(2),
        };
        renderBanner();
        expect(screen.getByRole('status')).toHaveTextContent('AI Brain 애드온이 2일 뒤 만료됩니다.');
    });
});
