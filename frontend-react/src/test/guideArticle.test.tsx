import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { GuideArticlePage } from '@/pages/public/GuidePages';

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: null, loading: false }),
}));

const slugs = [
    'vcp-pattern-basics', 'supply-demand-reading', 'market-regime-guide',
    'closing-bet-explained', 'position-sizing-r', 'dart-disclosure-reading', 'using-ai-signals',
];

describe('guide provenance visible to readers and search engines', () => {
    it.each(slugs)('keeps publication history and usable source links on %s', (slug) => {
        render(
            <MemoryRouter initialEntries={[`/guide/${slug}`]}>
                <Routes><Route path="/guide/:slug" element={<GuideArticlePage />} /></Routes>
            </MemoryRouter>,
        );

        const article = screen.getByRole('article');
        expect(within(article).getByText('최초 게시: 2026-08-27')).toBeInTheDocument();
        expect(within(article).getByText('내용 보강: 2026-09-05')).toBeInTheDocument();
        const references = within(article).getByRole('region', { name: '출처와 작성 방법' });
        const links = within(references).getAllByRole('link');
        expect(links.length).toBeGreaterThan(0);
        for (const link of links) {
            expect(link).toHaveAttribute('href', expect.stringMatching(/^https:\/\//));
            expect(link.textContent?.trim()).not.toBe('');
        }
        const schema = [...document.querySelectorAll('script[type="application/ld+json"]')]
            .flatMap((script) => JSON.parse(script.textContent || '[]'))
            .find((entry) => entry['@type'] === 'Article');
        expect(schema).toMatchObject({
            datePublished: '2026-08-27', dateModified: '2026-09-05',
            mainEntityOfPage: `https://bit-man.net/guide/${slug}`,
        });
        expect(schema.citation).toEqual(links.map((link) => link.getAttribute('href')));
    });
});
