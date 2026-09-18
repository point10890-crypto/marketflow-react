/**
 * 관리자 대시보드 "전환 퍼널 (30일)" 카드 — /api/admin/funnel/summary 집계를 숫자로만 보여준다.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import DashboardTab from '@/pages/admin/tabs/DashboardTab';

const mocks = vi.hoisted(() => ({
    getFunnelSummary: vi.fn(),
    getNotifications: vi.fn(),
    getUnreadCount: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
    adminAPI: {
        getFunnelSummary: mocks.getFunnelSummary,
        getNotifications: mocks.getNotifications,
        getUnreadCount: mocks.getUnreadCount,
        markRead: vi.fn(),
        markAllRead: vi.fn(),
    },
}));

function renderTab() {
    return render(
        <MemoryRouter>
            <DashboardTab data={null} onNavigate={() => {}} apiToken="tok" />
        </MemoryRouter>,
    );
}

describe('DashboardTab 전환 퍼널 카드', () => {
    beforeEach(() => {
        mocks.getNotifications.mockResolvedValue({ notifications: [], total: 0, page: 1, total_pages: 1 });
        mocks.getUnreadCount.mockResolvedValue({ unread_count: 0 });
    });

    it('places the funnel and seven working shortcuts before the action queue', async () => {
        mocks.getFunnelSummary.mockResolvedValue(null);
        const onNavigate = vi.fn();
        render(<MemoryRouter><DashboardTab data={null} onNavigate={onNavigate} /></MemoryRouter>);
        const nav = screen.getByRole('navigation', { name: '관리 바로가기' });
        const buttons = within(nav).getAllByRole('button');
        expect(buttons.map(button => button.textContent)).toEqual([
            '대시보드', '사용자', '구독', '구매', 'Pro 관리', '시스템', '잡 상태',
        ]);
        const funnel = screen.getByTestId('funnel-card');
        const queue = screen.getByText('오늘 처리할 일');
        expect(funnel.compareDocumentPosition(nav) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(nav.compareDocumentPosition(queue) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        buttons.forEach(button => fireEvent.click(button));
        expect(onNavigate.mock.calls.map(call => call[0])).toEqual([
            'dashboard', 'users', 'subscriptions', 'purchases', 'pro', 'system', 'jobs',
        ]);
        await waitFor(() => expect(screen.getByText('알림이 없습니다')).toBeInTheDocument());
    });

    it('집계 응답의 고유 회원 수 · 전환율 · 승인 소요 중앙값을 표시한다', async () => {
        mocks.getFunnelSummary.mockResolvedValue({
            days: 30,
            since: '2026-08-04T00:00:00+00:00',
            counts: { register: 12, subscription_request: 6, approve: 4, reject: 1, tier_grant: 1 },
            users: { registered: 12, requested: 6, approved: 5 },
            conversion: { register_to_request: 0.5, request_to_approve: 0.8333, register_to_approve: 0.4167 },
            median_request_to_approve_hours: 3.5,
            approved_requests_sampled: 4,
        });
        renderTab();

        const card = await screen.findByTestId('funnel-card');
        expect(card).toHaveTextContent('전환 퍼널 (30일)');
        await waitFor(() => expect(card).toHaveTextContent('가입→신청 50%'));
        expect(card).toHaveTextContent('신청→승인 83%');
        expect(card).toHaveTextContent('3.5h');
        expect(card).toHaveTextContent('표본 4');
        expect(mocks.getFunnelSummary).toHaveBeenCalledWith(30, 'tok');
    });

    it('집계 실패 시에도 카드는 0 과 "-" 로 렌더되고 대시보드가 깨지지 않는다', async () => {
        mocks.getFunnelSummary.mockRejectedValue(new Error('offline'));
        renderTab();

        const card = await screen.findByTestId('funnel-card');
        expect(card).toHaveTextContent('집계 대기');
        expect(card).toHaveTextContent('가입→신청 -');
        expect(card).toHaveTextContent('신청→승인 -');
    });
});
