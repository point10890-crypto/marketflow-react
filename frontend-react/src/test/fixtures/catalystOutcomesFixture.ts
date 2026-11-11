export function catalystOutcomesFixture() {
    const complete = { status: 'completed', entry_date: '2026-10-12', exit_date: '2026-10-23', entry_price: 10000,
        exit_price: 11000, net_return: .0965, gross_return: .1, mfe: .15, mae: -.02, source_revision: false };
    return {
        schema_version: 1, status: 'ready', generated_at: '2026-11-11T01:00:00Z', as_of_session: '2026-11-10',
        schedule: { timezone: 'Asia/Seoul', times: ['10:00', '15:00'], next_run_at: '2026-11-11T06:00:00Z', slot: '2026-11-11T10:00' },
        coverage: { events_total: 15, symbols_total: 8, priced_symbols: 6, matured_events: 9, positive_events: 4,
            unpriced_events: 2, excluded_events: 3, source_counts: { verification: 10, omni: 5 } },
        operation: { state: 'completed', last_attempt_at: '2026-11-11T00:59:00Z', pending_symbols: 0, error: null },
        candidates: [{ symbol: '005930', name: '삼성전자', rank: 1, score: 72.5, reasons: ['완료 일봉 추세 조건 충족'],
            invalidation: ['20일 이동평균 이탈 시 재검토'], price: 70000, price_session: '2026-11-10',
            price_fetched_at: '2026-11-11T00:55:00Z', plan: { entry_price: 70000, stop_price: 65000, target_price: 80000 },
            historical: { matured: 4, positive: 2, mean_net_return: .0325 },
            latest_event: { title: '반도체 공급 계약 보도', url: 'https://www.yna.co.kr/view/AKR202611100001',
                first_seen_at: '2026-11-10T01:00:00Z', verification: 'related_filing_found' } }],
        cases: [{ id: 'event-1', symbol: '005930', name: '삼성전자', title: '반도체 수요 개선 보도',
            url: 'https://www.businesspost.co.kr/BP?command=article_view&num=1', source: 'verification', event_type: 'news',
            published_at: '2026-10-09T00:00:00Z', first_seen_at: '2026-10-09T01:00:00Z', anchor_at: '2026-10-09T01:00:00Z',
            analysis_basis: 'received', verification: 'verified_numeric_claims',
            horizons: { '5': { ...complete, exit_date: '2026-10-16', net_return: -.0235, gross_return: -.02, exit_price: 9800 },
                '10': { ...complete }, '20': { status: 'pending', entry_date: '2026-10-12', exit_date: null, entry_price: 10000,
                    exit_price: null, net_return: null, gross_return: null, mfe: null, mae: null, source_revision: false } },
            price_source: 'KIS_daily', price_fetched_at: '2026-11-11T00:55:00Z' }],
        pagination: { page: 1, page_size: 10, total: 15, pages: 2 },
        limitations: ['보존된 자료만 포함하며 전체 뉴스 이력을 뜻하지 않습니다.'],
    };
}
