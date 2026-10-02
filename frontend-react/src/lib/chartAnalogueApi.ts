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

export interface ChartAnalogueEvaluationReturns {
    baseline_net_return_pct: number | null;
    challenger_net_return_pct: number | null;
    excess_return_pct: number | null;
}

export interface ChartAnalogueEvaluationHorizon extends ChartAnalogueEvaluationReturns {
    sessions: 5 | 20 | 40;
    paired_days: number;
    pending_days: number;
    blocked_days: number;
}

export interface ChartAnalogueEvaluationRecord {
    workflow_id: string;
    decision_at: string;
    status: string;
    reason: string | null;
    baseline: Array<{ symbol: string; target: string }>;
    challenger: Array<{ symbol: string; target: string }>;
    horizons: Array<ChartAnalogueEvaluationReturns & {
        sessions: 5 | 20 | 40;
        status: 'pending' | 'matured' | 'blocked';
        observed_sessions: number;
    }>;
}

export interface ChartAnalogueEvaluationReport {
    schema_version: 1;
    status: 'collecting' | 'ready' | 'unavailable';
    evaluated_at: string | null;
    protocol: 'chart_median20_v1';
    ranking_effect: 'none';
    cost_bps: 23;
    slippage_bps: 10;
    counts: { recorded: number; eligible_days: number; pending: number; blocked: number; intraday_excluded: number };
    horizons: ChartAnalogueEvaluationHorizon[];
    recent: ChartAnalogueEvaluationRecord[];
    warnings: string[];
}

const isCount = (value: unknown): value is number => isNumber(value) && Number.isInteger(value) && value >= 0;
const isExplicitTimestamp = (value: unknown): value is string => typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && Number.isFinite(Date.parse(value));
const isEvaluationSession = (value: unknown) => value === 5 || value === 20 || value === 40;
const returnKeys = ['baseline_net_return_pct', 'challenger_net_return_pct', 'excess_return_pct'] as const;

/** Pending outcomes are explicitly null; a zero is accepted only for an evaluated comparison. */
function validEvaluationReturns(row: Record<string, unknown>, measured: boolean) {
    return returnKeys.every(key => measured ? isNumber(row[key]) : row[key] === null);
}

function isEvaluationReport(value: unknown): value is ChartAnalogueEvaluationReport {
    if (!isRecord(value) || value.schema_version !== 1
        || typeof value.status !== 'string' || !['collecting', 'ready', 'unavailable'].includes(value.status)
        || (value.evaluated_at !== null && !isExplicitTimestamp(value.evaluated_at))
        || value.protocol !== 'chart_median20_v1' || value.ranking_effect !== 'none'
        || value.cost_bps !== 23 || value.slippage_bps !== 10 || !isRecord(value.counts)
        || !Array.isArray(value.horizons) || !Array.isArray(value.recent) || !Array.isArray(value.warnings)
        || !value.warnings.every(warning => typeof warning === 'string')) return false;
    const counts = value.counts;
    if (!['recorded', 'eligible_days', 'pending', 'blocked', 'intraday_excluded'].every(key => isCount(counts[key]))) return false;
    const horizons = value.horizons;
    if (horizons.length !== 3 || new Set(horizons.map(row => isRecord(row) ? row.sessions : null)).size !== 3
        || !horizons.every(row => isRecord(row) && isEvaluationSession(row.sessions)
            && isCount(row.paired_days) && isCount(row.pending_days) && isCount(row.blocked_days)
            && validEvaluationReturns(row, row.paired_days > 0))) return false;
    const validPicks = (picks: unknown) => Array.isArray(picks) && picks.length <= 3
        && picks.every(pick => isRecord(pick) && typeof pick.symbol === 'string' && /^\d{6}$/.test(pick.symbol)
            && typeof pick.target === 'string');
    return value.recent.every(row => {
        if (!isRecord(row) || typeof row.workflow_id !== 'string' || !row.workflow_id.trim()
            || !isExplicitTimestamp(row.decision_at) || typeof row.status !== 'string' || !row.status.trim()
            || (row.reason !== null && typeof row.reason !== 'string')
            || !validPicks(row.baseline) || !validPicks(row.challenger) || !Array.isArray(row.horizons)
            || row.horizons.length > 3) return false;
        const rows = row.horizons;
        return new Set(rows.map(item => isRecord(item) ? item.sessions : null)).size === rows.length
            && rows.every(item => isRecord(item) && isEvaluationSession(item.sessions)
                && typeof item.status === 'string' && ['pending', 'matured', 'blocked'].includes(item.status) && isCount(item.observed_sessions)
                && (item.status !== 'matured' || item.observed_sessions >= (item.sessions as number))
                && validEvaluationReturns(item, item.status === 'matured'));
    });
}

export async function fetchChartAnalogueEvaluation(token?: string): Promise<ChartAnalogueEvaluationReport> {
    const result = await fetchAuthAPI<unknown>('/api/admin/mirofish/chart-analogue/evaluation', token);
    if (!isEvaluationReport(result)) throw new Error('비교 관측 응답 형식이 올바르지 않습니다.');
    return result;
}

export interface ChartAnalogueCandidate {
    symbol: string;
    name: string;
}

export async function fetchChartAnalogueCandidates(query: string, token?: string): Promise<ChartAnalogueCandidate[]> {
    const target = query.trim();
    if (!target) return [];
    const errorMessage = '종목 검색을 완료하지 못했습니다. 다시 시도해 주세요.';
    if (target.length > 80) throw new Error(errorMessage);

    try {
        const result = await fetchAuthAPI<unknown>(
            `/api/admin/mirofish/targets/search?target=${encodeURIComponent(target)}&limit=8`, token, 8000,
        );
        if (!isRecord(result) || typeof result.target !== 'string' || !Array.isArray(result.candidates)) {
            throw new Error(errorMessage);
        }
        const candidates: ChartAnalogueCandidate[] = [];
        const symbols = new Set<string>();
        for (const row of result.candidates) {
            if (!isRecord(row) || typeof row.symbol !== 'string' || !/^\d{6}$/.test(row.symbol)
                || (row.asset_type !== undefined && row.asset_type !== 'equity')
                || (row.market !== undefined && !['KR', 'KOSPI', 'KOSDAQ', 'KONEX'].includes(row.market as string))
                || (row.name !== null && row.name !== undefined && typeof row.name !== 'string')
                || (row.display_name !== null && row.display_name !== undefined && typeof row.display_name !== 'string')
                || (row.name === undefined && typeof row.display_name !== 'string') || symbols.has(row.symbol)) continue;
            const name = (typeof row.name === 'string' ? row.name.trim() : '')
                || (typeof row.display_name === 'string' ? row.display_name.trim() : '') || row.symbol;
            candidates.push({ symbol: row.symbol, name });
            symbols.add(row.symbol);
            if (candidates.length === 8) break;
        }
        return candidates;
    } catch {
        throw new Error(errorMessage);
    }
}
