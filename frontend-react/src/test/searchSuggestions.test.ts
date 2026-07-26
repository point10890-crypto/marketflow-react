import { describe, expect, it } from 'vitest';

import { buildSuggestions, type SearchIndex } from '@/lib/searchSuggestions';

const INDEX: SearchIndex = {
    stocks: [
        { rank: 1, name: '삼성전자', ticker: '005930', industry: '반도체 및 반도체 장비' },
        { rank: 5, name: '삼성바이오로직스', ticker: '207940', industry: '생명공학' },
        { rank: 2, name: 'SK하이닉스', ticker: '000660', industry: '반도체 및 반도체 장비' },
        { rank: 9, name: 'LG 화학', ticker: '051910', industry: '화학' },
        { rank: 4, name: '현대차', ticker: '005380', industry: '자동차' },
        { rank: 420, name: '삼성공조', ticker: '006660', industry: '미분류' },
    ],
    industries: [
        { name: '반도체 및 반도체 장비', count: 2 },
        { name: '생명공학', count: 1 },
        { name: '자동차', count: 1 },
        { name: '화학', count: 1 },
    ],
};

describe('buildSuggestions', () => {
    it('returns nothing for an empty query', () => {
        expect(buildSuggestions(INDEX, '')).toEqual([]);
        expect(buildSuggestions(INDEX, '   ')).toEqual([]);
    });

    it('matches stock names by prefix', () => {
        const labels = buildSuggestions(INDEX, '삼성').map((s) => s.label);
        expect(labels).toContain('삼성전자');
        expect(labels).toContain('삼성바이오로직스');
    });

    it('orders equally-good matches by source rank, not alphabetically', () => {
        // "삼성" matches six names; alphabetical order buries 삼성전자 below 삼성공조.
        const labels = buildSuggestions(INDEX, '삼성').map((s) => s.label);
        expect(labels[0]).toBe('삼성전자');
        expect(labels.indexOf('삼성바이오로직스')).toBeLessThan(labels.indexOf('삼성공조'));
    });

    it('omits the placeholder industry from the hint', () => {
        const hit = buildSuggestions(INDEX, '삼성공조')[0];
        expect(hit.hint).toBe('006660');
        expect(hit.hint).not.toContain('미분류');
    });

    it('ranks prefix matches above mid-string matches', () => {
        const labels = buildSuggestions(INDEX, '하이닉스').map((s) => s.label);
        expect(labels[0]).toBe('SK하이닉스');
    });

    it('matches a stock by ticker digits', () => {
        const hits = buildSuggestions(INDEX, '005930');
        expect(hits[0].label).toBe('삼성전자');
        expect(hits[0].type).toBe('stock');
    });

    it('ignores spacing differences in the query', () => {
        expect(buildSuggestions(INDEX, 'lg화학').map((s) => s.label)).toContain('LG 화학');
        expect(buildSuggestions(INDEX, 'LG 화 학').map((s) => s.label)).toContain('LG 화학');
    });

    it('is case-insensitive', () => {
        expect(buildSuggestions(INDEX, 'sk').map((s) => s.label)).toContain('SK하이닉스');
    });

    it('suggests industries with their stock count', () => {
        const industry = buildSuggestions(INDEX, '반도체').find((s) => s.type === 'industry');
        expect(industry).toBeDefined();
        expect(industry!.label).toBe('반도체 및 반도체 장비');
        expect(industry!.hint).toBe('2종목');
    });

    it('inserts the bare stock name, not "이름 (코드)"', () => {
        // The run table filters on a substring of stock_name/ticker/industry, so a
        // combined "삼성전자 (005930)" would match nothing and empty the table.
        const hit = buildSuggestions(INDEX, '삼성전자')[0];
        expect(hit.value).toBe('삼성전자');
        expect(hit.hint).toContain('005930');
    });

    it('inserts the industry name for industry rows', () => {
        const industry = buildSuggestions(INDEX, '자동차').find((s) => s.type === 'industry');
        expect(industry!.value).toBe('자동차');
    });

    it('puts stocks before industries at equal match quality', () => {
        const types = buildSuggestions(INDEX, '자동차').map((s) => s.type);
        expect(types.indexOf('stock')).toBeLessThan(types.indexOf('industry'));
    });

    it('honours the limit', () => {
        expect(buildSuggestions(INDEX, '삼', 1)).toHaveLength(1);
    });

    it('returns nothing when the query matches nothing', () => {
        expect(buildSuggestions(INDEX, 'zzzz없는종목')).toEqual([]);
    });

    it('survives an empty or malformed index', () => {
        expect(buildSuggestions({ stocks: [], industries: [] }, '삼성')).toEqual([]);
        expect(buildSuggestions(null, '삼성')).toEqual([]);
    });
});
