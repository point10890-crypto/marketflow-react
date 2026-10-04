import { fetchAuthAPI, postAuthAPI } from './api';

export interface AlphaLabPerformance {
    net_total_return: number | null;
    max_drawdown: number | null;
    trades: number;
    win_rate: number | null;
}
export interface AlphaLabStrategy {
    strategy_id: string;
    name: string;
    validation: { trades: number; win_rate: number | null; mean_net_return: number | null };
    test: AlphaLabPerformance;
    stress: AlphaLabPerformance;
    qualified: boolean;
    reasons: string[];
}
export interface AlphaLabCandidate {
    symbol: string;
    name: string;
    strategy_id: string;
    score: number;
    last_close: number | null;
    plan: { entry_price: number; stop_price: number; target_price: number; loss_fraction: number } | null;
    risk: { weight: number; status: string; reasons: string[]; p: number | null; kelly_raw: number | null };
    reasons: string[];
}
export interface AlphaLabReport {
    schema_version: 1;
    mode: 'research';
    as_of: string;
    universe: { ranked_count: number; quality_count: number; inspected_count: number; scope_date: string | null };
    provenance: {
        price_basis: string;
        price_adjustment_verified: boolean;
        historical_vintage_verified: boolean;
        point_in_time_universe_verified: boolean;
        current_cohort_bias: boolean;
        analysis_ready: boolean;
    };
    champion: { strategy_id: string | null; selection_basis: 'validation_only'; status: string; reasons: string[] };
    strategies: AlphaLabStrategy[];
    candidates: AlphaLabCandidate[];
    agents: Array<{ id: string; name: string; status: string; detail: string }>;
    warnings: string[];
    forward: { decisions: number; matured: number; win_rate: number | null; mean_net_return: number | null };
    protocol: {
        train_end: string;
        validation_end: string;
        test_start: string;
        horizon_sessions: number;
        source_references: Array<{ name: string; url: string }>;
    };
}
export interface AlphaLabStatus {
    schema_version: 1;
    state: 'missing' | 'running' | 'ready' | 'held' | 'failed';
    generated_at: string | null;
    report: AlphaLabReport | null;
    error: string | null;
}

const invalid = '전략 실험 응답 형식이 올바르지 않습니다. 저장 결과를 다시 확인해 주세요.';
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const count = (value: unknown): value is number => finite(value) && Number.isInteger(value) && value >= 0;
const fraction = (value: unknown) => finite(value) && value >= 0 && value <= 1;
const nullableFinite = (value: unknown) => value === null || finite(value);
const nullableRate = (value: unknown) => value === null || fraction(value);
const safeText = (value: unknown, max = 300): value is string => typeof value === 'string' && value.length <= max
    && !/[\u0000-\u001f]|[A-Za-z]:[\\/]|(?:^|\s)\/(?:home|srv|tmp|Users|private)\b|\.env\b|(?:api[_-]?key|access[_-]?token|secret)\s*[:=]/i.test(value);
const label = (value: unknown): value is string => safeText(value, 120) && !!value.trim();
const reasons = (value: unknown): value is string[] => Array.isArray(value) && value.length <= 100 && value.every(item => label(item));
const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
const timestamp = (value: unknown): value is string => typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

function publicReference(value: unknown): boolean {
    if (!record(value) || !label(value.name) || typeof value.url !== 'string' || value.url.length > 1000) return false;
    try {
        const url = new URL(value.url);
        return url.protocol === 'https:' && !url.username && !url.password
            && !/^(?:localhost|127\.|0\.|192\.168\.|10\.|\[::1\])/i.test(url.hostname);
    } catch { return false; }
}
function performance(value: unknown): boolean {
    return record(value) && count(value.trades) && nullableRate(value.win_rate)
        && nullableFinite(value.net_total_return) && nullableFinite(value.max_drawdown)
        && (value.trades > 0 || value.win_rate === null);
}
function strategy(value: unknown): value is AlphaLabStrategy {
    return record(value) && label(value.strategy_id) && label(value.name) && typeof value.qualified === 'boolean'
        && reasons(value.reasons) && record(value.validation) && count(value.validation.trades)
        && nullableRate(value.validation.win_rate) && nullableFinite(value.validation.mean_net_return)
        && (value.validation.trades > 0 || value.validation.win_rate === null && value.validation.mean_net_return === null)
        && performance(value.test) && performance(value.stress);
}
function candidate(value: unknown, strategies: Set<string>): value is AlphaLabCandidate {
    if (!record(value) || typeof value.symbol !== 'string' || !/^\d{6}$/.test(value.symbol) || !label(value.name)
        || !label(value.strategy_id) || !strategies.has(value.strategy_id) || !finite(value.score)
        || !(value.last_close === null || finite(value.last_close) && value.last_close > 0)
        || !reasons(value.reasons) || !record(value.risk) || !finite(value.risk.weight)
        || value.risk.weight < 0 || value.risk.weight > .2 || !label(value.risk.status) || !reasons(value.risk.reasons)
        || !nullableRate(value.risk.p) || !nullableFinite(value.risk.kelly_raw)) return false;
    if (value.plan === null) return value.risk.weight === 0;
    const p = value.plan;
    return record(p) && finite(p.entry_price) && finite(p.stop_price) && finite(p.target_price)
        && p.stop_price > 0 && p.stop_price < p.entry_price && p.target_price > p.entry_price
        && finite(p.loss_fraction) && p.loss_fraction > 0 && p.loss_fraction < 1
        && Math.abs(p.loss_fraction - (p.entry_price - p.stop_price) / p.entry_price) < .0001;
}

function validReport(value: unknown): value is AlphaLabReport {
    if (!record(value) || value.schema_version !== 1 || value.mode !== 'research' || !timestamp(value.as_of)
        || !record(value.universe) || !record(value.provenance) || !record(value.champion)
        || !Array.isArray(value.strategies) || value.strategies.length > 12 || !value.strategies.every(strategy)
        || !Array.isArray(value.candidates) || value.candidates.length > 3 || !Array.isArray(value.agents)
        || value.agents.length > 12 || !reasons(value.warnings) || !record(value.forward) || !record(value.protocol)) return false;
    const u = value.universe;
    const p = value.provenance;
    const c = value.champion;
    const f = value.forward;
    const protocol = value.protocol;
    const ids = new Set(value.strategies.map(row => row.strategy_id));
    if (ids.size !== value.strategies.length || !count(u.ranked_count) || u.ranked_count > 100
        || !count(u.quality_count) || u.quality_count > u.ranked_count || !count(u.inspected_count)
        || u.inspected_count > u.quality_count || !(u.scope_date === null || date(u.scope_date))
        || !label(p.price_basis) || !['price_adjustment_verified', 'historical_vintage_verified', 'point_in_time_universe_verified', 'current_cohort_bias', 'analysis_ready'].every(key => typeof p[key] === 'boolean')
        || c.selection_basis !== 'validation_only' || !(c.strategy_id === null || label(c.strategy_id) && ids.has(c.strategy_id))
        || !label(c.status) || !reasons(c.reasons) || !count(f.decisions) || !count(f.matured)
        || !nullableRate(f.win_rate) || !nullableFinite(f.mean_net_return)
        || f.matured === 0 && (f.win_rate !== null || f.mean_net_return !== null)
        || !date(protocol.train_end) || !date(protocol.validation_end) || !date(protocol.test_start)
        || protocol.train_end >= protocol.validation_end || protocol.validation_end >= protocol.test_start
        || !count(protocol.horizon_sessions) || protocol.horizon_sessions < 1 || protocol.horizon_sessions > 252
        || !Array.isArray(protocol.source_references) || protocol.source_references.length > 20
        || !protocol.source_references.every(publicReference)) return false;
    const symbols = new Set<string>();
    let exposure = 0;
    for (const row of value.candidates) {
        if (!candidate(row, ids) || symbols.has(row.symbol)) return false;
        symbols.add(row.symbol); exposure += row.risk.weight;
    }
    return exposure <= .6 + 1e-8 && value.agents.every(row => record(row) && label(row.id) && label(row.name)
        && label(row.status) && safeText(row.detail));
}

/** Only finite, identified research evidence crosses the API boundary; raw worker errors are never rendered. */
export function validateAlphaLabStatus(value: unknown): AlphaLabStatus {
    if (!record(value) || value.schema_version !== 1 || !['missing', 'running', 'ready', 'held', 'failed'].includes(String(value.state))
        || !(value.generated_at === null || timestamp(value.generated_at)) || !(value.error === null || typeof value.error === 'string')
        || !(value.report === null || validReport(value.report))
        || ['ready', 'held'].includes(String(value.state)) && value.report === null) throw new Error(invalid);
    return value as unknown as AlphaLabStatus;
}
export async function fetchAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await fetchAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', token));
}
export async function startAlphaLab(token?: string): Promise<AlphaLabStatus> {
    return validateAlphaLabStatus(await postAuthAPI<unknown>('/api/admin/mirofish/alpha-lab', {}, token));
}
