import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import GoodrichTop3Charts from '@/components/aibain/GoodrichTop3Charts';

const picks = [
    { rank: 1, symbol: '068270', name: '셀트리온', score: 69.03 },
    { rank: 2, symbol: '035720', name: '카카오', score: 67.89 },
    { rank: 3, symbol: '035420', name: 'NAVER', score: 62.97 },
];

describe('GoodrichTop3Charts', () => {
    it('renders three real symbol charts and switches chart periods', () => {
        render(<GoodrichTop3Charts picks={picks} />);

        expect(screen.getByRole('heading', { name: 'TOP 3 종목 차트' })).toBeTruthy();
        expect(screen.getAllByRole('img')).toHaveLength(3);
        expect(screen.getByAltText('셀트리온 day 캔들 차트')).toHaveAttribute(
            'src',
            expect.stringContaining('/candle/day/068270.png'),
        );

        fireEvent.click(screen.getByRole('button', { name: '주봉' }));

        expect(screen.getByAltText('셀트리온 week 캔들 차트')).toHaveAttribute(
            'src',
            expect.stringContaining('/candle/week/068270.png'),
        );
    });
});
