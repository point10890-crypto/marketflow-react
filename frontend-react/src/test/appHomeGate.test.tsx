import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppHomeGate } from '@/App';
import { clearToken, setToken, type FunnelUser } from '@/lib/auth';

const auth = vi.hoisted(() => ({
    user: null as FunnelUser | null,
    token: null as string | null,
    loading: false,
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => auth,
}));

function Destination() {
    const { pathname, search } = useLocation();
    return <output aria-label="이동한 주소">{pathname}{search}</output>;
}

function home() {
    return (
        <MemoryRouter initialEntries={['/']}>
            <Routes>
                <Route path="/" element={<AppHomeGate><h1>BitMan 소개</h1></AppHomeGate>} />
                <Route path="*" element={<Destination />} />
            </Routes>
        </MemoryRouter>
    );
}

describe('the app entry opens the correct destination for the current session', () => {
    const token = '7:4102444800:test-signature';

    beforeEach(() => {
        clearToken();
        auth.user = null;
        auth.token = null;
        auth.loading = false;
    });
    afterEach(clearToken);

    it('shows the public first page to a guest while auth initializes and afterward', () => {
        auth.loading = true;
        const view = render(home());
        expect(screen.getByRole('heading', { name: 'BitMan 소개' })).toBeInTheDocument();

        auth.loading = false;
        view.rerender(home());
        expect(screen.getByRole('heading', { name: 'BitMan 소개' })).toBeInTheDocument();
        expect(screen.queryByLabelText('이동한 주소')).not.toBeInTheDocument();
    });

    it('waits during a hard reload when browser storage has a session but auth has not read it', () => {
        setToken(token, true);
        auth.loading = true;
        const view = render(home());

        expect(screen.getByText('Loading...')).toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: 'BitMan 소개' })).not.toBeInTheDocument();
        expect(screen.queryByLabelText('이동한 주소')).not.toBeInTheDocument();

        auth.user = { role: 'user', status: 'approved', tier: 'pro' };
        auth.token = token;
        auth.loading = false;
        view.rerender(home());
        expect(screen.getByLabelText('이동한 주소')).toHaveTextContent(/^\/dashboard$/);
    });

    it('waits for member details when only a token is available', () => {
        auth.user = { status: 'unknown', role: 'user', tier: null };
        auth.token = token;
        render(home());

        expect(screen.getByText('Loading...')).toBeInTheDocument();
        expect(screen.queryByRole('heading', { name: 'BitMan 소개' })).not.toBeInTheDocument();
        expect(screen.queryByLabelText('이동한 주소')).not.toBeInTheDocument();
    });

    it.each([
        { user: { role: 'user', status: 'approved', tier: 'pro', has_pending_subscription: true }, path: '/dashboard' },
        { user: { role: 'user', status: 'approved', tier: 'premium' }, path: '/dashboard' },
        { user: { role: 'user', status: 'approved', tier: null, is_kongming_active: true, kongming_expires_at: '2099-01-01T00:00:00Z' }, path: '/dashboard/ai-bain' },
        { user: { role: 'admin', status: 'approved', tier: 'premium' }, path: '/admin' },
        { user: { role: 'user', status: 'pending', tier: null, has_pending_subscription: true }, path: '/pending-approval' },
        { user: { role: 'user', status: 'pending', tier: null, has_pending_subscription: false }, path: '/plan-select' },
        { user: { role: 'user', status: 'expired', tier: 'pro' }, path: '/plan-select?resubscribe=1&from=expired' },
    ])('opens $path for $user', ({ user, path }) => {
        auth.user = user;
        auth.token = token;
        render(home());

        expect(screen.getByLabelText('이동한 주소').textContent).toBe(path);
        expect(screen.queryByRole('heading', { name: 'BitMan 소개' })).not.toBeInTheDocument();
    });
});
