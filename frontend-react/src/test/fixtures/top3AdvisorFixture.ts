const origin = '2026-11-06T11:31:00Z';
const generated = '2026-11-08T02:08:00Z';
export function advisorFixture() {
    const finding = { text: '원문과 공시 대조가 필요합니다.', claim_status: 'missing', evidence_ids: ['saved:1'], quotes: [] };
    const rows = [{ symbol: '021240', name: '코웨이' }, { symbol: '028050', name: '삼성E&A' }, { symbol: '032640', name: 'LG유플러스' }].map((row, i) => ({
        ...row, market: 'KR', rank: i + 1, baseline_rank: i + 1, score: 61 - i, basis: 'research_watchlist', entry_status: 'held',
        source_at: origin, reference_price: 100000, plan: null, score_components: { news_count: 0, official_evidence_available: false, price_evidence_available: false },
        hold_reasons: ['t_stat_below_two'], evidence_ids: ['saved:1'], strengths: [], risks: [finding], what_to_watch: [finding],
    }));
    return { schema_version: 1, status: 'ready', generated_at: generated, decision_id: 'a'.repeat(64), input_fingerprint: 'b'.repeat(64),
        source_origin_at: origin, source_cutoff_at: generated, coverage: { inspected: 49, pool: 5, shortlisted: 5, with_recent_news: 0, with_verified_filings: 0, with_verified_prices: 0, source_count: 1 },
        warnings: ['historical_price_vintage_unverified'], top3: rows, live_orders: false, empty_reason: null,
        debate: { debate_complete: true, ranking_basis: 'grounded_debate', stages: ['analyst', 'critic', 'chair'].map(role => ({
            role, status: 'SUCCESS_PRIMARY', rows, generated_at: generated, provider: 'anthropic', model: 'test-model', fallback_reason: null,
        })) }, sources: [{ evidence_id: 'saved:1', title: '저장된 정량 분석', source: 'AlphaLab', url: null, published_at: origin, fetched_at: origin,
            verification_status: 'sealed', target_symbols: rows.map(row => row.symbol), available_at_original_decision: true }],
    };
}
