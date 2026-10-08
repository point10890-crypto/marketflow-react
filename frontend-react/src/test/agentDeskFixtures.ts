import type { AlphaLabStatus } from '@/lib/alphaLabApi';
import type { AccountPlan, AgentDesk } from '@/lib/agentDeskApi';
import type { OpportunityEngine } from '@/lib/opportunityEngine';

export const deskNow = Date.parse('2026-10-05T01:00:00Z');
export function deskBoard(): OpportunityEngine {
    const identity = { decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), source_audit_hash: 'c'.repeat(64) };
    return { schema_version: 1, policy_version: 'profit-opportunity-v1', ...identity, generated_at: '2026-10-04T10:00:00Z',
        latest_session: '2026-10-02', entry_session: '2026-10-05', valid_until: '2026-10-05T06:30:00Z', status: 'ready', research_only: true, live_orders: false,
        coverage: { inspected: 100, eligible: 7, selected: 1 }, alternatives: [], reasons: [],
        stages: [{ id: 'data', status: 'passed', detail: '저장 가격과 출처 확인', count: 100 }],
        candidates: [{ ...identity, opportunity_id: 'd'.repeat(64), symbol: '005930', name: '삼성전자', market: 'KR', strategy_id: 'momentum', rank: 1,
            action: 'entry_candidate', label: '현재 진입 후보', why_stock: '두 기간의 비용과 불확실성을 대조했습니다.',
            why_now: '새 관측 가격이 참고 상한 안에 있습니다.', next_action: '참고 가격과 손실 한도를 직접 확인하세요.',
            quote_session: '2026-10-02', source_at: '2026-10-04T09:00:00Z', current_price: 60000,
            quote_at: '2026-10-05T00:59:30Z', fetched_at: '2026-10-05T00:59:45Z', quote_source: 'KIS:J:FHKST03010200+FHKST01010100',
            valid_until: '2026-10-05T06:30:00Z', reference_weight: .04,
            plan: { basis: 'observed_quote_reference', entry_low: 60000, entry_high: 61200, stop_price: 57000, target_price: 66000, horizon_sessions: 10 },
            ranking: { stress_mean_net_return: .03, standard_error: .005, conservative_score: .0202, correlation_penalty: 0, score: .0202, calibration_samples: 40, confirmation_samples: 20 },
            kelly: { raw_fraction: .16, fraction: .25, cap: .05, account_risk_cap: .01 },
            audit: { status: 'passed', reasons: [], independent_validation: false }, reasons: [] }],
    };
}
const roleIds = ['regime', 'fx_liquidity', 'flow', 'disclosure', 'sector', 'event', 'micro', 'sentiment', 'auditor', 'leader', 'risk_guard', 'review'];
export function deskContract(): AgentDesk {
    return { schema_version: 1, policy_version: 'evidence-account-v1', generated_at: '2026-10-05T01:00:00Z', order_allowed: false,
        roles: roleIds.map(id => ({ id, title: `${id} 검사`, status: 'unavailable', detail: '인증한 추가 자료가 없습니다.' })),
        candidates: [{ opportunity_id: 'd'.repeat(64), symbol: '005930', name: '삼성전자', state: 'Conditional plan',
            audit: { status: 'passed', reasons: [], independent_sources: 2 },
            probability: { kind: 'unavailable', bull: null, base: null, bear: null, reason: '교정된 전망 자료가 없습니다.' },
            invalidation: { price_below: 57000, price_above: 61200, valid_until: '2026-10-05T06:30:00Z', detail: '손절·추격 상한을 벗어나면 새 진입을 보류합니다.' }, missing: [] }],
        promotion: { stage: 'M0', reasons: ['forward_validation_pending'] } };
}
export function deskStatus(): AlphaLabStatus {
    return { schema_version: 1, state: 'ready', generated_at: '2026-10-04T10:00:00Z', error: null,
        opportunity_engine: deskBoard(), agent_desk: deskContract(),
        report: { schema_version: 1, mode: 'research', as_of: '2026-10-04T10:00:00Z', input_fingerprint: 'b'.repeat(64), latest_session: '2026-10-02',
            universe: { ranked_count: 100, quality_count: 100, inspected_count: 100, scope_date: '2026-10-02' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [], forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } } };
}
export function accountResult(): AccountPlan {
    return { schema_version: 1, policy_version: 'evidence-account-v1', status: 'ready', reasons: [], generated_at: '2026-10-05T01:00:00Z',
        valid_until: '2026-10-05T01:02:00Z', order_allowed: false,
        limits: { trade_risk: .005, daily_stop: -.015, weekly_stop: -.04, symbol_cap: .05, theme_cap: .3, cash_floor: .4 },
        plans: [{ opportunity_id: 'd'.repeat(64), symbol: '005930', name: '삼성전자', status: 'ready', reasons: [], quantity: 6,
            weight: .03672, budget: 367200, planned_loss: 25200, entry_price: 61200, stop_price: 57000, target_price: 66000 }] };
}
