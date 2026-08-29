import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import RagStatusCard from '@/pages/dashboard/aibain/RagStatusCard';

const mockApi = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: mockApi.fetchAuthAPI }));
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 1, tier: 'pro' }, token: 't' }),
}));

const status = {
  graph: {
    entities: 248, relations: 512,
    entity_types: { metric: 115, event: 28, company: 27, asset: 24 },
    top_relations: [{ relation: 'related_to', count: 270 }, { relation: 'impacts', count: 106 }],
    updated_at: '2026-08-29T00:00:00+00:00',
  },
  news: {
    total: 26, last_24h: 26, last_collected_at: new Date().toISOString(),
    by_grade: { B: 26 }, by_source: { yonhap_economy: 18, mk_economy: 8 }, stale: false,
  },
  coverage: { symbols: 12, top_symbols: [{ symbol: '005930', count: 5 }] },
  errors: {},
};

describe('RagStatusCard', () => {
  beforeEach(() => mockApi.fetchAuthAPI.mockReset());

  it('지식그래프 규모와 커버리지를 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(status);
    render(<RagStatusCard />);
    await waitFor(() => expect(screen.getByText('248')).toBeInTheDocument());
    expect(screen.getByText('관계 512')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();      // 커버리지 종목 수
    expect(screen.getByText('005930')).toBeInTheDocument();  // 최근 언급 상위
  });

  it('엔티티 타입을 한국어 라벨로 보여준다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue(status);
    render(<RagStatusCard />);
    await waitFor(() => expect(screen.getByText('지표')).toBeInTheDocument());
    expect(screen.getByText('기업')).toBeInTheDocument();
    expect(screen.getByText('연관')).toBeInTheDocument();    // 관계 라벨
  });

  it('수집 이력이 없으면 안내로 대체한다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({
      ...status,
      news: { ...status.news, total: 0, last_24h: 0, last_collected_at: null,
              by_source: {}, stale: true },
      coverage: { symbols: 0, top_symbols: [] },
    });
    render(<RagStatusCard />);
    await waitFor(() => expect(screen.getByText(/아직 수집된 뉴스가 없습니다/)).toBeInTheDocument());
    expect(screen.getByText(/수집 이력 없음/)).toBeInTheDocument();
  });

  it('응답이 계약과 다르면 안내로 폴백한다', async () => {
    mockApi.fetchAuthAPI.mockResolvedValue({ nope: true });
    render(<RagStatusCard />);
    await waitFor(() =>
      expect(screen.getByText(/현황을 불러오지 못했습니다/)).toBeInTheDocument());
  });
});
