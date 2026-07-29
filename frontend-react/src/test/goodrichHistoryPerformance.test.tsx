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
            })
            .mockResolvedValueOnce({
                objective: 'forward_profit_quality_with_cash_wait',
                mcp_domains: [
                    { id: 'market', owner: 'KIS/regime', mode: 'read_only' },
                    { id: 'technical', owner: 'trend/price structure', mode: 'read_only' },
                    { id: 'evidence', owner: 'DART/news/GraphRAG/freshness', mode: 'read_only' },
                    { id: 'memory', owner: 'look-ahead-safe outcomes', mode: 'read_only' },
                    { id: 'debate', owner: 'bull/bear cross-examination', mode: 'compute' },
                    { id: 'cio', owner: 'approval/rejection', mode: 'compute' },
                ],
                agent_flow: [
                    'candidate_detection',
                    'parallel_mcp_evidence',
                    'profit_quality_gate',
                    'four_analyst_reports',
                    'bull_bear_cross_examination',
                    'trader_risk_review',
                    'cio_selection_or_cash_wait',
                    'outcome_memory',
                ],
            });
    });

    it('shows large endpoint buttons and renders live history/performance data', async () => {
        render(<MemoryRouter><GoodrichFundManagerPage /></MemoryRouter>);

        await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalledTimes(4));

        expect(screen.getByRole('link', { name: /검출 이력/ })).toHaveAttribute('href', '#goodrich-history');
        expect(screen.getByRole('link', { name: /성과 검증/ })).toHaveAttribute('href', '#goodrich-performance');
        expect((await screen.findAllByText('삼성전자')).length).toBeGreaterThan(0);
        expect(screen.getByText('목표 달성').nextElementSibling?.textContent).toBe('1');
        expect(screen.getByText('손절 도달').nextElementSibling?.textContent).toBe('1');
        expect(screen.getByText('적중률').nextElementSibling?.textContent).toBe('50%');
        expect(screen.getByRole('region', { name: '멀티 MCP 에이전트 운영 상태' })).toBeInTheDocument();
        expect(screen.getByText('에이전트 상호 분석 파이프라인')).toBeInTheDocument();
        expect(screen.getByText('Bull ↔ Bear 상호 검증')).toBeInTheDocument();
        expect(screen.getByText('최종 Selected').nextElementSibling?.textContent).toBe('1');
    });

    it('renders cash-wait state and zero selected from a completed multi-MCP run', async () => {
        mockApi.fetchAuthAPI.mockReset();
        mockApi.fetchAuthAPI
            .mockResolvedValueOnce({
                status: 'cash_wait',
                headline: '현금 대기',
                picks: [],
                multi_mcp: {
                    status: 'cash_wait',
                    candidate_count: 9,
                    profit_gate_passed_count: 0,
                    selected: [],
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
            })
            .mockResolvedValueOnce({ mcp_domains: [], agent_flow: [] });

        render(<MemoryRouter><GoodrichFundManagerPage /></MemoryRouter>);

        expect(await screen.findByText('현금 대기', { selector: 'span' })).toBeInTheDocument();
        expect(screen.getByText('검출 후보').nextElementSibling?.textContent).toBe('9');
        expect(screen.getByText('게이트 통과').nextElementSibling?.textContent).toBe('0');
        expect(screen.getByText('최종 Selected').nextElementSibling?.textContent).toBe('0');
        expect(screen.getByText(/수익 품질 게이트와 CIO 심사를 통과한 종목이 없어/)).toBeInTheDocument();
    });
});
