export function surgeTraceFixture() {
    return {
        schema_version: 1, status: 'partial', generated_at: '2026-11-10T10:15:00+09:00', source_as_of: '2026-11-10T10:00:00+09:00',
        threshold: { change_pct: 5, trading_value: 2000000000 },
        operation: { state: 'ready', last_run_at: '2026-11-10T10:15:00+09:00', source_status: 'fresh', processed: 2, pending: 0 },
        items: [{
            id: '2026-11-10:005930', symbol: '005930', name: '삼성전자', market: 'KOSPI', session: '2026-11-10',
            first_detected_at: '2026-11-10T10:05:00+09:00', price_observed_at: '2026-11-10T10:00:00+09:00',
            price: 71200, change_pct: 6.37, trading_value: 2345678910, status: 'prior_material',
            summary: '삼성전자 공급 계약 보도가 관측 전에 발표됐습니다.',
            evidence: [{
                id: 'news-1', kind: 'news', title: '삼성전자 공급 계약 발표', url: 'https://www.businesspost.co.kr/BP?command=article_view&num=123',
                source: 'omni', publisher: '비즈니스포스트', published_at: '2026-11-10T09:20:00+09:00', published_precision: 'timestamp',
                first_received_at: '2026-11-10T10:10:00+09:00', timing: 'before_observation', discovered_after_observation: true,
                category: 'contract', direction: 'positive', verification: 'reported_unverified', duplicate_count: 2,
            }, {
                id: 'news-2', kind: 'news', title: '삼성전자 상승 이후 위험 요인 보도', url: 'https://example.com/news/risk',
                source: 'google_news', publisher: '예시 언론사', published_at: '2026-11-10T10:12:00+09:00', published_precision: 'timestamp',
                first_received_at: '2026-11-10T10:14:00+09:00', timing: 'after_observation', discovered_after_observation: true,
                category: 'risk', direction: 'negative', verification: 'reported_unverified', duplicate_count: 0,
            }, {
                id: 'filing-1', kind: 'disclosure', title: '삼성전자 실적 공시', url: 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261110000123',
                source: 'opendart', publisher: 'OpenDART', published_at: '2026-11-10', published_precision: 'date',
                first_received_at: '2026-11-10T10:14:00+09:00', timing: 'same_day_unknown', discovered_after_observation: true,
                category: 'earnings', direction: 'mixed', verification: 'issuer_matched', duplicate_count: 0,
            }],
            checks: [{ source: 'omni', status: 'ready', checked_at: '2026-11-10T10:15:00+09:00', count: 2 },
                { source: 'google_news', status: 'error', checked_at: '2026-11-10T10:15:00+09:00', count: null }],
            limitations: ['기사에 제시된 재료 후보이며 인과관계는 입증되지 않았습니다.'],
        }, {
            id: '2026-11-10:000660', symbol: '000660', name: 'SK하이닉스', market: 'KOSPI', session: '2026-11-10',
            first_detected_at: '2026-11-10T10:05:00+09:00', price_observed_at: '2026-11-10T10:00:00+09:00',
            price: 188000, change_pct: 5.15, trading_value: 4234567890, status: 'unresolved', summary: null,
            evidence: [], checks: [{ source: 'opendart', status: 'empty', checked_at: '2026-11-10T10:15:00+09:00', count: 0 }], limitations: [],
        }],
    };
}
