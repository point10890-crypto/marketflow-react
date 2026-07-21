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

const workflowTop3 = Array.from({ length: 3 }, (_, index) => ({
    run_id: `analysis-${index + 1}`,
    symbol: `10000${index + 1}`,
    target: `Top Result ${index + 1}`,
    market: 'KOSPI',
    final_score: 82 - (index * 5),
    verdict: {
        action: 'BUY',
        confidence_pct: 75 - (index * 5),
        symbol: `10000${index + 1}`,
        market: 'KOSPI',
        reference_date: '2026-07-21',
        target_display: `Top Result ${index + 1}`,
    },
    graphrag: {
        links: 10414 - (index * 11),
        entities: 20 - index,
        relations: 10 + index,
    },
    outcome_status: 'pending',
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

    it('renders scanner candidates bundled with the fear-index response', async () => {
        mockApi.getFearIndex.mockResolvedValue({
            score: 41,
            level_label: '중립',
            components: [],
            scanner_top_candidates: scannerCandidates,
        });
        mockApi.getLatestScannerCandidates.mockReturnValue(new Promise(() => undefined));

        render(<MiroFishFearIndexCard candidates={[]} candidatesLoading={false} />);

        const list = await screen.findByTestId('fear-index-top-candidates');
        await waitFor(() => expect(within(list).getAllByRole('listitem')).toHaveLength(5));
        expect(within(list).queryByText('표시할 최신 검출 종목이 없습니다.')).toBeNull();
    });

    it('publishes the verified top three in a proportional three-card grid', async () => {
        render(<MiroFishFearIndexCard candidates={scannerCandidates} topResults={workflowTop3} />);

        const section = await screen.findByTestId('fear-index-top-results');
        expect(within(section).getAllByRole('article')).toHaveLength(3);
        expect(within(section).getByText('Top Result 1')).toBeTruthy();
        expect(within(section).getByText('BUY 75%')).toBeTruthy();
        expect(within(section).getByText('L 10414')).toBeTruthy();
        expect(within(section).getByText('E 20')).toBeTruthy();
        expect(within(section).getByText('R 10')).toBeTruthy();
        expect(within(section).getAllByText('Replay-safe after 2026-07-21')).toHaveLength(3);
    });
});
