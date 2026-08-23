/**
 * AI Brain 은 AI Brain 구독자(활성 애드온) 또는 admin 에게만 보이는 섹션이어야 한다.
 * - 내비 3종(Sidebar / BottomTabBar / MobileDashboardRail)에서 미구독 Pro 유저에게 AI Brain 항목이 렌더되지 않는다.
 * - 구독자·admin 에게는 렌더된다.
 * - canAccessAiBain() 단일 기준.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { canAccessAiBain } from '@/lib/auth';
import Sidebar from '@/components/layout/Sidebar';
import BottomTabBar from '@/components/layout/BottomTabBar';
import MobileDashboardRail from '@/components/layout/MobileDashboardRail';

const authState = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: authState.user,
    token: 't',
    loading: false,
    logout: vi.fn(),
    isAdmin: () => authState.user?.role === 'admin',
  }),
}));

vi.mock('@/hooks/usePWAInstall', () => ({
  usePWAInstall: () => ({ canInstall: false, isInstalled: false, isIOS: false, install: async () => 'manual' }),
}));

const proNoAiBain = { id: 1, email: 'pro@example.com', name: 'Pro', tier: 'pro', role: 'user', status: 'approved', is_aibain_active: false };
const proWithAiBain = { ...proNoAiBain, id: 2, is_aibain_active: true, aibain_enabled: true };
const admin = { id: 3, email: 'admin@example.com', name: 'Admin', tier: null, role: 'admin', status: 'approved', is_aibain_active: false };

function renderAt(path: string, ui: React.ReactElement) {
  return render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>);
}

describe('canAccessAiBain', () => {
  it('is false for null / non-subscriber pro, true for active add-on or admin', () => {
    expect(canAccessAiBain(null)).toBe(false);
    expect(canAccessAiBain(proNoAiBain)).toBe(false);
    expect(canAccessAiBain({ ...proNoAiBain, is_aibain_active: true })).toBe(true);
    expect(canAccessAiBain(admin)).toBe(true);
  });
});

describe('AI Brain navigation gating', () => {
  beforeEach(() => {
    authState.user = proNoAiBain;
  });

  it('Sidebar hides the AI Brain entry for a Pro user without the add-on', () => {
    renderAt('/dashboard', <Sidebar />);
    expect(screen.queryByText('AI Brain')).toBeNull();
    expect(screen.getByText('Summary')).toBeInTheDocument();
  });

  it('Sidebar shows AI Brain for an active add-on subscriber and for admin', () => {
    authState.user = proWithAiBain;
    const { unmount } = renderAt('/dashboard', <Sidebar />);
    expect(screen.getByText('AI Brain')).toBeInTheDocument();
    unmount();

    authState.user = admin;
    renderAt('/dashboard', <Sidebar />);
    expect(screen.getByText('AI Brain')).toBeInTheDocument();
  });

  it('BottomTabBar hides / shows the AI Brain tab by entitlement', () => {
    const { unmount } = renderAt('/dashboard', <BottomTabBar />);
    expect(screen.queryByText('AI Brain')).toBeNull();
    expect(screen.getByText('Summary')).toBeInTheDocument();
    unmount();

    authState.user = proWithAiBain;
    renderAt('/dashboard', <BottomTabBar />);
    expect(screen.getByText('AI Brain')).toBeInTheDocument();
  });

  it('MobileDashboardRail hides the AI Brain pill, rail item and Goodrich item for non-subscribers', () => {
    const { unmount } = renderAt('/dashboard', <MobileDashboardRail />);
    expect(screen.queryAllByText('AI Brain')).toHaveLength(0);
    expect(screen.queryByText('Goodrich TOP 3')).toBeNull();
    expect(screen.getByText('Briefing')).toBeInTheDocument();
    unmount();

    authState.user = proWithAiBain;
    renderAt('/dashboard', <MobileDashboardRail />);
    expect(screen.queryAllByText('AI Brain').length).toBeGreaterThan(0);
    expect(screen.getByText('Goodrich TOP 3')).toBeInTheDocument();
  });
});
