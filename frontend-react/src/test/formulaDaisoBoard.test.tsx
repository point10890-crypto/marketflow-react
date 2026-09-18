import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import { FORMULA_BOARDS, getFormulaBoard, isFormulaBoardSlug } from '@/lib/formulaBoards';

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: { id: 1, role: 'admin', tier: 'premium', status: 'approved' } }),
}));

const { getPosts, search } = vi.hoisted(() => ({ getPosts: vi.fn(), search: vi.fn() }));
vi.mock('@/lib/api', async () => {
    const actual = await vi.importActual<typeof import('@/lib/api')>('@/lib/api');
    return {
        ...actual,
        communityAPI: { ...actual.communityAPI, getPosts, search },
    };
});

import FormulaListPage from '@/pages/community/FormulaListPage';

describe('formulaBoards config', () => {
    it('수식 다이소는 3만원 균일가, 수식마켓은 자유 가격', () => {
        expect(FORMULA_BOARDS['formula-daiso'].fixedPrice).toBe(30000);
        expect(FORMULA_BOARDS['formula-market'].fixedPrice).toBeNull();
        expect(isFormulaBoardSlug('formula-daiso')).toBe(true);
        expect(isFormulaBoardSlug('free-talk')).toBe(false);
        expect(getFormulaBoard(undefined)).toBeNull();
    });
});

describe('FormulaListPage (formula-daiso)', () => {
    beforeEach(() => {
        getPosts.mockReset();
        getPosts.mockResolvedValue({
            posts: [{
                id: 7, board_id: 9, title: '거래량 급증 조건식', content: '<p>설명</p>', price: '30000',
                created_at: '2026-09-18T01:00:00Z', is_notice: false, view_count: 0, comment_count: 0, like_count: 0,
                author: { id: 1, name: '관리자', tier: 'premium' },
            }],
            notices: [], total: 1, page: 1, total_pages: 1,
        });
    });

    it('다이소 슬러그로 목록을 조회하고 균일가 배지와 등록 링크를 렌더한다', async () => {
        render(
            <MemoryRouter>
                <FormulaListPage boardSlug="formula-daiso" />
            </MemoryRouter>,
        );

        await waitFor(() => expect(getPosts).toHaveBeenCalledWith('formula-daiso', 1));
        expect(await screen.findByText('수식 다이소')).toBeInTheDocument();
        expect(screen.getByText('30,000원 균일가')).toBeInTheDocument();
        expect(screen.getByText('거래량 급증 조건식')).toBeInTheDocument();
        expect(screen.getByText('균일가')).toBeInTheDocument();
        expect(screen.getByText('균일가 수식 등록')).toBeInTheDocument();
    });

    it('기본값은 기존 수식마켓 동작을 유지한다', async () => {
        render(
            <MemoryRouter>
                <FormulaListPage />
            </MemoryRouter>,
        );
        await waitFor(() => expect(getPosts).toHaveBeenCalledWith('formula-market', 1));
        expect(await screen.findByText('수식 마켓')).toBeInTheDocument();
        expect(screen.queryByText('30,000원 균일가')).not.toBeInTheDocument();
    });
});
