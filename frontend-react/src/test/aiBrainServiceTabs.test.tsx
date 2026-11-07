import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AiBrainServiceTabs from '@/components/aibain/AiBrainServiceTabs';

const auth = vi.hoisted(() => ({ role: 'admin' }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ user: { role: auth.role } }) }));

describe('AI Brain service cards', () => {
    beforeEach(() => { auth.role = 'admin'; });

    it('opens and selects the Kongming validation page inside AI Brain for admins', () => {
        render(<AiBrainServiceTabs active="kongming" />);

        const nav = within(screen.getByRole('navigation', { name: 'AI Brain 서비스' }));
        const kongming = nav.getByRole('link', { name: /뉴스·재료 검증/ });
        expect(kongming).toHaveAttribute('href', '/dashboard/ai-bain/catalyst-validation');
        expect(kongming).not.toHaveAttribute('target');
        expect(kongming).toHaveAttribute('aria-current', 'page');
        const links = nav.getAllByRole('link');
        expect(links).toHaveLength(5);
        expect(links[3]).toHaveAccessibleName(/차트 유사 사례/);
        expect(links[4]).toBe(kongming);
    });

    it('keeps the Kongming card out of the subscriber navigation', () => {
        auth.role = 'user';
        render(<AiBrainServiceTabs active="scanner" />);
        const nav = within(screen.getByRole('navigation', { name: 'AI Brain 서비스' }));
        expect(nav.queryByRole('link', { name: /뉴스·재료 검증/ })).toBeNull();
        expect(nav.getAllByRole('link')).toHaveLength(4);
    });

    it('retains the four local routes and marks only the active local page', () => {
        render(<AiBrainServiceTabs active="chart-predict" />);

        const nav = within(screen.getByRole('navigation', { name: 'AI Brain 서비스' }));
        const links = [
            [/알파 스캐너/, '/dashboard/ai-bain'],
            [/Goodrich TOP 3/, '/dashboard/ai-bain/goodrich'],
            [/종목 판단/, '/dashboard/ai-bain/decision'],
            [/차트 유사 사례/, '/dashboard/ai-bain/chart-predict?code=003690'],
        ] as const;
        for (const [name, href] of links) {
            const link = nav.getByRole('link', { name });
            expect(link).toHaveAttribute('href', href);
            expect(link).not.toHaveAttribute('target');
        }
        expect(nav.getByRole('link', { current: 'page' })).toHaveAccessibleName(/차트 유사 사례/);
    });
});
