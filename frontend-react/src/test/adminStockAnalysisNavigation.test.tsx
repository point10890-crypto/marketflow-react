import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AdminGuard } from '@/App';
import Sidebar from '@/components/layout/Sidebar';
import Header from '@/components/layout/Header';
import AdminStockAnalysisPage from '@/pages/admin/AdminStockAnalysisPage';
const auth = vi.hoisted(() => ({ user: null as Record<string, unknown> | null, loading: false, token: 'admin-token' }));
const privateAPI = vi.hoisted(() => ({ fetchAdminStockAnalysis: vi.fn(), startAdminStockAnalysis: vi.fn(), searchAdminStockCandidates: vi.fn() }));
vi.mock('@/lib/adminStockAnalysisApi', async importOriginal => ({ ...(await importOriginal<typeof import('@/lib/adminStockAnalysisApi')>()), ...privateAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ ...auth, logout: vi.fn() }), AuthProvider: (p: { children: React.ReactNode }) => p.children }));
vi.mock('@/hooks/usePWAInstall', () => ({ usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: vi.fn() }) }));
vi.mock('@/contexts/NotificationContext', () => ({ useNotification: () => ({ notifications: [], unreadCount: 0, markAllRead: vi.fn(), clearAll: vi.fn(), dismiss: vi.fn() }) }));
const path = '/admin/stock-analysis', chartPath = '/dashboard/ai-bain/chart-predict';
function guarded() { return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path={path} element={<AdminGuard><p>관리자 분석 본문</p></AdminGuard>} />
    <Route path="/login" element={<p>로그인</p>} /><Route path="/dashboard" element={<p>대시보드</p>} />
</Routes></MemoryRouter>); }
function CurrentPath() { const location = useLocation(); return <output aria-label="연결 경로">{location.pathname}{location.search}{location.hash}</output>; }
function legacy(query = '') { return render(<MemoryRouter initialEntries={[path + query]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes>
    <Route path={path} element={<AdminGuard><AdminStockAnalysisPage /></AdminGuard>} />
    <Route path={chartPath} element={<p>차트 유사 사례 본문</p>} />
    <Route path="/login" element={<p>로그인</p>} /><Route path="/dashboard" element={<p>대시보드</p>} />
</Routes><CurrentPath /></MemoryRouter>); }
describe('embedded admin stock analysis navigation and legacy access', () => {
    beforeEach(() => { auth.user = { role: 'admin', name: '관리자', status: 'approved' }; auth.loading = false; vi.clearAllMocks(); privateAPI.fetchAdminStockAnalysis.mockResolvedValue({ state: 'missing', result: null }); });
    it('allows an admin without requiring a subscriber add-on', () => { guarded(); expect(screen.getByText('관리자 분석 본문')).toBeInTheDocument(); });
    it.each([null, { role: 'user', tier: 'pro', status: 'approved' }])('does not render admin data for %j', user => {
        auth.user = user; guarded(); expect(screen.queryByText('관리자 분석 본문')).not.toBeInTheDocument(); expect(screen.getByText(user ? '대시보드' : '로그인')).toBeInTheDocument();
    });
    it('waits for auth hydration before rendering protected data', () => { auth.loading = true; guarded(); expect(screen.queryByText('관리자 분석 본문')).not.toBeInTheDocument(); });
    it('keeps chart navigation in AI Brain and removes the standalone admin menu', async () => {
        const onClose = vi.fn(); render(<MemoryRouter initialEntries={[chartPath]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Sidebar mobile isOpen onClose={onClose} /><Header /></MemoryRouter>);
        expect(screen.queryByRole('link', { name: '종목 검색 분석' })).not.toBeInTheDocument(); expect(screen.getByRole('heading', { name: '차트 유사 사례' })).toBeInTheDocument();
        const link = screen.getByRole('link', { name: '차트 유사 사례' }); expect(link).toHaveAttribute('href', chartPath); await userEvent.click(link); expect(onClose).toHaveBeenCalledOnce();
    });
    it('does not add a private menu for paid members', () => { auth.user = { role: 'user', tier: 'pro', status: 'approved' }; render(<MemoryRouter><Sidebar /></MemoryRouter>); expect(screen.queryByRole('link', { name: '종목 검색 분석' })).not.toBeInTheDocument(); });
    it('redirects old links into the chart panel preserving the selected symbol and release without fetching private data', async () => {
        legacy('?code=196170&release=previous'); await screen.findByText('차트 유사 사례 본문');
        expect(screen.getByLabelText('연결 경로')).toHaveTextContent(`${chartPath}?code=196170&release=previous&adminCode=196170#admin-stock-analysis`);
        expect(privateAPI.fetchAdminStockAnalysis).not.toHaveBeenCalled(); expect(privateAPI.startAdminStockAnalysis).not.toHaveBeenCalled();
    });
    it.each(['', '?code=bad&release=previous', '?code=000000'])('does not carry invalid legacy stock codes for %s', async query => {
        legacy(query); await screen.findByText('차트 유사 사례 본문'); const route = screen.getByLabelText('연결 경로').textContent!;
        expect(route).toContain(chartPath); expect(route).toContain('#admin-stock-analysis'); expect(route).not.toMatch(/[?&](?:code|adminCode)=/); expect(privateAPI.fetchAdminStockAnalysis).not.toHaveBeenCalled();
    });
    it.each([null, { role: 'user', tier: 'pro', status: 'approved' }])('retains the admin guard on legacy URLs for %j', async user => {
        auth.user = user; legacy('?code=196170'); expect(await screen.findByText(user ? '대시보드' : '로그인')).toBeInTheDocument();
        expect(screen.queryByText('차트 유사 사례 본문')).not.toBeInTheDocument(); expect(privateAPI.fetchAdminStockAnalysis).not.toHaveBeenCalled();
    });
});
