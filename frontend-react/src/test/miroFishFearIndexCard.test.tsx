import { render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MiroFishFearIndexCard from '@/components/mirofish/MiroFishFearIndexCard';

const mockApi = vi.hoisted(() => ({
    getFearIndex: vi.fn(),
    getLatestScannerCandidates: vi.fn(),
    getLatestScannerRun: vi.fn(),
    getScannerCandidates: vi.fn(),
}));

vi.mock('@/lib/mirofishApi', () => ({
    mirofishApi: mockApi,
}));

const scannerCandidates = Array.from({ length: 6 }, (_, index) => ({
    rank: index + 1,
    symbol: `00000${index + 1}`,
    display_name: `검출종목 ${index + 1}`,
    market: 'KOSPI',
    alpha_score: 60 + index,
    risk_score: 20 + index,
    action: index === 0 ? 'BUY_CANDIDATE' : 'WATCH',
    horizon: 'SWING_5_20D',
    strategy_tags: [],
    evidence: [],
    price: 10000 * (index + 1),
}));

describe('MiroFishFearIndexCard', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockApi.getFearIndex.mockResolvedValue({
            score: 41,
            level_label: '중립',
            tone: 'neutral',
            coverage_pct: 100,
            summary: '공포지수 41 (중립).',
            components: [{ status: 'ok' }],
        });
        mockApi.getLatestScannerCandidates.mockResolvedValue({
            run_id: 'latest-run',
            status: 'completed',
            candidates: scannerCandidates,
        });
        mockApi.getScannerCandidates.mockResolvedValue({ candidates: [] });
    });

    it('shows only the top five latest scanner candidates with trading opinions', async () => {
        render(<MiroFishFearIndexCard />);

        const list = await screen.findByTestId('fear-index-top-candidates');
        await waitFor(() => expect(within(list).getByText('검출종목 5')).toBeTruthy());

        expect(within(list).getByText('검출종목 1')).toBeTruthy();
        expect(within(list).queryByText('검출종목 6')).toBeNull();
        expect(within(list).getByText('매수 후보')).toBeTruthy();
        expect(within(list).getAllByText('관망')).toHaveLength(4);
        expect(within(list).getByText('10,000원')).toBeTruthy();
    });

    it('fetches the latest candidates when the parent supplies an empty list', async () => {
        render(<MiroFishFearIndexCard candidates={[]} candidatesLoading={false} />);

        const list = await screen.findByTestId('fear-index-top-candidates');
        await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(5));

        expect(mockApi.getLatestScannerCandidates).toHaveBeenCalledWith(5);
        expect(within(list).queryByText('표시할 최신 검출 종목이 없습니다.')).toBeNull();
    });
});
