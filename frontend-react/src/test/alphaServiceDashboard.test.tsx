import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

import AlphaServiceDashboard from '@/components/admin/AlphaServiceDashboard';

const mockGetDashboard = vi.hoisted(() => vi.fn());

vi.mock('@/lib/mirofishApi', async () => {
  const actual = await vi.importActual<typeof import('@/lib/mirofishApi')>('@/lib/mirofishApi');
  return {
    ...actual,
    mirofishApi: { ...actual.mirofishApi, getAlphaServiceDashboard: mockGetDashboard },
  };
});

const dashboard = {
  schema_version: 'mirofish.alpha_service_dashboard.v1',
  generated_at: '2026-08-20T08:40:00+09:00',
  timezone: 'Asia/Seoul',
  date_kst: '2026-08-20',
  status: 'ready',
  warnings: [],
  links: {},
  services: [
    {
      id: 'market_brief', order: 1, title: '전일 시장 정리',
      description: '시장 국면과 시장 폭을 확인합니다.',
      schedule: { label: '오전 8시', time_kst: '08:00', phase: 'elapsed', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-19', summary: '상승 추세 확산',
      metrics: [{ key: 'breadth', label: '시장 폭', value: 54.2, unit: '%', tone: 'neutral' }],
      items: [], warnings: [], provenance: { sources: [] },
    },
    {
      id: 'score_leaders', order: 2, title: '알파스코어 상위 종목',
      description: '최근 비어 있지 않은 스캔 후보입니다.',
      schedule: { label: '오전 8시 30분', time_kst: '08:30', phase: 'due', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:30:00+09:00', summary: '1개 후보',
      metrics: [],
      items: [{ rank: 1, symbol: '005930', name: '삼성전자', market: 'KOSPI', alpha_score: 87.4, risk_score: 21, action: 'BUY_CANDIDATE', horizon: '5d', price: 71500 }],
      warnings: [], provenance: { sources: [{ source: 'latest_nonempty_run', run_id: 'mfas_20260820_0830', as_of: '2026-08-20T08:30:00+09:00', freshness: 'fresh', fallback: false }] },
    },
    {
      id: 'intraday_flow', order: 3, title: '장중 종목 흐름 체크',
      description: '마지막 저장 종가 기준 포지션입니다.',
      schedule: { label: '장중', time_kst: null, phase: 'due', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-19', summary: '1개 포지션', metrics: [],
      items: [{ symbol: '005930', name: '삼성전자', entry_price: 70000, last_close: 71500, last_close_date: '2026-08-19', unrealized_pct: 2.14, held_trading_days: 2, target_price: 75600, stop_price: 65100 }],
      warnings: [], provenance: { sources: [] },
    },
    {
      id: 'trade_signals', order: 4, title: '당일 매매 신호',
      description: '가상 매매와 파이프라인 상태입니다.',
      schedule: { label: '오후 3시', time_kst: '15:00', phase: 'upcoming', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:40:00+09:00', summary: '대기 1건', metrics: [],
      items: [{ key: 'pending', label: '진입 대기', count: 1, window_days: null, status: 'waiting' }],
      warnings: [], provenance: { sources: [] },
    },
    {
      id: 'performance_brief', order: 5, title: '최근 성과 브리핑',
      description: '두 성과 표본을 분리해 봅니다.',
      schedule: { label: '오후 6시', time_kst: '18:00', phase: 'upcoming', calendar_status: 'unverified' },
      data_status: 'ready', as_of: '2026-08-20T08:40:00+09:00', summary: '성과 표본 10건', metrics: [],
      items: [
        { source: 'paper_30d', sample_count: 4, window_days: 30, win_rate: 75, average_return_pct: 2.5, cumulative_return_pct: 10.2, hit_count: null, miss_count: null },
        { source: 'workflow_outcomes', sample_count: 6, window_days: 30, win_rate: 66.67, average_return_pct: 3.1, cumulative_return_pct: null, hit_count: 4, miss_count: 2 },
      ],
      warnings: [], provenance: { sources: [] },
    },
  ],
} as const;

beforeEach(() => {
  mockGetDashboard.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    value: 'visible',
  });
});

it('renders the five source-backed services in server order', async () => {
  mockGetDashboard.mockResolvedValue(dashboard);
  render(<AlphaServiceDashboard />);

  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  const headings = within(region).getAllByRole('heading', { level: 3 }).map(node => node.textContent);
  expect(headings).toEqual([
    '전일 시장 정리', '알파스코어 상위 종목', '장중 종목 흐름 체크',
    '당일 매매 신호', '최근 성과 브리핑',
  ]);
  expect(within(region).getByText('005930 · KOSPI')).toBeInTheDocument();
  expect(within(region).getByText('latest_nonempty_run · fresh')).toBeInTheDocument();
  expect(within(region).getByText(/run mfas_20260820_0830/)).toBeInTheDocument();
  expect(within(region).getByText('+2.14%')).toBeInTheDocument();
  expect(within(region).getByText('표본 6건')).toBeInTheDocument();
  expect(within(region).getByText('66.67%')).toBeInTheDocument();
  expect(within(region).queryByText('+66.67%')).not.toBeInTheDocument();

  const scoreCard = within(region).getByRole('heading', { name: '알파스코어 상위 종목' }).closest('article');
  const intradayCard = within(region).getByRole('heading', { name: '장중 종목 흐름 체크' }).closest('article');
  const tradeCard = within(region).getByRole('heading', { name: '당일 매매 신호' }).closest('article');
  const performanceCard = within(region).getByRole('heading', { name: '최근 성과 브리핑' }).closest('article');
  expect(scoreCard).not.toBeNull();
  expect(intradayCard).not.toBeNull();
  expect(tradeCard).not.toBeNull();
  expect(performanceCard).not.toBeNull();
  expect(within(scoreCard!).getByText('BUY_CANDIDATE')).toBeInTheDocument();
  expect(within(scoreCard!).getByText('5d')).toBeInTheDocument();
  expect(within(scoreCard!).getByText(/71,500/)).toBeInTheDocument();
  expect(within(intradayCard!).getByText(/목표 75,600/)).toBeInTheDocument();
  expect(within(intradayCard!).getByText(/손절 65,100/)).toBeInTheDocument();
  expect(within(tradeCard!).getByText('waiting')).toBeInTheDocument();
  expect(within(performanceCard!).getAllByText('30일').length).toBe(2);
  expect(within(performanceCard!).getByText('Hit 4 · Miss 2')).toBeInTheDocument();

  const dataStatus = within(scoreCard!).getByLabelText('데이터 상태: 준비됨');
  expect(dataStatus).toHaveTextContent('준비됨');
  expect(dataStatus.querySelector('[aria-hidden="true"]')).not.toBeNull();
  expect(region.className).not.toContain('shadow-[');
  expect(region.querySelector('[data-alpha-current-marker]')?.className).toContain('shadow-[');
  expect(Array.from(region.querySelectorAll<HTMLElement>('[class]')).some(node => /text-\[(?:9|10|11)px\]/.test(node.className))).toBe(false);
});

it('keeps global and card warnings scoped and does not present informational notices as errors', async () => {
  const globalWarning = { section: 'dashboard', code: 'source_summary', message: '전체 소스 점검이 필요합니다.', severity: 'warning' } as const;
  const intradayWarning = { section: 'paper_overview', code: 'source_read_failed', message: '포지션 데이터를 읽지 못했습니다.', severity: 'error' } as const;
  const marketInfo = { section: 'market_brief', code: 'leading_sectors_unavailable', message: '검증된 주도 업종 소스가 없습니다.', severity: 'info' } as const;
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    warnings: [globalWarning, globalWarning, intradayWarning],
    services: dashboard.services.map(service => {
      if (service.id === 'market_brief') return { ...service, warnings: [marketInfo] };
      if (service.id === 'intraday_flow') return { ...service, data_status: 'partial', warnings: [intradayWarning] };
      return service;
    }),
  });

  render(<AlphaServiceDashboard />);
  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  // region 은 로딩 스켈레톤 단계에서도 존재하므로, 데이터 렌더 완료는 findBy 로 기다린다
  // (느린 CI 러너에서 mockResolvedValue 해소 전에 getBy 가 실행되는 경합 방지).
  const globalAlert = await within(region).findByRole('alert', { name: '전체 서비스 경고' });
  expect(globalAlert).toHaveTextContent('전체 소스 점검이 필요합니다.');
  expect(globalAlert).not.toHaveTextContent('포지션 데이터를 읽지 못했습니다.');
  expect(within(globalAlert).getAllByText(/전체 소스 점검이 필요합니다\./)).toHaveLength(1);

  const marketCard = within(region).getByRole('heading', { name: '전일 시장 정리' }).closest('article')!;
  const intradayCard = within(region).getByRole('heading', { name: '장중 종목 흐름 체크' }).closest('article')!;
  expect(within(marketCard).getByRole('status')).toHaveTextContent('검증된 주도 업종 소스가 없습니다.');
  expect(within(marketCard).queryByRole('alert')).not.toBeInTheDocument();
  expect(within(intradayCard).getByRole('alert')).toHaveTextContent('포지션 데이터를 읽지 못했습니다.');
  expect(within(region).getAllByText(/포지션 데이터를 읽지 못했습니다\./)).toHaveLength(1);
});

it('hides unrealized return and warns when the stored close date is unknown', async () => {
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    services: dashboard.services.map(service => service.id === 'intraday_flow'
      ? { ...service, items: service.items.map(item => ({ ...item, last_close_date: null })) }
      : service),
  });

  render(<AlphaServiceDashboard />);
  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  const intradayCard = within(region).getByRole('heading', { name: '장중 종목 흐름 체크' }).closest('article')!;
  expect(within(intradayCard).queryByText('+2.14%')).not.toBeInTheDocument();
  expect(within(intradayCard).getByRole('alert')).toHaveTextContent('저장 가격 기준일을 확인할 수 없습니다.');
});

it('renders nullable candidate identity and performance windows without placeholder strings', async () => {
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    services: dashboard.services.map(service => {
      if (service.id === 'score_leaders') return {
        ...service,
        items: service.items.map(item => ({
          ...item, rank: null, name: null, market: null, action: null, horizon: null,
        })),
      };
      if (service.id === 'performance_brief') return {
        ...service,
        items: service.items.map((item, index) => index === 0 ? { ...item, window_days: null } : item),
      };
      return service;
    }),
  });

  render(<AlphaServiceDashboard />);
  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  const scoreCard = within(region).getByRole('heading', { name: '알파스코어 상위 종목' }).closest('article')!;
  const performanceCard = within(region).getByRole('heading', { name: '최근 성과 브리핑' }).closest('article')!;
  expect(within(scoreCard).getByText('—')).toBeInTheDocument();
  expect(scoreCard).toHaveTextContent('005930');
  expect(scoreCard).not.toHaveTextContent('BUY_CANDIDATE');
  expect(scoreCard).not.toHaveTextContent('5d');
  expect(scoreCard).not.toHaveTextContent('null');
  expect(within(performanceCard).getAllByText('30일')).toHaveLength(1);
  expect(performanceCard).not.toHaveTextContent('null일');
});

it('renders malformed-source null counts as unknown instead of bare count units', async () => {
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    status: 'partial',
    services: dashboard.services.map(service => {
      if (service.id === 'trade_signals') return {
        ...service,
        data_status: 'partial',
        items: service.items.map(item => ({ ...item, count: null })),
      };
      if (service.id === 'performance_brief') return {
        ...service,
        data_status: 'partial',
        items: service.items.map(item => ({ ...item, sample_count: null })),
      };
      return service;
    }),
  });

  render(<AlphaServiceDashboard />);
  const region = await screen.findByRole('region', { name: 'Alpha Service Clock' });
  const tradeCard = within(region).getByRole('heading', { name: '당일 매매 신호' }).closest('article')!;
  const performanceCard = within(region).getByRole('heading', { name: '최근 성과 브리핑' }).closest('article')!;
  expect(within(tradeCard).getByText('—')).toBeInTheDocument();
  expect(within(tradeCard).queryByText('건')).not.toBeInTheDocument();
  expect(within(performanceCard).getAllByText('표본 없음')).toHaveLength(2);
  expect(within(performanceCard).queryByText(/0%/)).not.toBeInTheDocument();
});

it('distinguishes stale partial and empty without presenting zero samples as success', async () => {
  mockGetDashboard.mockResolvedValue({
    ...dashboard,
    status: 'partial',
    warnings: [{ section: 'paper_overview', code: 'source_read_failed', message: '포지션 데이터를 읽지 못했습니다.', severity: 'error' }],
    services: dashboard.services.map(service => {
      if (service.id === 'market_brief') return { ...service, data_status: 'stale' };
      if (service.id === 'intraday_flow') return { ...service, data_status: 'partial', items: [] };
      if (service.id === 'performance_brief') return {
        ...service,
        data_status: 'empty',
        items: service.items.map(item => ({
          ...item, sample_count: 0, win_rate: null,
          average_return_pct: null, cumulative_return_pct: null,
        })),
      };
      return service;
    }),
  });

  render(<AlphaServiceDashboard />);

  expect(await screen.findByText('오래됨')).toBeInTheDocument();
  expect(screen.getByText('일부만')).toBeInTheDocument();
  expect(screen.getByText('데이터 없음')).toBeInTheDocument();
  expect(screen.getAllByText('표본 없음').length).toBeGreaterThan(0);
  expect(screen.queryByText('0%')).not.toBeInTheDocument();
  expect(screen.getByRole('alert')).toHaveTextContent('포지션 데이터를 읽지 못했습니다.');
});

it('retries the same endpoint after a failed request', async () => {
  mockGetDashboard
    .mockRejectedValueOnce(new Error('network unavailable'))
    .mockResolvedValueOnce(dashboard);
  render(<AlphaServiceDashboard />);

  const retry = await screen.findByRole('button', { name: '다시 불러오기' });
  expect(screen.getByRole('alert')).toHaveTextContent('서비스 현황을 불러오지 못했습니다.');
  await userEvent.click(retry);

  expect(await screen.findByText('전일 시장 정리')).toBeInTheDocument();
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);
});

it('refreshes every sixty seconds only while visible and stops after unmount', async () => {
  vi.useFakeTimers();
  const addListener = vi.spyOn(document, 'addEventListener');
  const removeListener = vi.spyOn(document, 'removeEventListener');
  let visibility: DocumentVisibilityState = 'visible';
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => visibility,
  });
  mockGetDashboard.mockResolvedValue(dashboard);
  const view = render(<AlphaServiceDashboard />);
  await act(async () => {
    await Promise.resolve();
  });

  expect(mockGetDashboard).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);

  visibility = 'hidden';
  document.dispatchEvent(new Event('visibilitychange'));
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);

  view.unmount();
  const visibilityRegistration = addListener.mock.calls.find(([type]) => type === 'visibilitychange');
  expect(visibilityRegistration).toBeDefined();
  expect(removeListener).toHaveBeenCalledWith('visibilitychange', visibilityRegistration![1]);
  visibility = 'visible';
  await vi.advanceTimersByTimeAsync(60_000);
  expect(mockGetDashboard).toHaveBeenCalledTimes(2);
});

it('keeps one request in flight across rapid retries and offers retry after a poll failure', async () => {
  vi.useFakeTimers();
  let resolveRetry!: (value: typeof dashboard) => void;
  const retryResponse = new Promise<typeof dashboard>(resolve => {
    resolveRetry = resolve;
  });
  mockGetDashboard
    .mockResolvedValueOnce(dashboard)
    .mockRejectedValueOnce(new Error('poll failed'))
    .mockImplementationOnce(() => retryResponse)
    .mockResolvedValue(dashboard);

  render(<AlphaServiceDashboard />);
  await act(async () => { await Promise.resolve(); });
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });

  const retry = screen.getByRole('button', { name: '다시 불러오기' });
  expect(screen.getByRole('region', { name: 'Alpha Service Clock' })).toHaveTextContent('전일 시장 정리');
  await act(async () => {
    fireEvent.click(retry);
    await Promise.resolve();
  });
  act(() => {
    fireEvent.click(screen.getByRole('button', { name: '다시 불러오기' }));
  });
  expect(mockGetDashboard).toHaveBeenCalledTimes(3);

  await act(async () => {
    resolveRetry(dashboard);
    await retryResponse;
  });
  expect(screen.queryByRole('button', { name: '다시 불러오기' })).not.toBeInTheDocument();
});

it('serializes alpha dashboard query parameters with the backend contract names', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('@/lib/mirofishApi');
  const buildPath = actual.buildAlphaServiceDashboardPath as ((params: {
    candidateLimit?: number;
    outcomeDays?: number;
    outcomeLimit?: number;
  }) => string) | undefined;

  expect(buildPath).toBeTypeOf('function');
  expect(buildPath!({ candidateLimit: 7, outcomeDays: 45, outcomeLimit: 12 })).toBe(
    '/api/admin/mirofish/alpha-dashboard?candidate_limit=7&outcome_days=45&outcome_limit=12',
  );
  expect(buildPath!({})).toBe('/api/admin/mirofish/alpha-dashboard');
});
