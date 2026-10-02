import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Header from '@/components/layout/Header';
import MobileDashboardRail from '@/components/layout/MobileDashboardRail';
import Sidebar from '@/components/layout/Sidebar';

const authState = vi.hoisted(() => ({ user: null as Record<string, unknown> | null }));
vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: authState.user, token: 'member-token', loading: false, logout: vi.fn() }),
}));
vi.mock('@/hooks/usePWAInstall', () => ({
    usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: async () => 'manual' }),
}));
vi.mock('@/contexts/NotificationContext', () => ({
    useNotification: () => ({ notifications: [], unreadCount: 0, markAllRead: vi.fn(), clearAll: vi.fn(), dismiss: vi.fn() }),
}));

const CHART_PATH = '/dashboard/ai-bain/chart-predict';
const subscriber = {
    id: 1, email: 'member@example.test', name: 'Member', tier: 'pro', role: 'user',
    status: 'approved', is_aibain_active: true, aibain_enabled: true,
};

function CurrentPath() {
    const { pathname, search } = useLocation();
    return <output aria-label="현재 경로">{pathname}{search}</output>;
}

function renderAt(path: string, children: React.ReactNode) {
    return render(<MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>{children}</MemoryRouter>);
}

describe('chart analogue entry in dashboard navigation', () => {
    beforeEach(() => { authState.user = subscriber; });

    it('lets members open chart analogues from the expanded AI Brain sidebar', () => {
        renderAt('/dashboard/ai-bain', <Sidebar />);

        expect(screen.getByRole('link', { name: '차트 유사 사례' })).toHaveAttribute('href', CHART_PATH);
        expect(screen.getByRole('link', { name: '알파 스캐너' })).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: 'Goodrich TOP 3' })).toBeInTheDocument();
        expect(screen.getByRole('link', { name: '종목 판단' })).toBeInTheDocument();
    });

    it.each([false, true])('marks the chart child current with symbol query parameters (mobile=%s)', mobile => {
        renderAt(`${CHART_PATH}?symbol=042700`, <Sidebar mobile={mobile} isOpen={mobile} />);

        const chart = screen.getByRole('link', { name: '차트 유사 사례' });
        expect(chart).toHaveAttribute('href', CHART_PATH);
        expect(chart).toHaveAttribute('aria-current', 'page');
        expect(screen.getByRole('link', { name: '알파 스캐너' })).not.toHaveAttribute('aria-current');
        expect(screen.getByRole('link', { name: '종목 판단' })).not.toHaveAttribute('aria-current');
    });

    it('navigates to the default chart page and closes the mobile sidebar', async () => {
        const onClose = vi.fn();
        renderAt('/dashboard/ai-bain', <><Sidebar mobile isOpen onClose={onClose} /><CurrentPath /></>);

        await userEvent.click(screen.getByRole('link', { name: '차트 유사 사례' }));

        expect(screen.getByLabelText('현재 경로')).toHaveTextContent(CHART_PATH);
        expect(screen.getByLabelText('현재 경로')).not.toHaveTextContent('?');
        expect(onClose).toHaveBeenCalledOnce();
    });

    it.each([
        { label: 'anonymous', user: null },
        { label: 'no AI Brain add-on', user: { ...subscriber, is_aibain_active: false, aibain_enabled: false } },
        { label: 'expired AI Brain add-on', user: { ...subscriber, is_aibain_active: false } },
    ])('hides chart links from $label users', ({ user }) => {
        authState.user = user;
        renderAt(CHART_PATH, <><Sidebar /><MobileDashboardRail /></>);

        expect(screen.queryByRole('link', { name: '차트 유사 사례' })).not.toBeInTheDocument();
        expect(screen.queryByRole('link', { name: 'AI Brain' })).not.toBeInTheDocument();
    });

    it('shows chart navigation to admins without an AI Brain add-on', () => {
        authState.user = { ...subscriber, role: 'admin', is_aibain_active: false, aibain_enabled: false };
        renderAt(CHART_PATH, <><Sidebar /><MobileDashboardRail /></>);

        const links = screen.getAllByRole('link', { name: '차트 유사 사례' });
        expect(links).toHaveLength(2);
        for (const link of links) expect(link).toHaveAttribute('aria-current', 'page');
    });

    it('shows the Korean chart page title in the desktop header', () => {
        renderAt(`${CHART_PATH}?symbol=042700`, <Header />);

        expect(screen.getByRole('heading', { name: '차트 유사 사례', level: 1 })).toBeInTheDocument();
    });

    it('prioritizes the chart title and current link over the generic AI Brain mobile entry', () => {
        renderAt(`${CHART_PATH}?symbol=042700`, <MobileDashboardRail />);

        expect(screen.getByRole('heading', { name: '차트 유사 사례', level: 1 })).toBeInTheDocument();
        expect(screen.getByText('과거 사례 분포')).toBeInTheDocument();
        expect(screen.queryByText('GraphRAG')).not.toBeInTheDocument();
        expect(screen.getByRole('link', { name: '차트 유사 사례' })).toHaveAttribute('href', CHART_PATH);
        expect(screen.getByRole('link', { name: '차트 유사 사례' })).toHaveAttribute('aria-current', 'page');
        for (const link of screen.getAllByRole('link', { name: 'AI Brain' })) {
            expect(link).not.toHaveAttribute('aria-current');
        }
    });
});
