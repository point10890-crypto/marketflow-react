import { render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import DataStatusPage from '@/pages/dashboard/DataStatusPage';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock('@/lib/api', () => ({ API_BASE: 'https://test.invalid', fetchAuthAPI: api.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ token: 'admin-token' }) }));
vi.mock('@/hooks/useIsMobile', () => ({ useIsMobile: () => viewport.mobile }));
vi.mock('@/components/layout/PullToRefreshProvider', () => ({ usePullToRefreshRegister: () => {} }));

beforeEach(() => { api.fetchAuthAPI.mockReset(); viewport.mobile = false; });

it('loads the admin-only status endpoint with authenticated transport', async () => {
    api.fetchAuthAPI.mockResolvedValue({ files: [{ name: 'US Smart Money', path: 'safe.json',
        exists: true, lastModified: new Date().toISOString(), size: '1 KB' }] });
    render(<DataStatusPage />);
    expect(await screen.findByText('US Smart Money')).toBeInTheDocument();
    expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/system/data-status', 'admin-token');
});

it.each([false, true])('shows partial source coverage instead of OK (mobile=%s)', async (mobile) => {
    viewport.mobile = mobile;
    api.fetchAuthAPI.mockResolvedValue({ files: [{ name: 'Institutional Trend', path: 'safe.csv',
        exists: true, lastModified: new Date().toISOString(), size: '1 MB', rowCount: 2665,
        collection: { status: 'partial', requested: 2760, successful: 2383, failed: 377,
            skipped: 0, source_date: '2026-11-06', collected_at: '2026-11-08T01:42:00+09:00',
            detail: '원본이 오래됐거나 필요한 가격·거래량이 없습니다.' } }] });
    render(<DataStatusPage />);
    const card = within(await screen.findByRole('article', { name: 'Institutional Trend 데이터 상태' }));
    expect(card.getByText('부분 실패')).toBeInTheDocument();
    expect(card.getByText('2,383 / 2,760종목')).toBeInTheDocument();
    expect(card.getByText('실패 377 · 이력 부족 0')).toBeInTheDocument();
    expect(card.getByText('2026-11-06')).toBeInTheDocument();
    expect(card.getByText('2026-11-08 01:42:00 KST')).toBeInTheDocument();
    expect(card.queryByText('OK')).not.toBeInTheDocument();
    expect(card.getByText(/이전 결과가 포함/)).toBeInTheDocument();
});

it.each(['unknown', 'stale', 'failed', undefined])('does not infer source health from a recent file (%s)', async (status) => {
    api.fetchAuthAPI.mockResolvedValue({ files: [{ name: 'Institutional Trend', path: 'safe.csv',
        exists: true, lastModified: new Date().toISOString(), size: '1 MB',
        ...(status ? { collection: { status, requested: null, successful: null, failed: null,
            skipped: null, source_date: null, collected_at: null, detail: '원본 상태 확인이 필요합니다.' } } : {}) }] });
    render(<DataStatusPage />);
    const card = within(await screen.findByRole('article', { name: 'Institutional Trend 데이터 상태' }));
    expect(card.queryByText('OK')).not.toBeInTheDocument();
    expect(card.getByText(status === 'stale' ? '원본 지연' : status === 'failed' ? '수집 실패' : '확인 필요')).toBeInTheDocument();
    expect(card.queryByText(/0 \/ 0종목/)).not.toBeInTheDocument();
});
