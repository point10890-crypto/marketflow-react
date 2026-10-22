export const candidateDeskNow = Date.parse('2026-10-22T12:00:00Z');

export function candidateDeskFixture(count = 3) {
    const names = [['005930', '삼성전자'], ['000660', 'SK하이닉스'], ['035420', 'NAVER']];
    return {
        schema_version: 1, policy_version: 'cross-sectional-candidates-v3', state: 'ready',
        decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64), generated_at: '2026-10-22T11:45:00Z',
        latest_session: '2026-10-22', entry_session: '2026-10-23', valid_until: '2026-10-23T06:30:00Z',
        source: { provider: 'KIS', venue: 'KRX', adjusted_requested: true, captured_at: '2026-10-22T11:40:00Z',
            historical_vintage_verified: false, corporate_action_adjustment_verified: false },
        candidates: names.slice(0, count).map(([symbol, name], index) => ({ symbol, name, rank: index + 1,
            strength_score: 82 - index, quote_session: '2026-10-22',
            reason_facts: ['60거래일 이동평균 위', '코호트 20거래일 수익률 중앙값 상회'],
            plan: { entry_price: 60000, entry_upper: 61200, stop_price: 57000, target_price: 66000,
                horizon_sessions: 10, loss_fraction: .05 },
            risk: { reference_weight: .05, kelly_fraction: .25, raw_kelly: .25, approved_exposure: 0, live_orders: false },
        })),
        funnel: [{ id: 'inspected', label: '검사 종목', count: 52 }, { id: 'selected', label: '선택 종목', count }],
        evidence: {
            formation: { samples: 30, wins: 18, win_rate: .6, mean_net_return: .012, stress_mean_net_return: .009, block_count: 6, unique_symbols: 8 },
            confirmation: { samples: 10, wins: 6, win_rate: .6, mean_net_return: .01, stress_mean_net_return: .007, block_count: 3, unique_symbols: 5 },
        },
        reasons: [] as string[], live_orders: false, approved_exposure: 0,
    };
}

export function candidateStatusFixture() {
    return {
        schema_version: 1, state: 'held', generated_at: '2026-10-22T11:45:00Z', error: null,
        report: {
            schema_version: 1, mode: 'research', as_of: '2026-10-22T11:45:00Z',
            universe: { ranked_count: 52, quality_count: 52, inspected_count: 52, scope_date: '2026-10-22' },
            provenance: { price_basis: 'provider_adjusted', price_adjustment_verified: false,
                historical_vintage_verified: false, point_in_time_universe_verified: false, current_cohort_bias: true, analysis_ready: false },
            champion: { strategy_id: null, selection_basis: 'validation_only', status: 'held', reasons: [] },
            strategies: [], candidates: [], agents: [], warnings: [],
            forward: { decisions: 0, matured: 0, win_rate: null, mean_net_return: null },
            protocol: { train_end: '2023-12-31', validation_end: '2024-12-31', test_start: '2025-01-01', horizon_sessions: 10, source_references: [] },
        },
    };
}

export function contextualCandidateDeskFixture(count = 2) {
    const original = candidateDeskFixture(count);
    const training_end = '2026-10-08';
    return {
        ...original, policy_version: 'contextual-candidates-v4',
        model: { name: 'causal-context-neighbors-v1', status: 'experimental', training_end,
            comparison_interpretation: 'v3_unconditional_retrospective_control_not_v4_holdout', validation: 'forward_collecting' },
        candidates: original.candidates.map(row => ({ ...row, risk: { ...row.risk, reference_weight: .01 },
            model_evidence: { samples: 50, wins: 30, win_rate: .6, block_count: 8, unique_symbols: 12,
                mean_net_return: .025, stress_mean_net_return: .02, expected_net_return: .012,
                expected_stress_net_return: .009, training_end, neighbors_exclude_target: true } })),
        evidence: { formation: { ...original.evidence.formation, mean_net_return: .0081, stress_mean_net_return: .005 },
            confirmation: { ...original.evidence.confirmation, wins: 4, win_rate: .4, mean_net_return: -.025, stress_mean_net_return: -.0289 } },
    };
}

export const candidateEntryNow = Date.parse('2026-10-23T00:05:00Z');
export function candidateMonitoringFixture(count = 2) {
    return { state: 'monitoring', checked_at: '2026-10-23T00:05:00Z', decision_id: 'a'.repeat(64),
        quotes: candidateDeskFixture(count).candidates.map(row => ({ symbol: row.symbol, state: 'within_band',
            price: 60500, opening_price: 59000, quote_at: '2026-10-23T00:04:30Z', fetched_at: '2026-10-23T00:04:55Z',
            source: 'KIS:J:FHKST03010200+FHKST01010100' })) };
}
