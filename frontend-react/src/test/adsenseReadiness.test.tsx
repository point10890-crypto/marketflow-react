import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const auth = vi.hoisted(() => ({ user: null as Record<string, unknown> | null }));
vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: auth.user, loading: false }),
    AuthProvider: ({ children }: { children: unknown }) => children,
}));
vi.mock('@/contexts/NotificationContext', () => ({
    NotificationProvider: ({ children }: { children: unknown }) => children,
}));
import App from '@/App';
vi.mock('@/pages/auth/PlanSelectPage', () => ({ default: () => <h1>플랜 선택</h1> }));

describe('public review readiness', () => {
    beforeEach(() => { auth.user = null; });

    it.each([
        null,
        { status: 'pending', tier: null },
        { status: 'expired', tier: 'pro' },
    ])('keeps educational articles readable regardless of subscription: %j', async (user) => {
        auth.user = user;
        window.history.replaceState({}, '', '/guide/using-ai-signals');
        render(<App />);
        expect(await screen.findByRole('heading', { level: 1, name: /AI 시장 분석, 어떻게 활용해야 하나/ })).toBeInTheDocument();
        expect(window.location.pathname).toBe('/guide/using-ai-signals');
        expect(document.querySelector('.adsbygoogle')).toBeNull();
    });

    it('retains ownership verification without starting advertising on every route', () => {
        const template = readFileSync(resolve(__dirname, '../../index.html'), 'utf8');
        const doc = new DOMParser().parseFromString(template, 'text/html');
        expect(doc.querySelector('meta[name="google-adsense-account"]')?.getAttribute('content'))
            .toBe('ca-pub-4268071335236139');
        expect(doc.querySelector('script[src*="adsbygoogle"]')).toBeNull();
    });
});
