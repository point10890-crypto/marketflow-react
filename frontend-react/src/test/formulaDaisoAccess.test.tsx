import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import CommunityPage from '@/pages/community/CommunityPage';

const { getBoards } = vi.hoisted(() => ({ getBoards: vi.fn() }));
vi.mock('@/lib/api', () => ({ communityAPI: { getBoards } }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: 'user' } }) }));

describe('AI Brain 전용 수식 다이소 카드', () => {
    beforeEach(() => window.localStorage.clear());

    it.each([false, true])('서버 접근 권한 %s를 카드에 반영한다', async (canRead) => {
        getBoards.mockResolvedValue([{
            id: 9, slug: 'formula-daiso', name: '수식 다이소 (3만원 균일가)',
            description: '3만원 균일가', min_tier: 'aibain', can_read: canRead, post_count: 0,
        }]);
        render(<MemoryRouter><CommunityPage /></MemoryRouter>);
        const card = await screen.findByRole('button', { name: /수식 다이소/ });
        expect(screen.getByText('AI Brain')).toBeInTheDocument();
        if (canRead) expect(card).toBeEnabled();
        else {
            expect(card).toBeDisabled();
            expect(screen.getByText('AI Brain 구독자 전용')).toBeInTheDocument();
        }
    });
});
