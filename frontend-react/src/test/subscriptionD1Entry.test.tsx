import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SubscriptionEntry from '@/components/subscription/SubscriptionEntry';
import RenewalBanner from '@/components/layout/RenewalBanner';

const m = vi.hoisted(() => ({ auth: { user: null as any, token: 'member', loading: false, refreshUser: vi.fn().mockResolvedValue(undefined) }, status: vi.fn() }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => m.auth }));
vi.mock('@/lib/api', () => ({ subscriptionAPI: { getStatus: m.status } }));
const now = Date.parse('2026-11-11T00:00:00Z');
const member = { id: 7, name: '회원', role: 'user', status: 'approved', tier: 'pro', pro_expires_at: '2026-11-12T00:00:00', is_pro_expired: false };
beforeEach(() => {
    vi.clearAllMocks(); sessionStorage.clear(); vi.spyOn(Date, 'now').mockReturnValue(now);
    m.auth.user = { ...member }; m.auth.token = 'member';
    m.status.mockResolvedValue({ user: member, requests: [] });
});
afterEach(() => vi.restoreAllMocks());
function show(path = '/dashboard') {
    return render(<MemoryRouter initialEntries={[path]}><SubscriptionEntry /><Routes>
        <Route path="/dashboard" element={<><RenewalBanner /><h1>이용 중인 화면</h1></>} />
        <Route path="/payment-request" element={<h1>재구독 입금 안내</h1>} />
    </Routes></MemoryRouter>);
}
describe('D-1 in-app alert and renewal popup', () => {
    it('shows one alert, exact Korean expiry time, amount and direct early-renewal CTA without blocking access', async () => {
        show(); await act(async () => {});
        const popup = screen.getByRole('dialog');
        expect(screen.getAllByRole('alert')).toHaveLength(1);
        expect(screen.getByRole('heading', { name: '이용 중인 화면' })).toBeInTheDocument();
        expect(popup).toHaveTextContent('50,000원');
        expect(popup).toHaveTextContent('09:00');
        expect(popup.querySelector('time')).toHaveAttribute('datetime', '2026-11-12T00:00:00.000Z');
        fireEvent.click(within(popup).getByRole('link', { name: /재구독 신청/ }));
        expect(screen.getByRole('heading', { name: '재구독 입금 안내' })).toBeInTheDocument();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    it('keeps the notice after dismissal and only reopens after 30 minutes and a fresh status lookup', async () => {
        show(); await act(async () => {});
        fireEvent.click(screen.getByRole('button', { name: '나중에 보기' }));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.getByRole('alert')).toBeInTheDocument();
        vi.mocked(Date.now).mockReturnValue(now + 29 * 60_000);
        await act(async () => window.dispatchEvent(new Event('focus')));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        vi.mocked(Date.now).mockReturnValue(now + 30 * 60_000);
        await act(async () => window.dispatchEvent(new Event('focus')));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    it('shows approval status without another payment popup for a pending renewal', async () => {
        m.status.mockResolvedValue({ user: member, requests: [], pending_request: { id: 8, status: 'pending' } });
        show(); await act(async () => {});
        expect(screen.getByRole('link', { name: '신청 상태 확인' })).toHaveAttribute('href', '/pending-approval');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
    it.each(['2026-12-12T00:00:00Z', '2026-11-11T23:00:00Z'])('does not show a cached expiry when the server confirms %s', async pro_expires_at => {
        m.status.mockResolvedValue({ user: { ...member, pro_expires_at }, requests: [] });
        show(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(m.auth.refreshUser).toHaveBeenCalled();
    });
    it('does not offer payment on a status failure', async () => {
        m.status.mockRejectedValue(new Error('offline')); show(); await act(async () => {});
        expect(screen.getByRole('button', { name: '다시 확인' })).toBeInTheDocument();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    it.each([{ tier: 'premium' }, { status: 'expired', is_pro_expired: true }])('refreshes the offer when server membership changes without changing expiry: %j', async change => {
        m.auth.user = { ...member, is_pro_paused: true, is_aibain_active: true, aibain_expires_at: member.pro_expires_at,
            is_kongming_active: true, kongming_expires_at: member.pro_expires_at };
        m.status.mockResolvedValue({ user: { ...m.auth.user, ...change }, requests: [] });
        show(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
        expect(m.auth.refreshUser).toHaveBeenCalled();
    });
    it('enters the D-1 window while the app is open', async () => {
        vi.mocked(Date.now).mockReturnValue(now - 1); show(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        vi.mocked(Date.now).mockReturnValue(now);
        await act(async () => window.dispatchEvent(new Event('focus')));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
    });
    it('closes the previous account reminder immediately on account switch', async () => {
        const view = show(); await act(async () => {}); expect(screen.getByRole('dialog')).toBeInTheDocument();
        m.auth.user = { ...member, id: 9 }; m.auth.token = 'another';
        m.status.mockReturnValue(new Promise(() => {}));
        view.rerender(<MemoryRouter><SubscriptionEntry /></MemoryRouter>);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
});
