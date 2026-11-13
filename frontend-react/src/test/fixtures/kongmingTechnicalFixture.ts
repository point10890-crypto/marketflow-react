export function kongmingTechnicalFixture() {
    const bins = Array.from({ length: 24 }, (_, index) => ({
        index, low: 70000 + index * 100, high: 70100 + index * 100,
        volume: 1000, volume_pct: 100 / 24, traded_value: 71000000,
    }));
    return {
        schema_version: 1, agent: 'volume_profile_20d_v1', status: 'ready', last_run_at: '2026-11-12T20:31:00+09:00',
        items: [{
            symbol: '005930', name: '삼성전자', status: 'ready', reason: null,
            as_of: '2026-11-12', fetched_at: '2026-11-12T20:31:00+09:00', window_start: '2026-10-16', window_end: '2026-11-12',
            sessions_required: 20, sessions_used: 20, reference_price: 71150,
            total_volume: 24000, total_traded_value: 1704000000,
            poc: bins[4], support: bins[4], resistance: bins[15], current_zone: bins[11], bins,
            method: 'daily_uniform_range_overlap_v1', source: 'KIS:FHKST03010100:J:D:1',
            calendar_source: 'KIS:KOSPI:FHKUP03500100', price_basis: 'KIS_KRX_raw_J_D_1',
            limitations: ['일봉 고가·저가 구간에 균등 배분한 추정치입니다.'], fingerprint: 'fixture-profile',
        }],
    };
}
