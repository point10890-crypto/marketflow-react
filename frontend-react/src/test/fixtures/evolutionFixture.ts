import type { EvolutionArmId } from '@/lib/evolutionContext';

export const evolutionIdentity = { decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), source_audit_hash: 'c'.repeat(64) };
export const evolutionNow = Date.parse('2026-10-14T12:00:00Z');
export const evolutionDecisionAt = '2026-10-14T11:30:00Z';
export function evolutionBoardFixture() {
    return { schema_version: 1, policy_version: 'profit-opportunity-v1', ...evolutionIdentity, generated_at: evolutionDecisionAt,
        latest_session: '2026-10-14', entry_session: '2026-10-15', valid_until: '2026-10-15T06:30:00Z', status: 'held', research_only: true, live_orders: false,
        coverage: { inspected: 100, eligible: 7, selected: 0 }, alternatives: [], stages: [], reasons: [], candidates: [] };
}
export function evolutionFixture() {
    const ids: EvolutionArmId[] = ['control', 'entry-band-v1', 'recovery-confirmed-v1', 'positive-rank-v1'];
    return { schema_version: 1, protocol_version: 'alpha-evolution-v1', protocol_hash: 'd'.repeat(64),
        generated_at: '2026-10-14T11:40:00Z', declared_at: '2026-10-14T10:00:00Z', status_id: 'e'.repeat(64), status: 'ready', binding: { ...evolutionIdentity },
        phase: 'collecting_nomination', next_step: '다음 결정 거래일의 첫 선정과 종료 결과를 관측합니다.',
        return_basis: 'equal_three_slot_watchlist_not_account_pnl',
        research_only: true, live_orders: false, approved_exposure: 0,
        window: { decision_sessions: 106, nomination_sessions: 36, embargo_sessions: 10, confirmation_sessions: 60,
            maturation_sessions: 10, block_sessions: 10, minimum_blocks: 6, enrolled_sessions: 2, resolved_sessions: 1, maturation_observed: 0 },
        nomination: { status: 'pending', arm_id: null as EvolutionArmId | null, session_count: 36, reason: 'nomination_window_incomplete' },
        review: { status: 'collecting', arm_id: null as EvolutionArmId | null, reasons: ['future_window_incomplete'], limitations: ['paper_costs_and_fills_not_brokerage_execution'],
            entered_outcomes: 0, control_entered_outcomes: 0, completed_blocks: 0,
            normal_mean: null as number | null, stress_mean: null as number | null, paired_advantage: null as number | null,
            stress_paired_advantage: null as number | null, block_lower_bound: null as number | null, downside_tail_delta: null as number | null },
        arms: ids.map((id, index) => ({ id, label: id,
            selected: index === 2 ? [] : [{ symbol: '005930', name: '삼성전자', market: 'KR', strategy_id: 'mean_reversion', slot: 1 }],
            counts: { entered: 2, resolved: 3, closed: 1, skipped: 1, cash: 1, unfilled: 0, pending: 2, open: 1, missing: 0,
                revised: 1, paired_sessions: 1, missed_control_winners: index === 0 ? 0 : 1, avoided_control_losers: 0 },
            metrics: { mean_net_return: -.01, stress_mean_net_return: -.014,
                paired_advantage: index === 0 ? 0 : -.002, stress_paired_advantage: index === 0 ? 0 : -.002, downside_tail_loss: .02 },
            reasons: index === 2 ? ['recovery_not_confirmed'] : [],
        })), reasons: ['future_window_incomplete'],
    };
}
export function evolutionStatusFixture(evolution: unknown = evolutionFixture()) {
    return { schema_version: 1, state: 'held', generated_at: evolutionDecisionAt, error: null, opportunity_engine: evolutionBoardFixture(), evolution,
        report: { schema_version: 1, mode: 'research', as_of: evolutionDecisionAt, input_fingerprint: evolutionIdentity.input_fingerprint, latest_session: '2026-10-14',
            universe: { ranked_count: 100, quality_count: 42, inspected_count: 42, scope_date: '2026-10-14' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: true, historical_vintage_verified: false,
                point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: true },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [],
            forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2019-12-31', validation_end: '2022-12-31', test_start: '2023-01-01', horizon_sessions: 10, source_references: [] } },
    };
}

/** Synthetic completed window for contract tests; these are not observed performance results. */
export function completedEvolutionFixture() {
    const value = evolutionFixture();
    value.phase = 'awaiting_review'; value.window.enrolled_sessions = 106; value.window.resolved_sessions = 106; value.window.maturation_observed = 10;
    value.nomination = { status: 'fixed', arm_id: 'entry-band-v1', session_count: 36, reason: 'nomination_fixed' };
    value.review = { status: 'awaiting_review', arm_id: 'entry-band-v1', reasons: ['research_candidate_awaiting_review'],
        limitations: ['paper_costs_and_fills_not_brokerage_execution'],
        entered_outcomes: 180, control_entered_outcomes: 180, completed_blocks: 6,
        normal_mean: .01, stress_mean: .009, paired_advantage: .002, stress_paired_advantage: .002, block_lower_bound: .0001, downside_tail_delta: -.001 };
    value.arms.forEach(arm => { arm.counts = { entered: 318, resolved: 318, closed: 318, skipped: 0, cash: 0, unfilled: 0, pending: 0, open: 0, missing: 0,
        revised: 0, paired_sessions: 106, missed_control_winners: 0, avoided_control_losers: 0 }; });
    value.reasons = [];
    return value;
}
