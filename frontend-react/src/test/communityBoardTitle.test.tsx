import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, useLocation } from 'react-router-dom';
import CommunityPage from '@/pages/community/CommunityPage';

const { getBoards } = vi.hoisted(() => ({ getBoards: vi.fn() }));
vi.mock('@/lib/api', () => ({ communityAPI: { getBoards } }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: 'admin' } }) }));
function CurrentPath() { const location = useLocation(); return <output aria-label="현재 경로">{location.pathname}</output>; }

const premiumTitle = '프리미엄 수식/조건검색식 마켓';
describe('canonical premium formula-market community title', () => {
    beforeEach(() => {
        window.localStorage.clear();
        getBoards.mockReset();
        getBoards.mockResolvedValue([
            { id: 6, slug: 'formula-market', name: '수식/ 조건검색식 마켓', description: '수식 거래', min_tier: 'pro', can_read: true, post_count: 7, latest_post_at: new Date().toISOString() },
            { id: 9, slug: 'formula-daiso', name: '수식 다이소 (3만원 균일가)', description: '균일가', min_tier: 'aibain', can_read: true, post_count: 3, latest_post_at: new Date().toISOString() },
            { id: 1, slug: 'notice', name: '운영팀 공지사항', description: '공지', min_tier: 'free', can_read: true, post_count: 2 },
        ]);
    });

    it('uses the canonical premium heading and NEW label for a legacy API name while retaining its route and count', async () => {
        render(<MemoryRouter initialEntries={['/dashboard/community']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><CommunityPage /><CurrentPath /></MemoryRouter>);
        const title = await screen.findByRole('heading', { level: 3, name: premiumTitle });
        expect(screen.queryByRole('heading', { name: '수식/ 조건검색식 마켓' })).not.toBeInTheDocument();
        expect(screen.getByLabelText(`${premiumTitle} new post`)).toBeInTheDocument();
        expect(title.closest('button')).toHaveAttribute('data-board', 'formula-market');
        expect(title.closest('button')).toHaveTextContent('7개 글');
        await userEvent.click(title);
        expect(screen.getByLabelText('현재 경로')).toHaveTextContent('/dashboard/community/formula-market');
    });

    it('preserves API names and NEW labels for formula-daiso and other boards', async () => {
        render(<MemoryRouter><CommunityPage /></MemoryRouter>);
        expect(await screen.findByRole('heading', { level: 3, name: '수식 다이소 (3만원 균일가)' })).toBeInTheDocument();
        expect(screen.getByLabelText('수식 다이소 (3만원 균일가) new post')).toBeInTheDocument();
        expect(screen.getByRole('heading', { level: 3, name: '운영팀 공지사항' })).toBeInTheDocument();
    });
});
