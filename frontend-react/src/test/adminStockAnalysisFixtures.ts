import type { AdminStockAnalysisStatus } from '@/lib/adminStockAnalysisApi';

export const analysisNow = '2026-10-01T10:00:00Z';
export function stockAnalysis(symbol = '042700', name = '한미반도체'): AdminStockAnalysisStatus {
    return {
        schema_version: 1, policy_version: 'admin-symbol-alpha-v1', state: 'ready',
        target: { symbol, name, market: 'KR' }, generated_at: analysisNow, error: null,
        result: {
            latest_session: '2026-10-01', analyzed_at: analysisNow, input_fingerprint: 'a'.repeat(64),
            source: { mode: 'saved_snapshot', captured_at: '2026-10-01T09:00:00Z', price_basis: 'unadjusted',
                price_adjustment_verified: false, historical_vintage_verified: false, point_in_time_universe_verified: false },
            quality: { status: 'passed', reasons: [] },
            stages: [{ id: 'proposal', label: '매매 제안', state: 'complete' }], warnings: [], diagnostics: [],
            candidate: { symbol, name, strategy_id: 'mean_reversion', score: .012, last_close: 100000,
                evidence: { selection_basis: 'calibration_stress_mean_then_confirmation', stronger_evidence: false,
                    retrospective: true, independent_validation: false,
                    calibration: { samples: 30, wins: 18, losses: 12, zeros: 0, win_rate: .6, mean_net_return: .02,
                        stress_mean_net_return: .012, compounded_trade_return: .5, stress_compounded_trade_return: .3,
                        start: '2021-01-04', end: '2025-09-30', last_exit_session: '2025-09-15', t_stat: 1.4 },
                    confirmation: { samples: 10, wins: 6, losses: 4, zeros: 0, win_rate: .6, mean_net_return: .016,
                        stress_mean_net_return: .009, compounded_trade_return: .15, stress_compounded_trade_return: .09,
                        start: '2025-10-01', end: '2026-10-01', last_exit_session: '2026-09-17', t_stat: 1.2 } },
                plan: { entry_price: 100000, stop_price: 92000, target_price: 116000, loss_fraction: .08, atr: 5000 },
                risk: { weight: 0, status: 'held', reasons: [], p: .6, kelly_raw: .2, research_weight: .05,
                    quarter_kelly_fraction: .05, planned_account_risk: .004 }, setup_active: true, quote_session: '2026-10-01',
                proposal: { action: 'buy', label: '매수 제안', reason: '과거 조건과 최근 확인 조건을 통과했습니다.',
                    next_step: '다음 장 시가를 확인하세요.', proposed_weight: .05, input_session: '2026-10-01',
                    derived_at: analysisNow, valid_until: '2026-10-02T06:30:00Z',
                    plan_basis: 'last_closed_price_next_open_reference', order_allowed: false }, reasons: [] },
        },
    };
}
