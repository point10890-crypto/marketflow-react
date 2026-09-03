import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import LlmRoutingCostCard from './LlmRoutingCostCard';


const mockApi = vi.hoisted(() => ({
    getLlmRoutingStatus: vi.fn(),
    getLlmUsage: vi.fn(),
}));

vi.mock('@/lib/mirofishApi', () => ({ mirofishApi: mockApi }));

const status = {
    schema_version: 'ai-routing-status-v1',
    service: 'ai-routing',
    checked_at: '2026-09-03T01:00:00+00:00',
    freshness: { status: 'fresh', checked_at: '2026-09-03T01:00:00+00:00', age_seconds: 0, ttl_seconds: 300 },
    provider_order: { decisive_text: ['deepseek', 'openai'], vision: ['gemini', 'openai'] },
    providers: [
        { provider: 'deepseek', operation: 'decisive_text', configured: true, available: false, model: 'deepseek-v4-pro', status: 'authentication', checked_at: '2026-09-03T01:00:00+00:00', ttl_seconds: 300 },
        { provider: 'gemini', operation: 'vision', configured: true, available: true, model: 'gemini-2.5-flash', status: 'healthy', checked_at: '2026-09-03T01:00:00+00:00', ttl_seconds: 300 },
    ],
    breakers: [
        { provider: 'deepseek', modality: 'text', model_tier: 'decisive', state: 'open', failure_count: 1, last_error_class: 'authentication' },
        { provider: 'gemini', modality: 'vision', model_tier: 'fast', state: 'closed', failure_count: 0, last_error_class: null },
    ],
    budget: {
        scope: 'utc_calendar_day', day_utc: '2026-09-03', pool: 'automatic', provider: 'openai',
        daily_cap_usd_configured: true, daily_cap_usd: '2.5', used_usd: '0.5', remaining_usd: '2',
        usage_percent: 20, status: 'configured',
    },
    hold_review: { available: false, count: null, rate: null, reason: 'final_outcome_not_recorded' },
} as const;

const usage = {
    schema_version: 'ai-routing-usage-v1',
    days: 1,
    limit: 20,
    window: { start_utc: '2026-09-03T00:00:00+00:00', end_utc: '2026-09-03T01:00:00+00:00', timezone: 'UTC' },
    groups: [],
    top_cost_endpoints: [
        { endpoint: '/api/unknown', attempts: 1, live_attempts: 1, successes: 0, fallbacks: 0, total_tokens: null, known_total_tokens: 0, estimated_cost_usd: null, known_estimated_cost_usd: '0', unknown_usage_attempts: 1, unknown_cost_attempts: 1, usage_completeness: 0, cost_completeness: 0, latency_ms: { p50: 30, p95: 30 } },
        { endpoint: '/api/high', attempts: 2, live_attempts: 2, successes: 2, fallbacks: 1, total_tokens: 900, known_total_tokens: 900, estimated_cost_usd: '0.4', known_estimated_cost_usd: '0.4', unknown_usage_attempts: 0, unknown_cost_attempts: 0, usage_completeness: 1, cost_completeness: 1, latency_ms: { p50: 20, p95: 25 } },
    ],
    top_operations: [
        { operation: 'decisive_text', attempts: 2, live_attempts: 2, successes: 2, fallbacks: 1, total_tokens: 900, known_total_tokens: 900, estimated_cost_usd: '0.4', known_estimated_cost_usd: '0.4', unknown_usage_attempts: 0, unknown_cost_attempts: 0, usage_completeness: 1, cost_completeness: 1, latency_ms: { p50: 20, p95: 25 } },
    ],
    totals: {
        attempts: 3, live_attempts: 3, breaker_skipped_attempts: 0, successes: 2, fallbacks: 1,
        input_tokens: 700, cached_input_tokens: 100, output_tokens: 180, reasoning_tokens: 20, total_tokens: 880,
        known_input_tokens: 700, known_output_tokens: 180, known_total_tokens: 880,
        estimated_cost_usd: '0.5', known_estimated_cost_usd: '0.5', unknown_usage_attempts: 0,
        quarantined_usage_attempts: 0, unknown_cost_attempts: 0, usage_completeness: 1, cost_completeness: 1,
        latency_ms: { p50: 20, p95: 30 },
    },
    openai_shares: { attempts: 0.333333, tokens: 0.25, cost: 0.4 },
    fallback_count: 1,
    fallback_attempt_share: 0.333333,
    hold_review: { available: false, count: null, rate: null, reason: 'final_outcome_not_recorded' },
    freshness: { status: 'fresh', last_event_at: '2026-09-03T00:59:00+00:00', age_seconds: 60, ttl_seconds: 300 },
    generated_at: '2026-09-03T01:00:00+00:00',
} as const;

beforeEach(() => {
    vi.clearAllMocks();
    mockApi.getLlmRoutingStatus.mockResolvedValue(status);
    mockApi.getLlmUsage.mockResolvedValue(usage);
});

describe('LlmRoutingCostCard', () => {
    it('loads status and UTC-today usage independently and renders dense cost controls', async () => {
        render(<LlmRoutingCostCard />);

        const card = await screen.findByRole('region', { name: 'LLM 라우팅 비용' });
        expect(mockApi.getLlmUsage).toHaveBeenCalledWith({ days: 1, limit: 20 });
        expect(within(card).getByText('880')).toBeInTheDocument();
        expect(within(card).getByText('$0.5')).toBeInTheDocument();
        expect(within(card).getByText('호출 33.3%')).toBeInTheDocument();
        expect(within(card).getByText('토큰 25.0%')).toBeInTheDocument();
        expect(within(card).getByText('비용 40.0%')).toBeInTheDocument();
        expect(within(card).getByText('Fallback 1회 · 33.3%')).toBeInTheDocument();
        expect(within(card).getByText('HOLD_REVIEW 미집계')).toBeInTheDocument();
        expect(within(card).getByRole('progressbar', { name: 'OpenAI 일일 비용 예산 사용률' })).toHaveAttribute('aria-valuenow', '20');
        expect(within(card).getByText('인증 실패 · 백업 사용 중')).toBeInTheDocument();
        expect(within(card).getByText('breaker open')).toBeInTheDocument();
        expect(within(card).getByText('health fresh')).toBeInTheDocument();
    });

    it('sorts known endpoint spend before unknown rows and labels unknown values', async () => {
        render(<LlmRoutingCostCard />);
        const table = await screen.findByRole('table', { name: 'LLM 엔드포인트별 비용' });
        const rows = within(table).getAllByRole('row');

        expect(rows[1]).toHaveTextContent('/api/high');
        expect(rows[2]).toHaveTextContent('/api/unknown');
        expect(rows[2]).toHaveTextContent('사용량 미확인');
        expect(rows[2]).toHaveTextContent('비용 미확인');
    });

    it('keeps usable usage data when status fails and never renders raw errors', async () => {
        mockApi.getLlmRoutingStatus.mockRejectedValueOnce(new Error('Bearer raw-secret'));
        render(<LlmRoutingCostCard />);

        expect(await screen.findByText('880')).toBeInTheDocument();
        expect(screen.getByText('상태 조회 실패')).toBeInTheDocument();
        expect(screen.queryByText(/raw-secret/)).toBeNull();
    });

    it('retains last good data after a later independent refresh failure', async () => {
        render(<LlmRoutingCostCard />);
        expect(await screen.findByText('880')).toBeInTheDocument();
        mockApi.getLlmUsage.mockRejectedValueOnce(new Error('prompt and token must not leak'));

        fireEvent.click(screen.getByRole('button', { name: 'LLM 라우팅 비용 새로고침' }));

        await waitFor(() => expect(mockApi.getLlmUsage).toHaveBeenCalledTimes(2));
        expect(screen.getByText('880')).toBeInTheDocument();
        expect(screen.getByText('사용량 조회 실패 · 마지막 정상 데이터')).toBeInTheDocument();
        expect(screen.queryByText(/must not leak/)).toBeNull();
    });

    it('distinguishes known zero from unknown and omits a budget bar without a cap', async () => {
        mockApi.getLlmUsage.mockResolvedValueOnce({
            ...usage,
            totals: { ...usage.totals, input_tokens: 0, output_tokens: 0, reasoning_tokens: 0, total_tokens: 0, estimated_cost_usd: '0' },
        });
        mockApi.getLlmRoutingStatus.mockResolvedValueOnce({
            ...status,
            freshness: { ...status.freshness, status: 'stale' },
            budget: { ...status.budget, daily_cap_usd_configured: false, daily_cap_usd: null, used_usd: null, remaining_usd: null, usage_percent: null, status: 'unavailable' },
        });
        render(<LlmRoutingCostCard />);

        const card = await screen.findByRole('region', { name: 'LLM 라우팅 비용' });
        expect(within(card).getByText('0')).toBeInTheDocument();
        expect(within(card).getByText('$0')).toBeInTheDocument();
        expect(within(card).getByText('health stale')).toBeInTheDocument();
        expect(within(card).queryByRole('progressbar')).toBeNull();
        expect(within(card).getByText('일일 비용 상한 미설정')).toBeInTheDocument();
    });

    it('does not mislabel an incomplete configured budget as unconfigured', async () => {
        mockApi.getLlmRoutingStatus.mockResolvedValueOnce({
            ...status,
            budget: {
                ...status.budget,
                daily_cap_usd_configured: true,
                daily_cap_usd: '2.5',
                used_usd: null,
                remaining_usd: null,
                usage_percent: null,
                status: 'incomplete',
            },
        });
        render(<LlmRoutingCostCard />);

        const card = await screen.findByRole('region', { name: 'LLM 라우팅 비용' });
        expect(within(card).queryByRole('progressbar')).toBeNull();
        expect(within(card).getByText('예산 사용량 미확인')).toBeInTheDocument();
        expect(within(card).queryByText('일일 비용 상한 미설정')).toBeNull();
    });
});
