import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import AdminEndpointsPage from '@/pages/admin/AdminEndpointsPage';

const mockApi = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getDataSources: vi.fn(),
  listRuns: vi.fn(),
  resolveTarget: vi.fn(),
  startRun: vi.fn(),
  hydrateRun: vi.fn(),
}));

vi.mock('@/lib/mirofishApi', () => ({
  mirofishApi: mockApi,
}));

function runPayload(target: string, status = 'running') {
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
  mockApi.resolveTarget.mockResolvedValue({
    target: 'ㅅㅅㅈㅈ',
    resolved: { symbol: '005930', display_name: '삼성전자', market: 'KOSPI' },
    source_files: [],
    signal_count: 0,
  });
  mockApi.startRun.mockImplementation(async ({ target }) => runPayload(target));
  mockApi.hydrateRun.mockResolvedValue(runPayload('삼성전자', 'completed'));
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
});
