import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ServiceGuardCard from '@/pages/dashboard/aibain/ServiceGuardCard';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));

vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, role: 'admin' }, token: 't' }),
}));

const payload = {
  generated_at: '2026-09-02T01:00:00+00:00',
  overall: 'ok',
  services: {
    scanner: { status: 'ok', detail: { latest_run_age_h: 2.5 } },
    decision: { status: 'warn', detail: { probe_s: 1.2, slowest_source: 'news' } },
  },
};

describe('ServiceGuardCard', () => {
  beforeEach(() => { mockApi.fetchAuthAPI.mockReset(); });

  it('첫 프로브가 실패하면(권한 없음/미배포) 카드를 그리지 않는다', async () => {
    mockApi.fetchAuthAPI.mockRejectedValue(new Error('403'));
    const { container } = render(<ServiceGuardCard />);
    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalled());
    expect(container.querySelector('section')).toBeNull();
  });

  it('정상 응답이면 서비스별 상태를 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(payload);
    render(<ServiceGuardCard />);
    await waitFor(() => expect(screen.getByText('서비스 가드')).toBeInTheDocument());
    expect(screen.getByText('알파 스캐너')).toBeInTheDocument();
    expect(screen.getByText(/최신 런 2\.5h 전/)).toBeInTheDocument();
  });

  it('새로고침이 한 번 실패해도 마지막 정상 상태를 지우지 않는다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValueOnce(payload);
    render(<ServiceGuardCard />);
    await waitFor(() => expect(screen.getByText('서비스 가드')).toBeInTheDocument());

    // 백엔드 재시작 중 5xx/타임아웃 — 감시 카드가 통째로 사라지면 안 된다
    mockApi.fetchAuthAPI.mockRejectedValueOnce(new Error('backend restarting'));
    await userEvent.click(screen.getByRole('button', { name: '서비스 가드 새로고침' }));
    await waitFor(() => expect(mockApi.fetchAuthAPI).toHaveBeenCalledTimes(2));

    expect(screen.getByText('서비스 가드')).toBeInTheDocument();
    expect(screen.getByText('알파 스캐너')).toBeInTheDocument();
  });
});
