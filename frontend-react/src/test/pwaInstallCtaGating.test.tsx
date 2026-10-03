import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import InstallPrompt from '@/components/layout/InstallPrompt';
import Sidebar from '@/components/layout/Sidebar';
import AccountPage from '@/pages/AccountPage';
import LandingPage from '@/pages/LandingPage';
import { safeRemoveItem } from '@/lib/safeStorage';

const pwaState = vi.hoisted(() => ({
    canInstall: false,
    isInstalled: false,
    isIOS: false,
    install: vi.fn(),
}));

const authState = vi.hoisted(() => ({
    user: {
        id: 1,
        email: 'pro@example.com',
        name: 'Pro User',
        tier: 'pro',
        role: 'user',
        status: 'approved',
        is_aibain_active: false,
    },
}));

vi.mock('@/hooks/usePWAInstall', () => ({
    usePWAInstall: () => pwaState,
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({
        user: authState.user,
        token: null,
        loading: false,
        logout: vi.fn(),
        refreshUser: vi.fn(),
        setSession: vi.fn(),
        isAdmin: () => false,
    }),
}));

const installSurfaces = [
    ['sidebar', () => <Sidebar />],
    ['account page', () => <AccountPage />],
] as const;

const manualGuideSurfaces = [
    ['sidebar', () => <Sidebar />],
    ['account page', () => <AccountPage />],
    ['landing page', () => <LandingPage />],
] as const;

function surfaceTree(subject: () => React.ReactNode) {
    return (
        <MemoryRouter initialEntries={['/dashboard/account']}>
            {subject()}
        </MemoryRouter>
    );
}

function renderSurface(subject: () => React.ReactNode) {
    return render(surfaceTree(subject));
}

describe('PWA install CTA gating', () => {
    beforeEach(() => {
        pwaState.canInstall = false;
        pwaState.isInstalled = false;
        pwaState.isIOS = false;
        pwaState.install.mockReset().mockResolvedValue('manual');
        safeRemoveItem('local', 'install-dismissed');
    });

    afterEach(() => {
        cleanup();
        vi.useRealTimers();
        safeRemoveItem('local', 'install-dismissed');
    });

    it.each(installSurfaces)('hides the %s install action when installation is unavailable', (_name, subject) => {
        renderSurface(subject);

        expect(screen.queryByRole('button', { name: /앱|홈 화면/ })).not.toBeInTheDocument();
    });

    it.each(installSurfaces)('hides the %s install action after the app is installed', (_name, subject) => {
        pwaState.canInstall = true;
        pwaState.isInstalled = true;

        renderSurface(subject);

        expect(screen.queryByRole('button', { name: /앱|홈 화면/ })).not.toBeInTheDocument();
    });

    it('labels the sidebar action as installation instead of a download', () => {
        pwaState.canInstall = true;

        renderSurface(() => <Sidebar />);

        expect(screen.getByRole('button', { name: '앱으로 설치' })).toBeInTheDocument();
        expect(screen.queryByText('앱 다운로드')).not.toBeInTheDocument();
    });

    it('describes the account action as adding the app to the home screen', () => {
        pwaState.canInstall = true;

        renderSurface(() => <AccountPage />);

        expect(screen.getByRole('heading', { name: '홈 화면에 추가' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: '앱으로 설치' })).toBeInTheDocument();
        expect(screen.queryByText('앱 다운로드')).not.toBeInTheDocument();
    });

    it('keeps the automatic manual guide visible after the native prompt becomes unavailable', async () => {
        vi.useFakeTimers();
        pwaState.canInstall = true;
        pwaState.install.mockImplementation(async () => {
            pwaState.canInstall = false;
            return 'manual';
        });

        render(<InstallPrompt />);
        act(() => vi.advanceTimersByTime(3000));

        await act(async () => {
            fireEvent.click(screen.getByRole('button', { name: '앱 설치하기' }));
            await Promise.resolve();
        });

        expect(screen.getByRole('heading', { name: '앱 설치 방법' })).toBeInTheDocument();
    });

    it.each(manualGuideSurfaces)('closes the %s manual guide when installation completes', async (_name, subject) => {
        pwaState.canInstall = true;
        const view = renderSurface(subject);

        fireEvent.click(screen.getByRole('button', { name: /앱으로 (?:설치|추가)/ }));
        expect(await screen.findByRole('heading', { name: '앱 설치 방법' })).toBeInTheDocument();

        pwaState.isInstalled = true;
        view.rerender(surfaceTree(subject));

        expect(screen.queryByRole('heading', { name: '앱 설치 방법' })).not.toBeInTheDocument();
    });

    it.each(manualGuideSurfaces)('labels the %s iOS action as installation guidance', (_name, subject) => {
        pwaState.canInstall = true;
        pwaState.isIOS = true;

        renderSurface(subject);

        expect(screen.getByRole('button', { name: '설치 방법 보기' })).toBeInTheDocument();
    });
});
