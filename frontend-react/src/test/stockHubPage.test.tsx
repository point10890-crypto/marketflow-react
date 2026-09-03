import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import StockHubPage from '@/pages/dashboard/StockHubPage';

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  auth: { user: { id: 1, tier: 'pro', role: 'user', is_aibain_active: false } as any },
}));

vi.mock('@/lib/api', () => ({ stockHubAPI: { get: mocks.get } }));
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => mocks.auth }));
vi.mock('@/components/layout/PullToRefreshProvider', () => ({ usePullToRefreshRegister: () => {} }));
// lightweight-charts 는 jsdom 에 캔버스가 없어 마운트할 수 없다 — 포인트 수만 검증한다.
vi.mock('@/components/stock/CloseLineChart', () => ({
  default: ({ points }: { points: unknown[] }) => <div data-testid="chart" data-points={points.length} />,
}));

const hub = {
  schema_version: 'marketflow.stock_hub.v1',
  generated_at: '2026-09-03T00:00:00',
  code: '005930',
  name: '삼성전자',
  market: 'KOSPI',
  sector: '반도체',
  price: { close: 101300, prev_close: 101290, change_pct: 0.01, date: '2026-09-02', bars: 120, source: 'daily_prices.csv' },
  chart: Array.from({ length: 120 }, (_, i) => ({ date: `2026-01-${String((i % 28) + 1).padStart(2, '0')}`, close: 100000 + i, high: null, low: null, volume: null })),
  sources: {
    jongga: { as_of: '2026-09-02T15:20:00', grade: 'A', score_total: 8, entry_price: 101300, stop_price: 98000, target_price: 106000, change_pct: 4.6, foreign_5d: 1000, inst_5d: 2000 },
    leading: { as_of: '2026-09-02T15:48:00', rank: 13, grade: 'A', score_total: 67, change_pct: 4.65, trading_value_eok: 36091, volume_ratio: 50.4, high_52w_distance_pct: 16.3, market_cap_tier: '대형' },
    vcp: null,
    wave: null,
    claw: null,
  },
  present: ['jongga', 'leading'],
  history: [
    { date: '2026-09-02', grade: 'A', score_total: 8, change_pct: 2, entry_price: 100000, stop_price: 97000, target_price: 105000, outcome: null, roi_pct: null, hold_roi_pct: null, days_held: null },
    { date: '2026-08-27', grade: 'S', score_total: 9, change_pct: 6, entry_price: 100000, stop_price: 97000, target_price: 105000, outcome: 'TARGET_HIT', roi_pct: 5, hold_roi_pct: 6, days_held: 3 },
  ],
  news: [{ title: '삼성전자 신규 수주', link: 'https://example.com/1', source: 'rss', grade: 'B', score: 0.8, published_ts: '2026-09-02T08:00:00', summary: null }],
  errors: {},
  disclaimer: '매수·매도 지시가 아닙니다.',
};

function renderAt(path = '/dashboard/stock/KR/005930') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/dashboard/stock/:market/:code" element={<StockHubPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StockHubPage', () => {
  beforeEach(() => {
    mocks.get.mockReset();
    mocks.auth.user = { id: 1, tier: 'pro', role: 'user', is_aibain_active: false };
  });

  it('URL 의 종목코드로 허브 API 를 호출하고 헤더·차트·소스·이력·뉴스를 그린다', async () => {
    mocks.get.mockResolvedValue(hub);
    renderAt();
    await waitFor(() => expect(mocks.get).toHaveBeenCalledWith('005930'));
    expect(await screen.findByRole('heading', { level: 1, name: '삼성전자' })).toBeInTheDocument();
    expect(screen.getByText('KOSPI')).toBeInTheDocument();
    expect(screen.getByText('101,300원')).toBeInTheDocument();
    expect(screen.getByTestId('chart')).toHaveAttribute('data-points', '120');
    // 소스 카드는 있음/없음을 모두 그린다
    expect(screen.getByTestId('source-jongga')).toHaveAttribute('data-present', '1');
    expect(screen.getByTestId('source-leading')).toHaveAttribute('data-present', '1');
    expect(screen.getByTestId('source-vcp')).toHaveAttribute('data-present', '0');
    expect(screen.getByTestId('source-claw')).toHaveAttribute('data-present', '0');
    expect(screen.getByText('신호 소스 2/5 보유 · 시세 2026-09-02 종가 기준')).toBeInTheDocument();
    // 이력: 추적 결과가 있는 행만 결과 표시, 나머지는 검증 대기
    expect(screen.getByText('목표 도달')).toBeInTheDocument();
    expect(screen.getByText('검증 대기')).toBeInTheDocument();
    // 뉴스 링크
    expect(screen.getByRole('link', { name: '삼성전자 신규 수주' })).toHaveAttribute('href', 'https://example.com/1');
  });

  it('AI Brain 링크는 애드온 활성 사용자에게만 보인다', async () => {
    mocks.get.mockResolvedValue(hub);
    renderAt();
    await screen.findByRole('heading', { level: 1, name: '삼성전자' });
    expect(screen.queryByRole('link', { name: /AI Brain 종목 판단 열기/ })).not.toBeInTheDocument();

    mocks.auth.user = { id: 1, tier: 'pro', role: 'user', is_aibain_active: true };
    renderAt();
    const links = await screen.findAllByRole('link', { name: /AI Brain 종목 판단 열기/ });
    expect(links[0]).toHaveAttribute('href', '/dashboard/ai-bain/decision?symbol=005930');
  });

  it('아티팩트가 없어도 화면이 깨지지 않는다 (null 소스 · 빈 이력)', async () => {
    mocks.get.mockResolvedValue({
      ...hub, name: null, market: null, sector: null, price: null, chart: [],
      sources: { jongga: null, leading: null, vcp: null, wave: null, claw: null },
      present: [], history: [], news: [],
    });
    renderAt();
    expect(await screen.findByRole('heading', { level: 1, name: '005930' })).toBeInTheDocument();
    expect(screen.getByText('신호 소스 0/5 보유 · 시세 없음')).toBeInTheDocument();
    expect(screen.getByText('이 종목의 종가베팅 신호 이력이 없습니다.')).toBeInTheDocument();
    expect(screen.getByText('수집된 뉴스가 없습니다.')).toBeInTheDocument();
  });

  it('API 실패는 배너로 알리고 다시 시도할 수 있다', async () => {
    mocks.get.mockRejectedValue(new Error('down'));
    renderAt();
    expect(await screen.findByRole('alert')).toHaveTextContent('종목 정보를 불러오지 못했습니다');
  });

  it('미국 종목은 허브 대신 분석 도구 링크를 안내한다', () => {
    renderAt('/dashboard/stock/US/AAPL');
    expect(mocks.get).not.toHaveBeenCalled();
    expect(screen.getByRole('link', { name: /ProPicks 분석 열기/ })).toHaveAttribute('href', '/dashboard/stock-analyzer?ticker=AAPL&market=US');
  });
});
