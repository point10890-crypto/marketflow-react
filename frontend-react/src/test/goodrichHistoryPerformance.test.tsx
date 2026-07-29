import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import GoodrichFundManagerPage from '@/pages/dashboard/aibain/GoodrichFundManagerPage';

const mockApi = vi.hoisted(() => ({
    fetchAuthAPI: vi.fn(),
    postAuthAPI: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
    fetchAuthAPI: mockApi.fetchAuthAPI,
    postAuthAPI: mockApi.postAuthAPI,
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ token: 'test-token' }),
}));

vi.mock('@/components/aibain/AiBrainServiceTabs', () => ({
    default: () => <div>AI Brain tabs</div>,
}));

vi.mock('@/components/aibain/GoodrichTop3Charts', () => ({
    default: () => <div>TOP 3 charts</div>,
}));

describe('Goodrich history and performance endpoints', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi.fetchAuthAPI
            .mockResolvedValueOnce({
                headline: '오늘의 TOP 3',
                picks: [{ rank: 1, symbol: '005930', name: '삼성전자', current_price: 100 }],
                integration: { universe_size: 3 },
            })
            .mockResolvedValueOnce({
                items: [{
                    cycle_id: 'cycle-12345678',
                    detected_at: '2026-07-28T01:00:00Z',
                    picks: [{ rank: 1, symbol: '005930', name: '삼성전자', status: 'monitoring' }],
                }],
            })
            .mockResolvedValueOnce({
                window_days: 30,
                total_picks: 12,
                active_count: 3,
                evaluated_count: 2,
                target_hits: 1,
                stop_hits: 1,
                hit_rate_pct: 50,
            });
    });

    it('shows large endpoint buttons and renders live history/performance data', async () => {
        render(<MemoryRouter><GoodrichFundManagerPage /></MemoryRouter>);

        await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalledTimes(3));

        expect(screen.getByRole('link', { name: /검출 이력/ })).toHaveAttribute('href', '#goodrich-history');
        expect(screen.getByRole('link', { name: /성과 검증/ })).toHaveAttribute('href', '#goodrich-performance');
        expect((await screen.findAllByText('삼성전자')).length).toBeGreaterThan(0);
        expect(screen.getByText('목표 달성').nextElementSibling?.textContent).toBe('1');
        expect(screen.getByText('손절 도달').nextElementSibling?.textContent).toBe('1');
        expect(screen.getByText('적중률').nextElementSibling?.textContent).toBe('50%');
        expect(screen.queryByText('에이전트 상호 분석 파이프라인')).not.toBeInTheDocument();
    });

    it('renders cash-wait state and zero selected from a completed multi-MCP run', async () => {
        mockApi.fetchAuthAPI.mockReset();
        mockApi.fetchAuthAPI
            .mockResolvedValueOnce({
                status: 'research_required',
                headline: '현금 대기',
                picks: [],
                multi_mcp: {
                    status: 'selective_portfolio',
                    candidate_count: 9,
                    profit_gate_passed_count: 2,
                    selected: [{ symbol: '052460' }, { symbol: '068270' }],
                    architecture: {
                        mcp_domains: [{ id: 'market', owner: 'KIS/regime' }],
                        agent_flow: ['candidate_detection', 'cio_selection_or_cash_wait'],
                    },
                },
            })
            .mockResolvedValueOnce({ items: [] })
            .mockResolvedValueOnce({
                window_days: 30,
                total_picks: 0,
                active_count: 0,
                evaluated_count: 0,
                target_hits: 0,
                stop_hits: 0,
            });

        render(<MemoryRouter><GoodrichFundManagerPage /></MemoryRouter>);

        expect(await screen.findByRole('region', { name: '현재는 현금 대기 구간입니다' })).toBeInTheDocument();
        expect(screen.getByText('현재는 현금 대기 구간입니다.')).toBeInTheDocument();
        expect(screen.getByText(/백그라운드에서 다음 검출을 계속합니다/)).toBeInTheDocument();
        expect(screen.queryByText('에이전트 상호 분석 파이프라인')).not.toBeInTheDocument();
    });
});
