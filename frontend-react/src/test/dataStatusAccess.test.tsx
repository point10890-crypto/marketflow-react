import { render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import DataStatusPage from '@/pages/dashboard/DataStatusPage';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ API_BASE: 'https://test.invalid', fetchAuthAPI: api.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'admin-token' }) }));
vi.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('@/components/layout/PullToRefreshProvider', () => ({ usePullToRefreshRegister: () => {} }));

beforeEach(() => { api.fetchAuthAPI.mockReset(); });

it('loads the admin-only status endpoint with authenticated transport', async () => {
    api.fetchAuthAPI.mockResolvedValue({ files: [{ name: 'US Smart Money', path: 'safe.json',
        exists: true, lastModified: new Date().toISOString(), size: '1 KB' }] });
    render(<DataStatusPage />);
    expect(await screen.findByText('US Smart Money')).toBeInTheDocument();
    expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/system/data-status', 'admin-token');
});
