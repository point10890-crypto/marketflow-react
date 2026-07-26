/**
 * Autocomplete matching for the manual-stock-analysis search box.
 *
 * The whole stock/industry universe is fetched once from `/search-index`, so
 * matching happens locally: no request per keystroke, and stocks the current
 * cycle has not scraped yet still show up.
 */

export interface SearchIndexStock {
    /** Row order in the source workbook — roughly importance, 1 = 삼성전자. */
    rank?: number;
    name: string;
    ticker: string;
    industry: string;
}

/** Workbook placeholder for "industry unknown" — noise in a hint. */
const UNKNOWN_INDUSTRY = '미분류';

export interface SearchIndexIndustry {
    name: string;
    count: number;
}

export interface SearchIndex {
    stocks: SearchIndexStock[];
    industries: SearchIndexIndustry[];
}

export interface Suggestion {
    type: 'stock' | 'industry';
    /** Primary text shown in the dropdown row. */
    label: string;
    /** Secondary text: ticker + industry, or the industry's stock count. */
    hint: string;
    /** What gets written into the search box when the row is picked. */
    value: string;
}

/** Strip spaces and case so "LG 화 학" and "lg화학" match the same entry. */
function compact(text: string): string {
    return (text || '').replace(/\s+/g, '').toLowerCase();
}

/** 0 = starts with the query (ranked first), 1 = contains it, null = no match. */
function matchScore(haystack: string, needle: string): number | null {
    if (!haystack || !needle) return null;
    const index = haystack.indexOf(needle);
    if (index < 0) return null;
    return index === 0 ? 0 : 1;
}

export function buildSuggestions(
    index: SearchIndex | null | undefined,
    query: string,
    limit = 8,
): Suggestion[] {
    const needle = compact(query);
    if (!needle || !index) return [];

    const digits = (query || '').replace(/\D+/g, '');
    const scored: { score: number; typeRank: number; order: number; suggestion: Suggestion }[] = [];

    for (const stock of index.stocks || []) {
        const nameScore = matchScore(compact(stock.name), needle);
        const tickerScore = digits ? matchScore(stock.ticker || '', digits) : null;
        const score = nameScore ?? tickerScore;
        if (score === null) continue;
        const industry = stock.industry === UNKNOWN_INDUSTRY ? '' : stock.industry;
        scored.push({
            score,
            typeRank: 0,
            // Workbook order approximates market cap, so "삼성" surfaces 삼성전자
            // first instead of burying it under alphabetically earlier matches.
            order: Number.isFinite(stock.rank) ? Number(stock.rank) : Number.MAX_SAFE_INTEGER,
            suggestion: {
                type: 'stock',
                label: stock.name || stock.ticker,
                hint: [stock.ticker, industry].filter(Boolean).join(' · '),
                // Deliberately the bare name: the run table filters on a substring of
                // stock_name/ticker/industry, so "삼성전자 (005930)" would match nothing.
                value: stock.name || stock.ticker,
            },
        });
    }

    for (const industry of index.industries || []) {
        const score = matchScore(compact(industry.name), needle);
        if (score === null) continue;
        scored.push({
            score,
            typeRank: 1,
            // Bigger industries first — they are the more useful filter.
            order: -industry.count,
            suggestion: {
                type: 'industry',
                label: industry.name,
                hint: `${industry.count}종목`,
                value: industry.name,
            },
        });
    }

    scored.sort((a, b) =>
        a.score - b.score
        || a.typeRank - b.typeRank
        || a.order - b.order
        || a.suggestion.label.localeCompare(b.suggestion.label, 'ko'),
    );

    return scored.slice(0, Math.max(0, limit)).map((entry) => entry.suggestion);
}
