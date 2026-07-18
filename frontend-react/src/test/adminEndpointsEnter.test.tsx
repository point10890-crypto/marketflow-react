import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  getScannerStatus: vi.fn(),
  getScannerAlertState: vi.fn(),
  getScannerMonitorStatus: vi.fn(),
  getLatestScannerRun: vi.fn(),
  getScannerRun: vi.fn(),
  getScannerCandidates: vi.fn(),
  getDeepSeekStatus: vi.fn(),
  getTradingViewStatus: vi.fn(),
  getDualKalmanStatus: vi.fn(),
  getPriceChart: vi.fn(),
  createDeepSeekScannerSummary: vi.fn(),
  summarizeScannerRunWithDeepSeek: vi.fn(),
  sendScannerDeepSeekSummaryTelegram: vi.fn(),
  getWorkflowStatus: vi.fn(),
  getWorkflow: vi.fn(),
  getLatestWorkflow: vi.fn(),
  getWorkflowOutcomes: vi.fn(),
  refreshWorkflowOutcomes: vi.fn(),
  startWorkflowScanAnalyze: vi.fn(),
  getAutonomousStatus: vi.fn(),
  getAutonomousLearning: vi.fn(),
  getLearningReadiness: vi.fn(),
  runAutonomousCandidateAlert: vi.fn(),
  runAutonomousScanAnalysis: vi.fn(),
  refreshAutonomousLearning: vi.fn(),
  sendLatestAutonomousWorkflowTelegram: vi.fn(),
  getPipelineToday: vi.fn(),
  getOutcomesBoard: vi.fn(),
  getMcpResources: vi.fn(),
  getAlphaEndpointBlueprint: vi.fn(),
  getFearIndex: vi.fn(),
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
  const input = document.querySelector<HTMLInputElement>('input[name="target"]');
  expect(input).toBeTruthy();
  return input!;
}

async function renderSubscriberPage() {
  render(<AdminEndpointsPage subscriberMode />);
  await waitFor(() => expect(mockApi.getStatus).toHaveBeenCalled());
  const input = document.querySelector<HTMLInputElement>('input[name="target"]');
  expect(input).toBeTruthy();
  return input!;
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  mockApi.getStatus.mockResolvedValue({
    ready: true,
    source: 'test',
    brain: { score: 63, regime: 'neutral', crisis: 'Lv.2' },
    pipeline: { status: 'ready', graph_links: 0, similar_events: 0, agent_count: 10 },
  });
  mockApi.getDataSources.mockResolvedValue({ files: [] });
  const alphaEndpointBlueprint = {
    schema_version: 'mirofish.alpha_endpoint_blueprint.v1',
    objective: 'Improve profitable Top 3 candidate detection with evidence-first endpoint gates.',
    source_readiness: {
      status: 'ready',
      required_total: 5,
      required_covered: 5,
      required_partial: 0,
      required_missing: 0,
      summary: '5/5 required evidence clusters covered',
    },
    endpoint_count: 3,
    p0_count: 2,
    endpoints: [
      {
        id: 'kr_flow_batch',
        priority: 'P0',
        name: 'KR capital-flow confirmation batch',
        current_status: 'ready',
        mcp_tool: 'get_kr_investor_flow_batch',
        internal_path: '/api/admin/mirofish/sources/kr-flow/batch',
        alpha_impact: 'Confirms whether scanner momentum has actual foreign/institution flow support.',
      },
      {
        id: 'kr_disclosure_risk_batch',
        priority: 'P0',
        name: 'KR disclosure and event-risk batch',
        current_status: 'ready',
        mcp_tool: 'get_disclosure_risk_batch',
        internal_path: '/api/admin/mirofish/sources/disclosure-risk/batch',
        alpha_impact: 'Filters out candidates with unresolved filings, dilution, or event risk.',
      },
      {
        id: 'outcome_memory_similar_cases',
        priority: 'P1',
        name: 'Outcome memory similar-case retrieval',
        current_status: 'ready',
        mcp_tool: 'get_similar_outcome_cases',
        internal_path: '/api/admin/mirofish/learning/similar-cases',
        alpha_impact: 'Uses past outcomes to adjust rank when a candidate resembles prior wins or failures.',
      },
    ],
    next_actions: [],
  };
  mockApi.getMcpResources.mockResolvedValue({
    schema_version: 'mirofish.mcp_resource_catalog.v1',
    catalog_count: 3,
    alpha_endpoint_blueprint: alphaEndpointBlueprint,
    source_gaps: {
      readiness: 'ready',
      required_total: 5,
      required_covered: 5,
      required_partial: 0,
      required_missing: 0,
      requirements: [],
      next_actions: [],
    },
  });
  mockApi.getAlphaEndpointBlueprint.mockResolvedValue(alphaEndpointBlueprint);
  mockApi.getFearIndex.mockResolvedValue({
    schema_version: 'mirofish.fear_index.v1',
    generated_at: '2026-05-12T00:00:00+00:00',
    score: 46.5,
    level: 'neutral',
    level_label: '중립',
    tone: 'neutral',
    confidence: 'high',
    coverage_pct: 100,
    summary: '공포지수 46.5 (중립).',
  });
  mockApi.getPipelineToday.mockResolvedValue({
    generated_at: '2026-05-12T00:00:00+00:00',
    date_kst: '2026-05-12',
    market: {
      kr: {
        phase: 'regular_session',
        is_regular_session: true,
        gate_label: 'open',
        gate_score: 72,
        kospi_change_pct: 0.4,
        kosdaq_change_pct: -0.2,
      },
      us: {
        vix: 18.2,
        vix_level: 'moderate',
        fear_greed_score: 52,
        fear_greed_label: 'neutral',
      },
    },
    fear_index: {
      schema_version: 'mirofish.fear_index.v1',
      generated_at: '2026-05-12T00:00:00+00:00',
      score: 46.5,
      level: 'neutral',
      level_label: '중립',
      tone: 'neutral',
      confidence: 'high',
      coverage_pct: 100,
      summary: '공포지수 46.5 (중립).',
    },
    funnel: {
      scanner_pool: 20,
      scanner_runs_today: 2,
      batch_new_candidates: 5,
      graphrag_uploaded: 5,
      top3_ready: 3,
      latest_workflow_id: 'mcp_test',
      latest_workflow_status: 'completed',
      latest_workflow_at: '2026-05-12T00:05:00+00:00',
      latest_scanner_run_at: '2026-05-12T00:00:00+00:00',
      freshness_status: 'fresh',
    },
    operating_workflow: {
      schema_version: 'mirofish.operating_workflow.v1',
      generated_at: '2026-05-12T00:00:00+00:00',
      date_kst: '2026-05-12',
      workflow_id: 'mcp_test',
      workflow_status: 'completed',
      current_stage_id: 'outcomes',
      overall_status: 'ready',
      overall_progress_pct: 83,
      stages: [
        { id: 'scanner', label: 'Alpha Scanner pool', objective: 'detect candidates', status: 'complete', progress_pct: 100, count: 20, total: null },
        { id: 'batch', label: 'New-event batch', objective: 'select batch', status: 'complete', progress_pct: 100, count: 5, total: 5 },
        { id: 'graphrag', label: 'GraphRAG analysis', objective: 'validate evidence', status: 'complete', progress_pct: 100, count: 5, total: 5 },
        { id: 'top3', label: 'MCP Top3', objective: 'rank final picks', status: 'complete', progress_pct: 100, count: 3, total: 3 },
        { id: 'telegram', label: 'Telegram handoff', objective: 'send actionable alert', status: 'complete', progress_pct: 100, count: 1, total: 1 },
        { id: 'outcomes', label: 'Forward outcomes', objective: 'validate returns', status: 'ready', progress_pct: 0, count: 3, total: 3 },
      ],
    },
    kpi_7d: { window_days: 7, sample_size: 1, hit_rate_pct: 100, avg_return_pct: 10, pending_count: 0 },
    kpi_30d: { window_days: 30, sample_size: 1, hit_rate_pct: 100, avg_return_pct: 10, pending_count: 0 },
    next: {
      next_scheduled_scan_at: '2026-05-12T11:20:00+09:00',
      next_scheduled_scans: ['2026-05-12T11:20:00+09:00'],
      scanner_enabled: true,
    },
    alerts_today: {
      scanner_alerts_today: 1,
      scanner_last_alert_at: '2026-05-12T00:06:00+00:00',
      recent_scanner_alerts: [
        {
          event_key: '079650:WATCH:2026-05-12',
          sent_at: '2026-05-12T00:06:00+00:00',
          run_id: 'mfas_test',
          symbol: '079650',
          display_name: '서산',
          market: 'KOSDAQ',
          action: 'WATCH',
          alpha_score: 40,
          risk_score: 19,
          price: { current_price: 5760, change_rate: 3.2, date: '2026-05-12' },
        },
      ],
    },
  });
  mockApi.getOutcomesBoard.mockResolvedValue({
    window_days: 30,
    generated_at: '2026-05-12T00:00:00+00:00',
    sample_size: 1,
    workflow_count: 1,
    summary: {
      evaluated_count: 1,
      pending_count: 0,
      hit_count: 1,
      miss_count: 0,
      stopped_count: 0,
      hit_rate_pct: 100,
      avg_forward_return_pct: 10,
      false_positive_pct: 0,
      targets: { hit_rate_pct: 55, avg_return_pct: 1.5, false_positive_pct: 20 },
    },
    items: [],
    items_truncated: false,
    total_items: 0,
  });
  mockApi.getDeepSeekStatus.mockResolvedValue({
    provider: 'deepseek',
    configured: true,
    default_model: 'deepseek-v4-flash',
  });
  mockApi.getTradingViewStatus.mockResolvedValue({
    provider: 'tradingview_mcp',
    mode: 'disabled',
    enabled: false,
    configured: false,
    cache_available: false,
    mcp_url_configured: false,
  });
  mockApi.getDualKalmanStatus.mockResolvedValue({
    service: 'mirofish-dual-kalman',
    ready: true,
    mode: 'scanner_signal_shadow_gate',
    latest_run_id: null,
  });
  mockApi.getPriceChart.mockResolvedValue({
    symbol: '000001',
    target: 'Alpha One',
    source: 'daily_prices.csv',
    count: 2,
    chart: [
      { date: '2026-05-06', open: 100, high: 105, low: 98, close: 102, volume: 1000000 },
      { date: '2026-05-07', open: 102, high: 112, low: 101, close: 110, volume: 1400000 },
    ],
    latest: { date: '2026-05-07', open: 102, high: 112, low: 101, close: 110, volume: 1400000 },
  });
  mockApi.getWorkflowStatus.mockResolvedValue({
    ready: true,
    latest_workflow: {
      id: 'mcp_test',
      status: 'completed',
      outcome_summary: {
        top3_evaluated_count: 1,
        top3_hit_rate_pct: 100,
        average_forward_return_pct: 10,
        pending_count: 0,
        lookahead_safe: true,
      },
      top3: [{
        symbol: '000001',
        target: 'Alpha One',
        final_score: 91,
        verdict: { action: 'BUY', confidence_pct: 80 },
        outcome: {
          status: 'partial',
          entry_date: '2026-05-07',
          primary_horizon_days: 5,
          forward_return_pct: 10,
          hit: true,
          lookahead_safe: true,
        },
      }],
    },
  });
  mockApi.getWorkflow.mockResolvedValue({
    id: 'mcp_test',
    status: 'completed',
    outcome_summary: {
      top3_evaluated_count: 1,
      top3_hit_rate_pct: 100,
      average_forward_return_pct: 10,
      pending_count: 0,
      lookahead_safe: true,
    },
    top3: [{
      symbol: '000001',
      target: 'Alpha One',
      final_score: 91,
      verdict: { action: 'BUY', confidence_pct: 80 },
      outcome: {
        status: 'partial',
        entry_date: '2026-05-07',
        primary_horizon_days: 5,
        forward_return_pct: 10,
        hit: true,
        lookahead_safe: true,
      },
    }],
  });
  mockApi.getLatestWorkflow.mockResolvedValue({
    id: 'mcp_test',
    status: 'completed',
    outcome_summary: {
      top3_evaluated_count: 1,
      top3_hit_rate_pct: 100,
      average_forward_return_pct: 10,
      pending_count: 0,
      lookahead_safe: true,
    },
    top3: [{
      symbol: '000001',
      target: 'Alpha One',
      final_score: 91,
      verdict: { action: 'BUY', confidence_pct: 80 },
      outcome: {
        status: 'partial',
        entry_date: '2026-05-07',
        primary_horizon_days: 5,
        forward_return_pct: 10,
        hit: true,
        lookahead_safe: true,
      },
    }],
  });
  mockApi.startWorkflowScanAnalyze.mockResolvedValue({
    id: 'mcp_test',
    status: 'completed',
    outcome_summary: {
      top3_evaluated_count: 1,
      top3_hit_rate_pct: 100,
      average_forward_return_pct: 10,
      pending_count: 0,
      lookahead_safe: true,
    },
    top3: [{
      symbol: '000001',
      target: 'Alpha One',
      final_score: 91,
      verdict: { action: 'BUY', confidence_pct: 80 },
      outcome: {
        status: 'partial',
        entry_date: '2026-05-07',
        primary_horizon_days: 5,
        forward_return_pct: 10,
        hit: true,
        lookahead_safe: true,
      },
    }],
  });
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
    generated_at: '2026-05-06T10:00:00+09:00',
    freshness_status: 'fresh',
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
  mockApi.getScannerStatus.mockResolvedValue({
    enabled: true,
    timezone: 'Asia/Seoul',
    last_run_id: 'mfas_latest',
    last_run_at: '2026-05-05T16:10:00+09:00',
    next_scheduled_at: '2026-05-06T09:20:00+09:00',
    scheduled_times: ['09:20', '11:20', '14:20', '15:40', '16:10'],
    freshness_status: 'fresh',
    freshness: { status: 'fresh' },
    candidate_count: 1,
    source_files: [],
  });
  mockApi.getScannerMonitorStatus.mockResolvedValue({
    last_checked_at: '2026-07-08T10:38:20.679750+09:00',
    last_status: 'sent',
    last_run_id: 'mfas_latest',
    last_candidate_count: 9,
    last_new_event_count: 1,
    last_telegram_sent: true,
  });
  mockApi.getScannerAlertState.mockResolvedValue({
    last_checked_at: '2026-07-08T10:38:20.679750+09:00',
    last_sent_at: '2026-07-08T10:38:20.679750+09:00',
    last_run_id: 'mfas_latest',
    last_candidate_count: 9,
    sent_event_count: 1,
    recent_sent_events: [{
      event_key: '037710:BUY_CANDIDATE:2026-07-08',
      sent_at: '2026-07-08T10:38:20.679750+09:00',
      run_id: 'mfas_latest',
      rank: 1,
      symbol: '037710',
      display_name: '광주신세계',
      market: 'KOSPI',
      action: 'BUY_CANDIDATE',
      signal_quality: 'B',
      alpha_score: 72,
      risk_score: 40,
      price: { current_price: 45900, change_rate: 1.2, date: '2026-07-08' },
    }],
  });
  mockApi.getLatestScannerRun.mockResolvedValue({
    id: 'mfas_latest',
    status: 'completed',
    generated_at: '2026-05-05T16:10:00+09:00',
    candidate_count: 1,
    freshness_status: 'fresh',
    freshness: { status: 'fresh' },
    candidates: [
      {
        rank: 1,
        symbol: '000001',
        display_name: 'Latest Alpha',
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
  const deepSeekSummary = {
    provider: 'deepseek',
    model: 'deepseek-v4-flash',
    run_id: 'mfas_test',
    candidate_count: 1,
    summary: {
      summary_title_ko: '알파 후보 요약',
      portfolio_note_ko: '스캐너 숫자를 보존한 요약입니다.',
      candidates: [
        {
          rank: 1,
          symbol: '000001',
          display_name: 'Alpha One',
          market: 'KOSPI',
          action_ko: '매수 후보',
          thesis_ko: '모멘텀이 확인됩니다.',
          risk_ko: '리스크 점검 필요.',
          next_check_ko: '거래대금 확인.',
        },
      ],
    },
  };
  mockApi.summarizeScannerRunWithDeepSeek.mockResolvedValue(deepSeekSummary);
  mockApi.createDeepSeekScannerSummary.mockResolvedValue({
    run: {
      id: 'mfas_test',
      status: 'completed',
      candidate_count: 1,
      candidates: [],
    },
    summary: deepSeekSummary,
  });
  mockApi.sendScannerDeepSeekSummaryTelegram.mockResolvedValue({
    ok: true,
    run_id: 'mfas_test',
    provider: 'deepseek',
    message_chars: 300,
    summary: deepSeekSummary,
  });
  mockApi.getAutonomousStatus.mockResolvedValue({
    service: 'mirofish-autonomous-mcp',
    ready: true,
    mode: 'scanner_workflow_learning_telegram_control_plane',
    mutation_enabled: false,
    shared_secret_configured: false,
    send_confirmation_phrase: 'SEND_MIROFISH_AUTONOMOUS_ALERT',
    telegram: {
      personal_configured: true,
      channel_configured: false,
      personal_chat_present: true,
      channel_chat_present: false,
    },
    learning: {
      available: true,
      evaluated_count: 2,
      hit_rate_pct: 50,
      average_forward_return_pct: 2.25,
      production_weights_mutated: false,
      recommendation_count: 1,
      alpha_memory: {
        available: true,
        sample_count: 2,
        strongest_positive: { key: 'momentum', hit_rate_pct: 100, average_forward_return_pct: 6.5 },
        weakest_negative: { key: 'event_risk', hit_rate_pct: 0, average_forward_return_pct: -2 },
        score_profile: {
          hit_avg_alpha: 82,
          miss_avg_alpha: 68,
          hit_avg_risk: 24,
          miss_avg_risk: 52,
          hit_avg_final_score: 88,
          miss_avg_final_score: 54,
        },
        cohorts: {
          strategy_tags: [
            { key: 'momentum', sample_count: 1, hit_rate_pct: 100, average_forward_return_pct: 6.5 },
            { key: 'event_risk', sample_count: 1, hit_rate_pct: 0, average_forward_return_pct: -2 },
          ],
        },
      },
    },
    runtime: {
      mcp_server: {
        url: 'http://127.0.0.1:8765/mcp',
        healthy: true,
        status_code: 200,
        server_name: 'MarketFlow MiroFish Autonomous MCP',
        server_version: 'test',
      },
      startup_task: {
        task_name: 'MarketFlow-MiroFish-MCP',
        registered: true,
        query_ok: true,
        last_result: '0',
      },
      watchdog_task: {
        task_name: 'MarketFlow-MiroFish-MCP-Watchdog',
        registered: true,
        query_ok: true,
        next_run_time: '10:10',
      },
    },
    tools: [
      'run_candidate_detection_alert',
      'run_autonomous_scan_analysis',
      'refresh_learning_feedback',
      'send_latest_workflow_telegram',
    ],
    resources: ['mirofish://autonomous/status', 'mirofish://autonomous/learning'],
    checked_at: '2026-05-10T00:00:00+09:00',
  });
  mockApi.getAutonomousLearning.mockResolvedValue({ available: false });
  mockApi.getLearningReadiness.mockResolvedValue({
    schema_version: 'mirofish.learning_readiness.v1',
    service: 'mirofish-learning-readiness',
    ready: true,
    learning_active: true,
    status: 'bounded_maturing',
    mode: 'bounded_outcome_memory',
    lookahead_safe: true,
    production_weights_mutated: false,
    blockers: [],
    pending_recommendations: [],
    outcome_memory: {
      available: true,
      ready: true,
      evaluated_count: 20,
      min_evaluated_count: 9,
    },
    backtest_gate: {
      available: true,
      ready: true,
      status: 'maturing',
      sample_count: 52,
      min_sample_count_bounded: 40,
      min_sample_count_full: 100,
    },
    score_control: {
      outcome_memory_enabled: true,
      status: 'bounded_maturing',
      caps: { tag: { positive: 0.75, negative: -1.5 }, global: { positive: 1.0, negative: -2.0 } },
    },
    learning_guard: {
      status: 'insufficient_top3_metrics',
      disabled: false,
    },
    top3_metrics: {
      available: true,
      qualified: false,
    },
  });
  mockApi.runAutonomousCandidateAlert.mockResolvedValue({
    ok: true,
    status: 'dry_run',
    dry_run: true,
    run_id: 'mfas_auto',
    candidate_count: 1,
    new_event_count: 1,
    telegram_sent: false,
    events: [{
      key: '000001:BUY_CANDIDATE',
      symbol: '000001',
      name: 'Alpha One',
      market: 'KOSPI',
      alpha_score: 82,
      risk_score: 24,
      action: 'BUY_CANDIDATE',
    }],
    resource_links: { scanner_run: 'mirofish://scanner/runs/mfas_auto' },
  });
  mockApi.runAutonomousScanAnalysis.mockResolvedValue({
    ok: true,
    status: 'dry_run',
    dry_run: true,
    workflow_id: 'wfmcp_auto',
    scanner_run_id: 'mfas_auto',
    event_count: 1,
    candidate_count: 1,
    top_count: 1,
    top_symbols: ['000001'],
    telegram_sent: false,
    event_state_committed: false,
    resource_links: { workflow: 'mirofish://workflows/wfmcp_auto' },
  });
  mockApi.refreshAutonomousLearning.mockResolvedValue({
    service: 'mirofish-autonomous-learning',
    generated_at: '2026-05-10T00:00:00+09:00',
    mode: 'advisory_feedback_only',
    production_weights_mutated: false,
    lookahead_safe: true,
    workflow_count: 1,
    item_count: 2,
    evaluated_count: 2,
    hit_count: 1,
    miss_count: 1,
    hit_rate_pct: 50,
    average_forward_return_pct: 2.25,
    alpha_memory: {
      available: true,
      sample_count: 2,
      strongest_positive: { key: 'momentum', hit_rate_pct: 100, average_forward_return_pct: 6.5 },
      weakest_negative: { key: 'event_risk', hit_rate_pct: 0, average_forward_return_pct: -2 },
      score_profile: {
        hit_avg_alpha: 82,
        miss_avg_alpha: 68,
        hit_avg_risk: 24,
        miss_avg_risk: 52,
        hit_avg_final_score: 88,
        miss_avg_final_score: 54,
      },
      cohorts: {
        strategy_tags: [
          { key: 'momentum', sample_count: 1, hit_rate_pct: 100, average_forward_return_pct: 6.5 },
          { key: 'event_risk', sample_count: 1, hit_rate_pct: 0, average_forward_return_pct: -2 },
        ],
      },
      guidance: [{ type: 'alpha_boost', target: 'momentum', reason: 'strong cohort' }],
    },
    recommendations: [{
      type: 'keep_current_weights',
      action: 'monitor',
      reason: 'recent evaluated outcomes do not require automatic production weight changes',
    }],
    errors: [],
  });
  mockApi.sendLatestAutonomousWorkflowTelegram.mockResolvedValue({
    ok: true,
    status: 'sent',
    workflow_id: 'wfmcp_auto',
    telegram_sent: true,
    event_state_committed: false,
    message_chars: 240,
  });
});

describe('AdminEndpointsPage analysis start input', () => {
  it('keeps the cached TOP3 when the latest workflow has no new events', async () => {
    window.localStorage.setItem('marketflow.mirofish.workflow-top3.v1', JSON.stringify({
      id: 'cached_workflow',
      status: 'completed',
      completed_at: '2026-07-17T06:00:00Z',
      scanner_run_id: 'cached_scanner_run',
      top3: [{
        symbol: '096770',
        target: 'Cached SK Innovation',
        final_score: 87,
        verdict: { action: 'BUY', confidence_pct: 70 },
      }],
    }));
    mockApi.getWorkflowStatus.mockResolvedValueOnce({
      ready: true,
      latest_workflow: {
        id: 'no_new_workflow',
        status: 'no_new_events',
        created_at: '2026-07-18T06:00:00Z',
        top3: [],
      },
    });

    await renderPage();

    expect((await screen.findAllByText('Cached SK Innovation')).length).toBeGreaterThan(0);
  });

  it('loads the latest alpha scanner board on page load', async () => {
    await renderPage();

    await waitFor(() => expect(mockApi.getLatestScannerRun).toHaveBeenCalled());
    expect(mockApi.getScannerStatus).toHaveBeenCalled();
    expect(mockApi.getAutonomousStatus).toHaveBeenCalled();
    expect(await screen.findByText('Autonomous MCP Control')).toBeTruthy();
    expect(await screen.findByText('Latest Alpha')).toBeTruthy();
    expect(await screen.findByText(/Last/)).toBeTruthy();
    expect(await screen.findByText(/Next/)).toBeTruthy();
    expect(await screen.findByText(/Fresh fresh/i)).toBeTruthy();
    expect(await screen.findByText('Forward Return')).toBeTruthy();
    expect((await screen.findAllByText('+10.00%')).length).toBeGreaterThan(0);
    expect(await screen.findByText(/T5 \+10.00%/)).toBeTruthy();
    expect(await screen.findByText(/replay-safe after 2026-05-07/i)).toBeTruthy();
    expect((await screen.findAllByText(/MCP HTTP online/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Watchdog 5m on/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Startup Task/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Operating Workflow/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Scanner Alerts/i)).length).toBeGreaterThan(0);
    expect(await screen.findByText('서산')).toBeTruthy();
    expect(await screen.findByText(/079650 · KOSDAQ/)).toBeTruthy();
    expect((await screen.findAllByText(/MCP Top3/i)).length).toBeGreaterThan(0);
    expect(await screen.findByText(/NAVER CHARTS/i)).toBeTruthy();
    expect(await screen.findByText(/TOP3 차트 확인/i)).toBeTruthy();
    expect(mockApi.getPriceChart).not.toHaveBeenCalled();
    expect((await screen.findAllByText(/Alpha Memory/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/성과검증 보드/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Hit vs Miss Score Profile/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/Signal Cohorts/i)).length).toBeGreaterThan(0);
    expect((await screen.findAllByText(/best momentum/i)).length).toBeGreaterThan(0);
  });

  it('reuses the endpoints console in subscriber mode without admin-only mutation controls', async () => {
    await renderSubscriberPage();

    expect(await screen.findByText('AI Brain 검출 대시보드')).toBeTruthy();
    expect(await screen.findByText('Pro + AI Brain 구독자 콘솔')).toBeTruthy();
    expect(await screen.findByText('알파 스캐너 신규 이벤트')).toBeTruthy();
    expect(await screen.findByText('광주신세계')).toBeTruthy();
    expect(await screen.findByText('037710')).toBeTruthy();
    expect(await screen.findByText('@45,900')).toBeTruthy();
    expect(await screen.findByText('등급 B')).toBeTruthy();
    expect(await screen.findByText('리스크 40')).toBeTruthy();
    expect(await screen.findByText('Latest Alpha')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Run scanner/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Run MCP Top 3 Force refresh/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Detection dry-run/i })).toBeNull();
    expect(screen.queryByRole('button', { name: /Analysis dry-run/i })).toBeNull();
    expect(screen.queryByText('Autonomous MCP Control')).toBeNull();
    expect(screen.queryByText('/api/admin/mirofish/deepseek/scanner-summary')).toBeNull();
    expect(screen.queryByText('/api/admin/mirofish/workflow/scan-analyze')).toBeNull();
    expect(screen.queryByText('/api/admin/mirofish/autonomous/*')).toBeNull();
    expect(screen.getAllByText('/api/admin/mirofish/runs').length).toBeGreaterThan(0);
  });

  it('keeps core endpoint cards healthy when an optional provider fails', async () => {
    mockApi.getDeepSeekStatus.mockRejectedValueOnce(new Error('deepseek unavailable'));

    await renderPage();

    const serviceCard = screen.getByText('Service Status').closest('section');
    const dataSourcesCard = screen.getByText('Data Sources').closest('section');
    const deepSeekCard = screen.getByText('DeepSeek V2').closest('section');

    expect(serviceCard).toBeTruthy();
    expect(dataSourcesCard).toBeTruthy();
    expect(deepSeekCard).toBeTruthy();
    expect(within(serviceCard!).queryByText('ERROR')).toBeNull();
    expect(within(dataSourcesCard!).queryByText('ERROR')).toBeNull();
    expect(within(serviceCard!).getByText('OK')).toBeTruthy();
    expect(within(dataSourcesCard!).getByText('OK')).toBeTruthy();
    expect(within(deepSeekCard!).getByText('ERROR')).toBeTruthy();
  });

  it('shows DeepSeek not configured as idle rather than failed', async () => {
    mockApi.getDeepSeekStatus.mockResolvedValueOnce({
      provider: 'deepseek',
      configured: false,
      default_model: 'deepseek-v4-flash',
    });

    await renderPage();

    const deepSeekCard = screen.getByText('DeepSeek V2').closest('section');
    expect(deepSeekCard).toBeTruthy();
    expect(within(deepSeekCard!).queryByText('ERROR')).toBeNull();
    expect(within(deepSeekCard!).getByText('IDLE')).toBeTruthy();
  });

  it('runs autonomous MCP pre-service dry-runs from the admin panel', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Detection dry-run/i }));

    await waitFor(() => {
      expect(mockApi.runAutonomousCandidateAlert).toHaveBeenCalledWith(expect.objectContaining({
        dry_run: true,
        send_telegram: false,
        min_alpha: 70,
        max_risk: 45,
      }));
    });
    await waitFor(() => {
      expect(screen.getAllByText(/mfas_auto/).length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole('button', { name: /Analysis dry-run/i }));

    await waitFor(() => {
      expect(mockApi.runAutonomousScanAnalysis).toHaveBeenCalledWith(expect.objectContaining({
        dry_run: true,
        sync: true,
        send_telegram: false,
        commit_event_state: false,
        top_n: 3,
      }));
    });

    fireEvent.click(screen.getByRole('button', { name: /Learning preview/i }));

    await waitFor(() => {
      expect(mockApi.refreshAutonomousLearning).toHaveBeenCalledWith(expect.objectContaining({
        commit: false,
        limit: 20,
      }));
    });
    await waitFor(() => {
      expect(screen.getAllByText(/Learning feedback/i).length).toBeGreaterThan(0);
    });
  });

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
        target: '두산로보틱스 454910 KOSPI',
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

    expect((await screen.findAllByText('Alpha One')).length).toBeGreaterThan(0);
    expect(await screen.findByText('BUY_CANDIDATE')).toBeTruthy();

    fireEvent.click(screen.getByText('Deep Dive'));

    await waitFor(() => {
      expect(mockApi.startScannerRun).toHaveBeenCalledWith(expect.objectContaining({
        market: 'KR',
        strategy: 'multi_signal',
        limit: 20,
      }));
      expect(mockApi.startRun).toHaveBeenCalledWith(expect.objectContaining({
        target: 'Alpha One 000001 KOSPI',
      }));
    });
  });

  it('runs MCP Top 3 as a forced batch analysis of current candidates', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Run MCP Top 3/i }));

    await waitFor(() => {
      expect(mockApi.startWorkflowScanAnalyze).toHaveBeenCalledWith(expect.objectContaining({
        force: true,
        min_alpha: 50,
        max_risk: 65,
        actions: ['BUY_CANDIDATE', 'WATCH'],
        max_events: 5,
        top_n: 3,
        allow_stale_sources: false,
      }));
    });
  });

  it('summarizes scanner candidates with DeepSeek and sends Telegram', async () => {
    await renderPage();

    fireEvent.click(screen.getByRole('button', { name: /Run scanner/i }));
    expect((await screen.findAllByText('Alpha One')).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: 'DeepSeek 요약' }));
    expect(await screen.findByText('알파 후보 요약')).toBeTruthy();
    expect(await screen.findByText('000001 매수 후보')).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: '텔레그램 전송' }));

    await waitFor(() => {
      expect(mockApi.summarizeScannerRunWithDeepSeek).toHaveBeenCalledWith('mfas_test', expect.objectContaining({
        limit: 5,
        model: 'deepseek-v4-flash',
      }));
      expect(mockApi.sendScannerDeepSeekSummaryTelegram).toHaveBeenCalledWith('mfas_test', expect.objectContaining({
        channel: false,
      }));
    });
  });
});
