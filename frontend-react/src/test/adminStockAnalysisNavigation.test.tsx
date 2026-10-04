import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminGuard } from '@/App';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';

const auth = vi.hoisted(() => ({ user: null as Record<string, unknown> | null, loading: false }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ ...auth, logout: vi.fn() }), AuthProvider: (p: { children: React.ReactNode }) => p.children }));
vi.mock('@/hooks/usePWAInstall', () => ({ usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: vi.fn() }) }));
vi.mock('@/contexts/NotificationContext', () => ({ useNotification: () => ({ notifications: [], unreadCount: 0, markAllRead: vi.fn(), clearAll: vi.fn(), dismiss: vi.fn() }) }));
const path = '/admin/stock-analysis';
function guarded() { return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path={path} element={<AdminGuard><p>관리자 분석 본문</p></AdminGuard>} />
    <Route path="/login" element={<p>로그인</p>} /><Route path="/dashboard" element={<p>대시보드</p>} />
</Routes></MemoryRouter>); }
describe('admin stock analysis navigation and access', () => {
    beforeEach(() => { auth.user = { role: 'admin', name: '관리자', status: 'approved' }; auth.loading = false; });
    it('allows an admin without requiring a subscriber add-on', () => { guarded(); expect(screen.getByText('관리자 분석 본문')).toBeInTheDocument(); });
    it.each([null, { role: 'user', tier: 'pro', status: 'approved' }])('does not render admin data for %j', user => {
        auth.user = user; guarded(); expect(screen.queryByText('관리자 분석 본문')).not.toBeInTheDocument();
        expect(screen.getByText(user ? '대시보드' : '로그인')).toBeInTheDocument();
    });
    it('waits for auth hydration before rendering protected data', () => { auth.loading = true; guarded(); expect(screen.queryByText('관리자 분석 본문')).not.toBeInTheDocument(); });
    it('shows the admin menu and title, closing the mobile drawer on navigation', async () => {
        const onClose = vi.fn(); render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Sidebar mobile isOpen onClose={onClose} /><Header /></MemoryRouter>);
        const link = screen.getByRole('link', { name: '종목 검색 분석' });
        expect(link).toHaveAttribute('href', path); expect(link).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('heading', { name: '종목 검색 분석' })).toBeInTheDocument();
        await userEvent.click(link); expect(onClose).toHaveBeenCalledOnce();
    });
    it('hides the new menu from paid members', () => {
        auth.user = { role: 'user', tier: 'pro', status: 'approved' };
        render(<MemoryRouter><Sidebar /></MemoryRouter>); expect(screen.queryByRole('link', { name: '종목 검색 분석' })).not.toBeInTheDocument();
    });
});
