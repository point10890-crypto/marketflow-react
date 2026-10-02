import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchChartAnalogueCandidates } from '@/lib/chartAnalogueApi';

const api = vi.hoisted(() => ({ fetchAuthAPI: vi.fn() }));
vi.mock('@/lib/api', () => ({ fetchAuthAPI: api.fetchAuthAPI }));

const candidate = (symbol: unknown, name: unknown, fields: Record<string, unknown> = {}) => ({
    symbol, name, display_name: name, market: 'KOSPI', asset_type: 'equity', score: 100, match_type: 'name_exact', ...fields,
});
const response = (target: string, candidates: unknown[]) => ({ target, source: 'ticker_map', candidates });

describe('chart analogue stock candidate search', () => {
    beforeEach(() => { api.fetchAuthAPI.mockReset(); });

    it('trims and encodes Korean queries while forwarding the token and timeout', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('삼성전자', [candidate('005930', '삼성전자')]));

        await expect(fetchChartAnalogueCandidates('  삼성전자  ', 'member-token')).resolves.toEqual([
            { symbol: '005930', name: '삼성전자' },
        ]);
        expect(api.fetchAuthAPI).toHaveBeenCalledWith(
            '/api/admin/mirofish/targets/search?target=%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90&limit=8', 'member-token', 8000,
        );
    });

    it('encodes reserved query characters without turning them into URL parameters', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('A&B +', []));

        await expect(fetchChartAnalogueCandidates('A&B +')).resolves.toEqual([]);
        expect(api.fetchAuthAPI).toHaveBeenCalledWith('/api/admin/mirofish/targets/search?target=A%26B%20%2B&limit=8', undefined, 8000);
    });

    it.each(['', '   ', '\t\n'])('returns no candidates without a request for blank input %j', async query => {
        await expect(fetchChartAnalogueCandidates(query)).resolves.toEqual([]);
        expect(api.fetchAuthAPI).not.toHaveBeenCalled();
    });

    it('accepts the maximum query length after trimming', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('a'.repeat(80), []));

        await expect(fetchChartAnalogueCandidates(`  ${'a'.repeat(80)}  `)).resolves.toEqual([]);
        expect(api.fetchAuthAPI).toHaveBeenCalledOnce();
    });

    it('rejects a query over 80 characters without sending a request', async () => {
        await expect(fetchChartAnalogueCandidates('a'.repeat(81))).rejects.toThrow(/종목 검색/);
        expect(api.fetchAuthAPI).not.toHaveBeenCalled();
    });

    it.each([
        null,
        [],
        'internal server details',
        {},
        { target: '삼성', candidates: null },
        { target: '삼성', candidates: {} },
        { target: null, candidates: [] },
    ].map(response => ({ response })))('rejects malformed response envelopes with a generic error: %j', async ({ response }) => {
        api.fetchAuthAPI.mockResolvedValue(response);

        await expect(fetchChartAnalogueCandidates('삼성')).rejects.toThrow(/종목 검색/);
    });

    it('filters invalid candidates, keeps the first symbol occurrence, and falls back for a null name', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('삼성', [
            null,
            candidate('005930', { label: '삼성전자' }),
            candidate('005930', '삼성전자'),
            candidate('005930', '중복 삼성전자'),
            candidate('5930', '짧은 코드'),
            candidate('A05930', '문자 포함 코드'),
            candidate(5930, '숫자 코드'),
            candidate(' 000660', '공백 포함 코드'),
            candidate('035420', 123),
            candidate('035720', undefined),
            candidate('005935', null),
            candidate('000660', 'SK하이닉스', { asset_type: 'fund' }),
            candidate('000270', '기아', { market: 'NYSE' }),
        ]));

        await expect(fetchChartAnalogueCandidates('삼성')).resolves.toEqual([
            { symbol: '005930', name: '삼성전자' },
            { symbol: '005935', name: '005935' },
        ]);
    });

    it('returns at most eight distinct valid candidates in backend order', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('전자', [
            candidate('005930', '삼성전자'), candidate('005930', '삼성전자'),
            candidate('000660', 'SK하이닉스'), candidate('035420', 'NAVER'),
            candidate('035720', '카카오'), candidate('005935', '삼성전자우'),
            candidate('003690', '코리안리'), candidate('066570', 'LG전자'),
            candidate('005380', '현대차'), candidate('000270', '기아'),
        ]));

        await expect(fetchChartAnalogueCandidates('전자')).resolves.toEqual([
            { symbol: '005930', name: '삼성전자' },
            { symbol: '000660', name: 'SK하이닉스' },
            { symbol: '035420', name: 'NAVER' },
            { symbol: '035720', name: '카카오' },
            { symbol: '005935', name: '삼성전자우' },
            { symbol: '003690', name: '코리안리' },
            { symbol: '066570', name: 'LG전자' },
            { symbol: '005380', name: '현대차' },
        ]);
    });

    it('accepts the endpoint market identities and uses a string display name when the name is null', async () => {
        api.fetchAuthAPI.mockResolvedValue(response('반도체', [
            candidate('042700', '한미반도체'),
            candidate('000660', null, { display_name: 'SK하이닉스', market: 'KR' }),
            candidate('035420', 'NAVER', { market: 'KOSDAQ' }),
            candidate('035720', '카카오', { market: 'KONEX' }),
            candidate('003690', '코리안리', { market: undefined, asset_type: undefined }),
        ]));

        await expect(fetchChartAnalogueCandidates('반도체')).resolves.toEqual([
            { symbol: '042700', name: '한미반도체' },
            { symbol: '000660', name: 'SK하이닉스' },
            { symbol: '035420', name: 'NAVER' },
            { symbol: '035720', name: '카카오' },
            { symbol: '003690', name: '코리안리' },
        ]);
    });

    it('does not expose private transport errors to the search caller', async () => {
        api.fetchAuthAPI.mockRejectedValue(new Error('private provider token detail'));

        await expect(fetchChartAnalogueCandidates('삼성')).rejects.toThrow(/종목 검색/);
    });
});
