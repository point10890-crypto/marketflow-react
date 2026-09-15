import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import PublicPostPage from '@/pages/public/PublicPostPage';

vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: null, loading: false }) }));
vi.mock('@/lib/api', () => ({
    API_BASE: 'https://marketflow-api.bit-man.net',
    publicCommunityAPI: { getPost: vi.fn().mockResolvedValue({
        post: { id: 226, title: '관찰 기록', content: '<img src="/api/community/uploads/sample.png" alt="분석 그림" onerror="alert(1)">',
            created_at: '2026-09-15', author_name: '작성자', board: { slug: 'analysis' } }, comments: [],
    }) },
}));

describe('public community reading', () => {
    it('serves uploaded images from the API host and strips unsafe attributes without ads', async () => {
        render(<MemoryRouter initialEntries={['/community/post/226']}>
            <Routes><Route path="/community/post/:postId" element={<PublicPostPage />} /></Routes>
        </MemoryRouter>);
        const image = await screen.findByRole('img', { name: '분석 그림' });
        expect(image).toHaveAttribute('src', 'https://marketflow-api.bit-man.net/api/community/uploads/sample.png');
        expect(image).not.toHaveAttribute('onerror');
        expect(document.querySelector('.adsbygoogle')).toBeNull();
    });
});
