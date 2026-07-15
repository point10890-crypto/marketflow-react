import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AiBainPage from '@/pages/dashboard/AiBainPage';

const mocks = vi.hoisted(() => ({
  auth: {
    user: {
      id: 7,
      email: 'renew@example.com',
      name: '재구독회원',
      tier: 'pro',
      role: 'user',
      status: 'approved',
      is_pro_expired: false,
      is_aibain_active: false,
      is_aibain_expired: true,
      aibain_expires_at: '2026-07-01T00:00:00',
    },
    token: 'test-token',
  },
  getStatus: vi.fn(),
  requestAibain: vi.fn(),
}));

vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => mocks.auth,
}));

vi.mock('@/lib/api', () => ({
  subscriptionAPI: {
    getStatus: mocks.getStatus,
    requestAibain: mocks.requestAibain,
  },
}));

vi.mock('@/pages/admin/AdminEndpointsPage', () => ({
  default: () => <div>AI Brain console</div>,
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<AiBainPage />} />
        <Route path="/pending-approval" element={<div>승인 상태 페이지</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AI Brain expired subscription workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.assign(mocks.auth.user, {
      name: '재구독회원',
      tier: 'pro',
      is_aibain_active: false,
      is_aibain_expired: true,
      aibain_expires_at: '2026-07-01T00:00:00',
    });
    mocks.getStatus.mockResolvedValue({
      user: mocks.auth.user,
      requests: [],
      aibain_subscription: {
        state: 'expired',
        is_active: false,
        is_expired: true,
        renewal_eligible: true,
        expires_at: '2026-07-01T00:00:00',
        pending_request: null,
        has_other_pending_request: false,
      },
    });
    mocks.requestAibain.mockResolvedValue({
      request: { id: 19, request_type: 'aibain_renewal', status: 'pending' },
    });
  });

  it('shows an explicit renewal CTA and submits an AI Brain-only renewal', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'AI Brain 재구독 신청' })).toBeInTheDocument();
    expect(screen.getByText(/이전 이용 만료일/)).toBeInTheDocument();
    expect(screen.getByText(/Pro 잔여기간 카운터는 자동으로 재개됩니다/)).toBeInTheDocument();
    expect(screen.getAllByText('40,000원').length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /AI Brain 재구독 신청/ }));

    await waitFor(() => {
      expect(mocks.requestAibain).toHaveBeenCalledWith('pro', 'test-token', '재구독회원');
    });
    expect(await screen.findByText('승인 상태 페이지')).toBeInTheDocument();
  });

  it('shows the existing renewal request instead of allowing duplicate submission', async () => {
    mocks.getStatus.mockResolvedValue({
      user: mocks.auth.user,
      requests: [{
        id: 21,
        request_type: 'aibain_renewal',
        status: 'pending',
        amount: '40,000원',
        depositor_name: '재구독회원',
      }],
    });

    renderPage();

    expect(await screen.findByRole('heading', { name: 'AI Brain 재구독 승인 대기 중' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /AI Brain 재구독 신청/ })).not.toBeInTheDocument();
    expect(mocks.requestAibain).not.toHaveBeenCalled();
  });

  it('keeps Ultra Pro visible after expiry and allows AI Brain-only renewal', async () => {
    Object.assign(mocks.auth.user, {
      name: '울트라재구독',
      tier: 'premium',
    });
    mocks.getStatus.mockResolvedValue({
      user: mocks.auth.user,
      requests: [],
      aibain_subscription: {
        state: 'expired',
        is_active: false,
        is_expired: true,
        renewal_eligible: true,
        expires_at: '2026-07-01T00:00:00',
        pending_request: null,
        has_other_pending_request: false,
      },
    });

    renderPage();

    expect(await screen.findByText(/Ultra Pro 무기한 이용권은 계속 유지됩니다/)).toBeInTheDocument();
    expect(screen.getByText('현재 Ultra Pro 구독')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /AI Brain 재구독 신청/ }));

    await waitFor(() => {
      expect(mocks.requestAibain).toHaveBeenCalledWith('premium', 'test-token', '울트라재구독');
    });
    expect(await screen.findByText('승인 상태 페이지')).toBeInTheDocument();
  });
});
