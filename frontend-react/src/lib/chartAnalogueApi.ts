import { fetchAuthAPI } from './api';

export type ChartAnalogueStatus = 'ready' | 'missing_index' | 'stale_data' | 'insufficient_history' | 'insufficient_analogues' | 'unavailable';

export interface ChartAnalogueHorizon {
    sessions: number;
    median_return_pct: number;
    p10_return_pct: number;
    p90_return_pct: number;
    up_frequency_pct: number;
    median_price: number;
    lower_price: number;
    upper_price: number;
}

export interface ChartAnalogueFanPoint {
    session: number;
    median_price: number;
    p10_price: number;
    p90_price: number;
}

export interface ChartAnaloguePrediction {
    symbol: string;
    target: string;
    status: ChartAnalogueStatus;
    mode: 'shadow';
    model_version: string;
    as_of: string;
    lookback_sessions: number;
    sample_count: number;
    source: {
        name?: string;
        source_id?: string;
        latest_session?: string;
        corpus_latest_session?: string;
        captured_at?: string;
        query_captured_at?: string | null;
        query_collection_status?: string;
        collection_summary?: Record<string, number>;
        price_basis?: string;
        built_at?: string;
        rows?: number;
        symbols?: number;
        freshness_days?: number;
    } | null;
    diagnostics: {
        eligible_windows?: number;
        rejected?: Record<string, number>;
        latest_session?: string;
        freshness_days?: number;
    };
    history: Array<{ date: string; close: number }>;
    horizons: ChartAnalogueHorizon[];
    fan: ChartAnalogueFanPoint[];
    neighbors: Array<{
        symbol: string;
        target: string;
        start_date: string;
        end_date: string;
        outcome_end_date: string;
        captured_at: string;
        similarity: number;
        returns: Record<string, number>;
    }>;
    warnings: string[];
}

const statuses: ChartAnalogueStatus[] = ['ready', 'missing_index', 'stale_data', 'insufficient_history', 'insufficient_analogues', 'unavailable'];
const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

/** Validate numerical inputs at the API boundary; invalid distributions never reach the SVG. */
function isPrediction(value: unknown, symbol: string): value is ChartAnaloguePrediction {
    if (!isRecord(value) || value.symbol !== symbol || typeof value.target !== 'string'
        || !statuses.includes(value.status as ChartAnalogueStatus) || value.mode !== 'shadow'
        || typeof value.as_of !== 'string' || typeof value.model_version !== 'string'
        || !isNumber(value.lookback_sessions) || !isNumber(value.sample_count) || value.sample_count < 0
        || !Array.isArray(value.history) || !Array.isArray(value.horizons) || !Array.isArray(value.fan)
        || !Array.isArray(value.neighbors) || !Array.isArray(value.warnings)
        || !value.warnings.every(warning => typeof warning === 'string')) return false;

    if (!value.history.every(row => isRecord(row) && typeof row.date === 'string' && isNumber(row.close) && row.close > 0)) return false;
    if (value.source !== null) {
        if (!isRecord(value.source)) return false;
        const source = value.source;
        if (source.query_captured_at !== undefined && source.query_captured_at !== null && typeof source.query_captured_at !== 'string') return false;
        if (!['name', 'source_id', 'latest_session', 'corpus_latest_session', 'captured_at', 'query_collection_status', 'price_basis', 'built_at']
            .every(key => source[key] === undefined || typeof source[key] === 'string')) return false;
    }
    if (value.status !== 'ready') return true;
    if (value.sample_count < 1 || value.history.length < 2 || value.fan.length < 2 || !isRecord(value.source)) return false;
    const horizonKeys = ['median_return_pct', 'p10_return_pct', 'p90_return_pct', 'up_frequency_pct', 'median_price', 'lower_price', 'upper_price'];
    if (!value.horizons.every(row => isRecord(row) && isNumber(row.sessions)
        && horizonKeys.every(key => isNumber(row[key]))
        && (row.up_frequency_pct as number) >= 0 && (row.up_frequency_pct as number) <= 100
        && (row.lower_price as number) > 0 && (row.lower_price as number) <= (row.median_price as number)
        && (row.median_price as number) <= (row.upper_price as number))) return false;
    const horizons = value.horizons;
    if (![5, 20, 40].every(sessions => horizons.some(row => row.sessions === sessions))) return false;
    if (!value.fan.every(row => isRecord(row) && isNumber(row.session) && row.session >= 0
        && isNumber(row.median_price) && isNumber(row.p10_price) && isNumber(row.p90_price)
        && row.p10_price > 0 && row.p10_price <= row.median_price && row.median_price <= row.p90_price)) return false;
    return value.neighbors.every(row => isRecord(row) && typeof row.symbol === 'string'
        && typeof row.target === 'string' && typeof row.start_date === 'string' && typeof row.end_date === 'string'
        && isNumber(row.similarity) && row.similarity >= 0 && row.similarity <= 1
        && isRecord(row.returns) && Object.values(row.returns).every(isNumber));
}

export async function fetchChartAnalogue(symbol: string, token?: string): Promise<ChartAnaloguePrediction> {
    if (!/^\d{6}$/.test(symbol)) throw new Error('국내 종목 코드 6자리를 입력해 주세요.');
    const result = await fetchAuthAPI<unknown>(`/api/admin/mirofish/chart-analogue/${symbol}`, token);
    if (!isPrediction(result, symbol)) throw new Error('응답 형식이 올바르지 않습니다. 다시 조회해 주세요.');
    return result;
}
