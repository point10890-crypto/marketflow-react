/**
 * ApprovedGuard 하이드레이션 계약 — status='unknown' (토큰만 있고 /api/auth/me 미응답,
 * 오프라인/백엔드 다운 포함) 은 App.tsx 의 no-flicker 설계 주석대로 로딩만 보여주고
 * 절대 /login 으로 튕기지 않는다. 퍼널 리다이렉트는 subscriptionFunnelTarget 기준.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const authState = vi.hoisted(() => ({
    user: null as Record<string, unknown> | null,
    loading: false,
}));

vi.mock('@/contexts/AuthContext', () => ({
    useAuth: () => ({ user: authState.user, loading: authState.loading }),
    AuthProvider: (props: { children?: unknown }) => props.children,
}));

import { ApprovedGuard } from '@/App';

function renderGuarded() {
    return render(
        <MemoryRouter initialEntries={['/dashboard']}>
            <Routes>
                <Route
                    path="/dashboard"
                    element={<ApprovedGuard><div>대시보드 본문</div></ApprovedGuard>}
                />
                <Route path="/login" element={<div>로그인 페이지</div>} />
                <Route path="/plan-select" element={<div>플랜 선택 페이지</div>} />
                <Route path="/pending-approval" element={<div>승인 대기 페이지</div>} />
            </Routes>
        </MemoryRouter>,
    );
}

describe('ApprovedGuard hydration', () => {
    beforeEach(() => {
        authState.user = null;
        authState.loading = false;
    });

    it('status=unknown 유저는 /login 으로 튕기지 않고 로딩만 보여준다', () => {
        authState.user = {
            id: 7, email: '(loading)', name: '...', tier: null, role: 'user', status: 'unknown',
        };
        renderGuarded();
        expect(screen.getByText('Loading...')).toBeInTheDocument();
        expect(screen.queryByText('로그인 페이지')).toBeNull();
        expect(screen.queryByText('대시보드 본문')).toBeNull();
    });

    it('비로그인(user=null) 방문자는 여전히 /login 으로 보낸다', () => {
        renderGuarded();
        expect(screen.getByText('로그인 페이지')).toBeInTheDocument();
    });

    it('구독 신청 제출 후 승인 대기 회원(requested_tier, tier=null)은 승인 대기로 보낸다', () => {
        authState.user = {
            id: 8, email: 'u@example.test', name: 'U', role: 'user',
            status: 'pending', tier: null, requested_tier: 'pro',
        };
        renderGuarded();
        expect(screen.getByText('승인 대기 페이지')).toBeInTheDocument();
    });

    it('활성 Pro 구독자는 대시보드 본문을 그대로 렌더한다', () => {
        authState.user = {
            id: 9, email: 'p@example.test', name: 'P', role: 'user',
            status: 'approved', tier: 'pro', is_pro_expired: false,
        };
        renderGuarded();
        expect(screen.getByText('대시보드 본문')).toBeInTheDocument();
    });
});
