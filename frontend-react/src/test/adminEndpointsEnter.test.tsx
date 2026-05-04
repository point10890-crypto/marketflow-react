import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AdminEndpointsPage from '@/pages/admin/AdminEndpointsPage';

const mockApi = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getDataSources: vi.fn(),
  listRuns: vi.fn(),
  searchTargets: vi.fn(),
  resolveTarget: vi.fn(),
  startRun: vi.fn(),
  hydrateRun: vi.fn(),
  startScannerRun: vi.fn(),
  getScannerRun: vi.fn(),
  getScannerCandidates: vi.fn(),
}));

vi.mock('@/lib/mirofishApi', () => ({
  mirofishApi: mockApi,
}));

function runPayload(target: string, status = 'running', overrides: Record<string, unknown> = {}) {
  return {
    id: 'mf_test_run',
    target,
    display_name: target,
    status,
    layers: [],
    logs: [],
    analysts: [],
    graph_nodes: [],
    prediction_nodes: [],
    progress: {
      percent: status === 'completed' ? 100 : 2,
      current_phase: status === 'completed' ? 'report' : 'intake',
      current_label: status === 'completed' ? 'Markdown Report' : 'Target Intake',
      elapsed_ms: 10,
    },
    ...overrides,
  };
}

async function renderPage() {
  render(<AdminEndpointsPage />);
  await waitFor(() => expect(mockApi.getStatus).toHaveBeenCalled());
  return screen.getByRole('textbox');
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.getStatus.mockResolvedValue({
    ready: true,
    source: 'test',
    brain: { score: 63, regime: 'neutral', crisis: 'Lv.2' },
    pipeline: { status: 'ready', graph_links: 0, similar_events: 0, agent_count: 10 },
  });
  mockApi.getDataSources.mockResolvedValue({ files: [] });
  mockApi.listRuns.mockResolvedValue({ runs: [] });
  mockApi.searchTargets.mockResolvedValue({
    target: 'ㅅㅅㅈㅈ',
    source: 'ticker_map',
    candidates: [],
  });
  mockApi.resolveTarget.mockResolvedValue({
    target: 'ㅅㅅㅈㅈ',
    resolved: { symbol: '005930', display_name: '삼성전자', market: 'KOSPI' },
    source_files: [],
    signal_count: 0,
  });
  mockApi.startRun.mockImplementation(async ({ target }) => runPayload(target));
  mockApi.hydrateRun.mockResolvedValue(runPayload('삼성전자', 'completed'));
  mockApi.startScannerRun.mockResolvedValue({
    id: 'mfas_test',
    status: 'completed',
    candidate_count: 1,
    candidates: [
      {
        rank: 1,
        symbol: '000001',
        display_name: 'Alpha One',
        market: 'KOSPI',
        alpha_score: 88,
        risk_score: 21,
        action: 'BUY_CANDIDATE',
        horizon: 'SWING_5_20D',
        strategy_tags: ['momentum', 'vcp_entry'],
        evidence: ['daily price momentum confirmed'],
        price: 108,
        change_pct: 8,
        trading_value: 64800000000,
      },
    ],
  });
  mockApi.getScannerRun.mockResolvedValue({
    id: 'mfas_test',
    status: 'completed',
    candidate_count: 1,
    candidates: [],
  });
  mockApi.getScannerCandidates.mockResolvedValue({
    run_id: 'mfas_test',
    status: 'completed',
    candidates: [],
  });
});

describe('AdminEndpointsPage analysis start input', () => {
  it('starts analysis when Enter is pressed after a chosung query', async () => {
    const input = await renderPage();

    fireEvent.change(input, { target: { value: 'ㅅㅅㅈㅈ' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });

    await waitFor(() => {
      expect(mockApi.startRun).toHaveBeenCalledWith(expect.objectContaining({
        target: 'ㅅㅅㅈㅈ',
        agent_count: 10,
      }));
    });
  });

  it('starts after Korean IME composition commits with Enter', async () => {
    const input = await renderPage();

    fireEvent.change(input, { target: { value: 'ㅅㅅㅈㅈ' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 229 });
    fireEvent.compositionEnd(input);

    await waitFor(() => {
      expect(mockApi.startRun).toHaveBeenCalledWith(expect.objectContaining({
        target: 'ㅅㅅㅈㅈ',
      }));
    });
  });

  it('shows ambiguous autocomplete candidates and starts the selected one with Enter', async () => {
    mockApi.searchTargets.mockResolvedValueOnce({
      target: '두산',
      source: 'ticker_map',
      candidates: [
        { symbol: '000150', display_name: '두산', market: 'KOSPI', yahoo_ticker: '000150.KS', match_type: 'exact' },
        { symbol: '034020', display_name: '두산에너빌리티', market: 'KOSPI', yahoo_ticker: '034020.KS', match_type: 'name_prefix' },
        { symbol: '454910', display_name: '두산로보틱스', market: 'KOSPI', yahoo_ticker: '454910.KS', match_type: 'name_prefix' },
      ],
    });
    const input = await renderPage();

    fireEvent.change(input, { target: { value: '두산' } });

    await screen.findByText('두산로보틱스');
    fireEvent.keyDown(input, { key: 'ArrowDown', code: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'ArrowDown', code: 'ArrowDown' });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });

    await waitFor(() => {
      expect(mockApi.startRun).toHaveBeenCalledWith(expect.objectContaining({
        target: '두산로보틱스',
      }));
    });
  });

  it('labels the final verdict with the selected target identity', async () => {
    mockApi.startRun.mockResolvedValueOnce(runPayload('Samsung Electronics', 'running', {
      symbol: '005930',
      market: 'KOSPI',
    }));
    mockApi.hydrateRun.mockResolvedValueOnce(runPayload('Samsung Electronics', 'completed', {
      display_name: 'Samsung Electronics',
      symbol: '005930',
      market: 'KOSPI',
      verdict: {
        label: 'BUY',
        target: 'Samsung Electronics',
        confidence: 75,
        bullish: 5,
        bearish: 1,
        neutral: 4,
        horizon: '1M',
        summary: 'Live CIO verdict for Samsung Electronics: BUY with 75% confidence.',
      },
    }));
    const input = await renderPage();

    fireEvent.change(input, { target: { value: 'Samsung Electronics' } });
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });

    expect(await screen.findByText('단일 분석 대상 최종판결')).toBeTruthy();
    expect(await screen.findByText((text) => text.includes('005930') && text.includes('KOSPI'))).toBeTruthy();
    expect(await screen.findByText(/전체 종목 판정이 아니라/)).toBeTruthy();
  });

  it('runs alpha scanner and starts deep dive from a detected candidate', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Run scanner/i }));

    expect(await screen.findByText('Alpha One')).toBeTruthy();
    expect(await screen.findByText('BUY_CANDIDATE')).toBeTruthy();

    fireEvent.click(screen.getByText('Deep Dive'));

    await waitFor(() => {
      expect(mockApi.startScannerRun).toHaveBeenCalledWith(expect.objectContaining({
        market: 'KR',
        strategy: 'multi_signal',
        limit: 20,
      }));
      expect(mockApi.startRun).toHaveBeenCalledWith(expect.objectContaining({
        target: 'Alpha One',
      }));
    });
  });
});
