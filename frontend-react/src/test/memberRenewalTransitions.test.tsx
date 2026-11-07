import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SubscriptionEntry from '@/components/subscription/SubscriptionEntry';
import PendingApprovalPage from '@/pages/auth/PendingApprovalPage';
import PlanSelectPage from '@/pages/auth/PlanSelectPage';
import { subscriptionFunnelTarget } from '@/lib/auth';
import { subscriptionJourney } from '@/lib/subscriptionJourney';

const m = vi.hoisted(() => ({ auth: { user: null as any, token: 'member-token' as string | null, loading: false,
    refreshUser: vi.fn(async () => {}), logout: vi.fn() }, status: vi.fn() }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => m.auth }));
vi.mock('@/lib/api', () => ({ subscriptionAPI: { getStatus: m.status } }));
const now = Date.parse('2026-11-05T00:00:00Z');
const base = { id: 1, name: '테스트회원', email: 'member@example.test', role: 'user', status: 'approved',
    tier: 'pro', is_pro_expired: false, has_pending_subscription: false };
const expired = { ...base, status: 'expired', is_pro_expired: true, pro_expires_at: '2026-11-04T00:00:00Z' };
const ready = { requests: [], pending_request: null, user: { has_pending_subscription: false } };
const showEntry = () => render(<MemoryRouter initialEntries={['/community']}><SubscriptionEntry /></MemoryRouter>);
beforeEach(() => { vi.clearAllMocks(); m.status.mockReset(); sessionStorage.clear(); localStorage.clear(); m.auth.user = { ...base };
    m.auth.token = 'member-token'; m.auth.loading = false; m.status.mockResolvedValue(ready); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.restoreAllMocks(); });

describe('member renewal state transitions', () => {
    it('derives Pro expiry at the actual timestamp even when cached flags still say active', () => {
        vi.spyOn(Date, 'now').mockReturnValue(now);
        const user = { ...base, pro_expires_at: '2026-11-05T00:00:00' };
        expect(subscriptionFunnelTarget(user)).toBe('/plan-select?resubscribe=1&from=expired');
        expect(subscriptionJourney(user)?.payment).toBe('/payment-request?plan=pro&resubscribe=1');
    });
    it('keeps paused Pro and lifetime Ultra active despite a historical timestamp', () => {
        vi.spyOn(Date, 'now').mockReturnValue(now);
        for (const user of [{ ...base, is_pro_paused: true }, { ...base, tier: 'premium' }]) {
            expect(subscriptionJourney({ ...user, pro_expires_at: '2026-01-01T00:00:00Z' })).toBeNull();
        }
        // A forcibly expired lifetime membership is no longer an active base;
        // lead with the current PRO renewal offer rather than another lifetime purchase.
        expect(subscriptionJourney({ ...expired, tier: 'premium' })?.payment).toBe('/payment-request?plan=pro&resubscribe=1');
    });
    it('offers only the expired AI Brain add-on when the paused Pro base is still active', () => {
        vi.spyOn(Date, 'now').mockReturnValue(now);
        const user = { ...base, is_pro_paused: true, pro_expires_at: '2026-01-01T00:00:00Z',
            is_aibain_active: true, is_aibain_expired: false, aibain_expires_at: '2026-11-04T00:00:00Z' };
        expect(subscriptionJourney(user)?.kind).toBe('aibain-expired');
        expect(subscriptionJourney(user)?.payment).toBe('/payment-request?plan=pro&aibain=1');
    });
    it('rechecks the clock while open so timestamp expiry reveals the existing renewal popup', async () => {
        vi.useFakeTimers(); vi.setSystemTime(now);
        m.auth.user = { ...base, pro_expires_at: '2026-11-05T00:00:30Z' };
        showEntry(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
        expect(screen.getByRole('dialog')).toHaveTextContent('재구독');
    });
    it('lets a confirmed server nonpending result override an old cached pending flag', async () => {
        m.auth.user = { ...expired, has_pending_subscription: true };
        showEntry(); await act(async () => {});
        expect(screen.getByRole('dialog')).toHaveTextContent('재구독');
        expect(screen.queryByRole('link', { name: '신청 상태 확인' })).not.toBeInTheDocument();
    });
    it('shows actual pending status without another payment even when history is empty', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, pending_request: { id: 8, status: 'pending' } });
        showEntry(); await act(async () => {});
        expect(screen.getByRole('link', { name: '신청 상태 확인' })).toHaveAttribute('href', '/pending-approval');
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    it('immediately replaces a ready payment prompt when the same member acquires a pending request', async () => {
        m.auth.user = { ...expired };
        const view = showEntry(); await act(async () => {});
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        m.status.mockReturnValue(new Promise(() => {}));
        m.auth.user = { ...expired, has_pending_subscription: true,
            pending_subscription_request: { id: 21, status: 'pending', request_type: 'resubscription' } };
        view.rerender(<MemoryRouter initialEntries={['/community']}><SubscriptionEntry /></MemoryRouter>);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: '신청 상태 확인' })).toBeInTheDocument();
        expect(m.status).toHaveBeenCalledTimes(2);
    });
    it('invalidates an older status promise when a same-member pending request ID changes', async () => {
        let resolveOld!: (value: typeof ready) => void;
        m.auth.user = { ...expired, has_pending_subscription: true,
            pending_subscription_request: { id: 21, status: 'pending', request_type: 'resubscription' } };
        m.status.mockReturnValueOnce(new Promise(done => { resolveOld = done; }))
            .mockReturnValue(new Promise(() => {}));
        const view = showEntry();
        m.auth.user = { ...m.auth.user, pending_subscription_request: { id: 22, status: 'pending', request_type: 'resubscription' } };
        view.rerender(<MemoryRouter initialEntries={['/community']}><SubscriptionEntry /></MemoryRouter>);
        await act(async () => resolveOld(ready));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: '신청 상태 확인' })).toBeInTheDocument();
        expect(m.status).toHaveBeenCalledTimes(2);
    });
    it('rechecks a cleared pending flag and request status before allowing the same member to reapply', async () => {
        let resolveCurrent!: (value: typeof ready) => void;
        const nextStatus = new Promise(done => { resolveCurrent = done; });
        m.auth.user = { ...expired, has_pending_subscription: true,
            pending_subscription_request: { id: 21, status: 'pending', request_type: 'resubscription' } };
        m.status.mockResolvedValueOnce({ ...ready, pending_request: { id: 21, status: 'pending' } })
            .mockReturnValueOnce(nextStatus);
        const view = showEntry(); await act(async () => {});
        expect(screen.getByRole('link', { name: '신청 상태 확인' })).toBeInTheDocument();
        m.auth.user = { ...expired, has_pending_subscription: false,
            pending_subscription_request: { id: 21, status: 'rejected', request_type: 'resubscription' } };
        view.rerender(<MemoryRouter initialEntries={['/community']}><SubscriptionEntry /></MemoryRouter>);
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
        await act(async () => resolveCurrent(ready));
        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(m.status).toHaveBeenCalledTimes(2);
    });
    it('suppresses obsolete cached-expiry payment prompts after the same-user server confirms a grant', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { ...base, pro_expires_at: '2099-01-01T00:00:00Z' } });
        showEntry(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('구독 안내')).not.toBeInTheDocument();
        expect(m.auth.refreshUser).toHaveBeenCalledTimes(1);
    });
    it.each(['suspended', 'rejected'])('does not offer payment to a server-confirmed %s account', async status => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { ...base, status } });
        showEntry(); await act(async () => {});
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('구독 안내')).not.toBeInTheDocument();
    });
    it('rejects status data for another member without exposing a payment prompt', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { ...base, id: 2 } });
        showEntry(); await act(async () => {});
        expect(screen.getByRole('button', { name: '다시 확인' })).toBeInTheDocument();
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    });
    it('does not restore a late renewal overlay after logout', async () => {
        let resolve!: (value: typeof ready) => void;
        m.auth.user = { ...expired }; m.status.mockReturnValue(new Promise(done => { resolve = done; }));
        const view = showEntry();
        m.auth.user = null; m.auth.token = null;
        view.rerender(<MemoryRouter><SubscriptionEntry /></MemoryRouter>);
        await act(async () => resolve(ready));
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(screen.queryByLabelText('구독 안내')).not.toBeInTheDocument();
    });
    it.each(['rejected', 'cancelled'])('keeps %s visible with a direct previous-plan reapplication', async status => {
        m.auth.user = { ...expired, tier: 'premium' };
        m.status.mockResolvedValue({ ...ready, requests: [{ id: 4, status, to_tier: 'premium',
            admin_note: '신청 내역을 확인해 주세요', processed_at: '2026-11-04T12:00:00Z' }] });
        render(<MemoryRouter initialEntries={['/pending-approval']}><Routes>
            <Route path="/pending-approval" element={<PendingApprovalPage />} />
            <Route path="*" element={<div>다른 화면</div>} />
        </Routes></MemoryRouter>);
        await act(async () => {});
        expect(screen.queryByText('다른 화면')).not.toBeInTheDocument();
        expect(screen.getByText(/신청 내역을 확인해 주세요/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '재구독 신청' })).toHaveAttribute('href', '/payment-request?plan=premium&resubscribe=1');
    });
    it('hides reapplication after a status refresh fails instead of trusting a previous rejection', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro' }] });
        render(<MemoryRouter><PendingApprovalPage /></MemoryRouter>); await act(async () => {});
        expect(screen.getByRole('link', { name: '재구독 신청' })).toBeInTheDocument();
        m.status.mockRejectedValue(new Error('offline'));
        fireEvent(window, new Event('focus')); await act(async () => {});
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
        expect(screen.getByText(/신청 상태를 확인하지 못/)).toBeInTheDocument();
    });
    it('holds a confirmed approval instead of sending a cached expired member back to payment while auth refresh is unavailable', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { ...base, pro_expires_at: '2099-01-01T00:00:00Z' } });
        render(<MemoryRouter initialEntries={['/pending-approval']}><Routes>
            <Route path="/pending-approval" element={<PendingApprovalPage />} />
            <Route path="*" element={<div>다른 화면으로 이동</div>} />
        </Routes></MemoryRouter>); await act(async () => {});
        expect(screen.queryByText('다른 화면으로 이동')).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: '승인이 확인되었습니다' })).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
        expect(m.auth.refreshUser).toHaveBeenCalledTimes(1);
    });
    it('keeps an authoritative pending flag without a request row in approval instead of offering another payment', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { has_pending_subscription: true } });
        render(<MemoryRouter initialEntries={['/pending-approval']}><Routes>
            <Route path="/pending-approval" element={<PendingApprovalPage />} />
            <Route path="*" element={<div>다른 화면으로 이동</div>} />
        </Routes></MemoryRouter>); await act(async () => {});
        expect(screen.queryByText('다른 화면으로 이동')).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: '승인 대기 중' })).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: '플랜 선택하기' })).not.toBeInTheDocument();
    });
    it('immediately invalidates a prior rejection when the same member receives new pending metadata', async () => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValueOnce({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro' }] });
        const view = render(<MemoryRouter><PendingApprovalPage /></MemoryRouter>); await act(async () => {});
        expect(screen.getByRole('link', { name: '재구독 신청' })).toBeInTheDocument();
        m.status.mockReturnValue(new Promise(() => {}));
        m.auth.user = { ...expired, has_pending_subscription: true,
            pending_subscription_request: { id: 30, status: 'pending', request_type: 'resubscription' } };
        view.rerender(<MemoryRouter><PendingApprovalPage /></MemoryRouter>);
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: '승인 대기 중' })).toBeInTheDocument();
        expect(m.status).toHaveBeenCalledTimes(2);
    });
    it.each(['suspended', 'rejected'])('does not redirect a server-confirmed %s account toward a new payment', async status => {
        m.auth.user = { ...expired };
        m.status.mockResolvedValue({ ...ready, user: { ...base, status } });
        render(<MemoryRouter initialEntries={['/pending-approval']}><Routes>
            <Route path="/pending-approval" element={<PendingApprovalPage />} />
            <Route path="*" element={<div>다른 화면으로 이동</div>} />
        </Routes></MemoryRouter>); await act(async () => {});
        expect(screen.queryByText('다른 화면으로 이동')).not.toBeInTheDocument();
        expect(screen.getByRole('heading', { name: '계정 상태 확인이 필요합니다' })).toBeInTheDocument();
        expect(screen.queryByRole('link', { name: '재구독 신청' })).not.toBeInTheDocument();
    });
    it('ignores a previous pending response after a newer rejection has arrived', async () => {
        let resolveOld!: (value: any) => void;
        m.auth.user = { ...expired };
        m.status.mockReturnValueOnce(new Promise(done => { resolveOld = done; }))
            .mockResolvedValue({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro', admin_note: '최신 처리 사유' }] });
        render(<MemoryRouter><PendingApprovalPage /></MemoryRouter>);
        fireEvent(window, new Event('focus')); await act(async () => {});
        expect(screen.getByText(/최신 처리 사유/)).toBeInTheDocument();
        await act(async () => resolveOld({ ...ready, pending_request: { id: 8, status: 'pending' } }));
        expect(screen.getByText(/최신 처리 사유/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '재구독 신청' })).toBeInTheDocument();
    });
    it('clears account-bound status immediately and rejects a late previous-account response', async () => {
        let resolveOld!: (value: any) => void;
        m.auth.user = { ...expired };
        m.status.mockResolvedValueOnce({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro', admin_note: '이전 회원 사유' }] });
        const view = render(<MemoryRouter><PendingApprovalPage /></MemoryRouter>); await act(async () => {});
        m.status.mockReturnValueOnce(new Promise(done => { resolveOld = done; }));
        fireEvent(window, new Event('focus'));
        m.auth.user = { ...expired, id: 2 }; m.auth.token = 'another-member';
        m.status.mockResolvedValue({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro', admin_note: '현재 회원 사유' }] });
        view.rerender(<MemoryRouter><PendingApprovalPage /></MemoryRouter>); await act(async () => {});
        expect(screen.queryByText(/이전 회원 사유/)).not.toBeInTheDocument();
        await act(async () => resolveOld({ ...ready, requests: [{ status: 'rejected', to_tier: 'pro', admin_note: '지연된 이전 회원 사유' }] }));
        expect(screen.getByText(/현재 회원 사유/)).toBeInTheDocument();
        expect(screen.queryByText(/지연된 이전 회원 사유/)).not.toBeInTheDocument();
    });
    it('keeps plan selection in renewal mode when a Pro timestamp has elapsed but flags are cached', async () => {
        vi.spyOn(Date, 'now').mockReturnValue(now);
        m.auth.user = { ...base, pro_expires_at: '2026-11-04T00:00:00Z' };
        render(<MemoryRouter initialEntries={['/plan-select']}><Routes>
            <Route path="/plan-select" element={<PlanSelectPage />} />
            <Route path="*" element={<div>활성 회원 화면</div>} />
        </Routes></MemoryRouter>);
        await act(async () => {});
        expect(screen.getByRole('heading', { name: '재구독 플랜 선택' })).toBeInTheDocument();
        expect(screen.queryByText('활성 회원 화면')).not.toBeInTheDocument();
    });
});
