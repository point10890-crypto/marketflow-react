import { fetchAuthAPI, postAuthAPI } from './api';

export interface ChartAnalogueKellyMetric {
    sample_count: number; distinct_symbols: number; period_start: string; period_end: string;
    net_win_rate_pct: number; wilson_lower_pct: number; payoff_ratio: number | null;
    expectancy_pct: number; median_pct: number; p10_pct: number; p90_pct: number; median_similarity: number;
}
export interface ChartAnalogueKellyCase {
    symbol: string; target: string; anchor_date: string; entry_date: string; exit_date: string; captured_at: string;
    similarity: number; gross_return_pct: number; net_return_pct: number; entry_close: number; exit_close: number;
    input: number[]; future: number[];
}
export interface ChartAnalogueKellyCandidate {
    rank: number; symbol: string; target: string; market: string; market_cap: number; universe_rank: number;
    score: number; research_status: 'stable' | 'watch' | 'insufficient'; reasons: string[];
    reference_session: string | null; current_close: number | null;
    train: ChartAnalogueKellyMetric | null; validation: ChartAnalogueKellyMetric | null;
    kelly: { empirical_fraction: number | null; half_fraction: number | null; capped_fraction: number | null;
        research_weight: number; approved_weight: null; volatility_guard: boolean; portfolio_scale: number };
    chart: { query: number[]; cases: ChartAnalogueKellyCase[]; future_basis?: string };
}
export interface ChartAnalogueKellyReport {
    schema_version: 1; policy_id: 'chart-analogue-kelly-v1'; mode: 'research'; status: 'ready' | 'blocked';
    as_of: string; generated_at: string;
    source: { source_id?: string; price_basis?: string; latest_session?: string; captured_at?: string; built_at?: string; name?: string; [key: string]: unknown };
    universe: { ranked: number; quality_passed: number; processed: number; valid: number; stable: number;
        rejected: Record<string, number> | number; as_of: string | null; reference_symbols: number };
    policy: { horizon_sessions: number; cost_bps: number; min_samples: number; min_similarity: number;
        max_positions: number; max_weight: number; max_exposure: number; min_cash: number; kelly_fraction: number };
    candidates: ChartAnalogueKellyCandidate[]; leaderboard: ChartAnalogueKellyCandidate[]; warnings: string[];
    approval: { status: 'held'; reasons: string[]; approved_exposure: 0 };
    portfolio: { research_exposure: number; research_cash: number };
    forward?: { decision_days: number; matured_trades: number; pending_trades: number; net_win_rate_pct: number | null;
        expectancy_pct: number | null; independent: false };
}
export interface ChartAnalogueKellyEnvelope {
    state: 'none' | 'running' | 'done' | 'error'; processed: number; total: number; error: string | null;
    freshness: 'current' | 'stale' | 'missing'; started_at: string | null; report: ChartAnalogueKellyReport | null;
}

const policy = { horizon_sessions: 20, cost_bps: 33, min_samples: 30, min_similarity: .8,
    max_positions: 3, max_weight: .2, max_exposure: .6, min_cash: .4, kelly_fraction: .5 };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const between = (v: unknown, min: number, max: number): v is number => finite(v) && v >= min && v <= max;
const count = (v: unknown): v is number => finite(v) && Number.isInteger(v) && v >= 0;
const code = (v: unknown): v is string => typeof v === 'string' && /^\d{6}$/.test(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim();
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 200 && v.every(item => typeof item === 'string');
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
    && Number.isFinite(Date.parse(`${v}T00:00:00Z`)) && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
const stamp = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const near = (a: number, b: number, tolerance = .00001) => Math.abs(a - b) <= tolerance;
const nullableFraction = (v: unknown, max = 1) => v === null || between(v, 0, max);
const series = (v: unknown, size: number): v is number[] => Array.isArray(v) && v.length === size && v.every(n => finite(n) && n > 0);
const message = '차트·켈리 응답 형식이 올바르지 않습니다. 다시 조회해 주세요.';

function validMetric(v: unknown, cutoffDate: string): v is ChartAnalogueKellyMetric | null {
    if (v === null) return true;
    return record(v) && count(v.sample_count) && v.sample_count > 0 && count(v.distinct_symbols)
        && v.distinct_symbols > 0 && v.distinct_symbols <= v.sample_count
        && date(v.period_start) && date(v.period_end) && v.period_start <= v.period_end && v.period_end <= cutoffDate
        && between(v.net_win_rate_pct, 0, 100) && between(v.wilson_lower_pct, 0, v.net_win_rate_pct)
        && (v.payoff_ratio === null || finite(v.payoff_ratio) && v.payoff_ratio >= 0)
        && finite(v.expectancy_pct) && finite(v.p10_pct) && finite(v.median_pct) && finite(v.p90_pct)
        && v.p10_pct <= v.median_pct && v.median_pct <= v.p90_pct && between(v.median_similarity, 0, 1);
}
function validCase(v: unknown, asOf: number, cutoffDate: string): v is ChartAnalogueKellyCase {
    if (!record(v) || !code(v.symbol) || !text(v.target) || !date(v.anchor_date) || !date(v.entry_date) || !date(v.exit_date)
        || v.anchor_date >= v.entry_date || v.entry_date >= v.exit_date || v.exit_date > cutoffDate
        || !stamp(v.captured_at) || Date.parse(v.captured_at) > asOf || !between(v.similarity, 0, 1)
        || !finite(v.gross_return_pct) || !finite(v.net_return_pct)
        || !finite(v.entry_close) || v.entry_close <= 0 || !finite(v.exit_close) || v.exit_close <= 0
        || !series(v.input, 64) || !near(v.input[63], 100, .0001) || !series(v.future, 21)) return false;
    const gross = 100 * (v.exit_close / v.entry_close - 1);
    return near(v.gross_return_pct, gross, .0001) && near(v.net_return_pct, gross - policy.cost_bps / 100, .0001)
        && near(100 * (v.future[20] / v.future[0] - 1), gross, .0001);
}
function validCandidate(v: unknown, asOf: number, cutoffDate: string, ranked: number, blocked = false): v is ChartAnalogueKellyCandidate {
    if (!record(v) || !count(v.rank) || v.rank < (blocked ? 0 : 1) || v.rank > 100 || !code(v.symbol) || !text(v.target)
        || typeof v.market !== 'string' || !['KR', 'KOSPI', 'KOSDAQ'].includes(v.market)
        || !finite(v.market_cap) || v.market_cap <= 0 || !count(v.universe_rank) || v.universe_rank < 1 || v.universe_rank > ranked
        || !finite(v.score) || !['stable', 'watch', 'insufficient'].includes(v.research_status as string) || !strings(v.reasons)
        || !(v.reference_session === null || date(v.reference_session) && v.reference_session <= cutoffDate)
        || !(v.current_close === null || finite(v.current_close) && v.current_close > 0)
        || !validMetric(v.train, cutoffDate) || !validMetric(v.validation, cutoffDate) || !record(v.kelly) || !record(v.chart)) return false;
    const k = v.kelly;
    if (!nullableFraction(k.empirical_fraction) || !nullableFraction(k.half_fraction, .5) || !nullableFraction(k.capped_fraction, .2)
        || !between(k.research_weight, 0, .2) || k.approved_weight !== null || typeof k.volatility_guard !== 'boolean'
        || !between(k.portfolio_scale, 0, 1) || !Array.isArray(v.chart.cases) || v.chart.cases.length > 3
        || !v.chart.cases.every(item => validCase(item, asOf, cutoffDate))
        || !(Array.isArray(v.chart.query) && v.chart.query.length === 0 || series(v.chart.query, 64) && near(v.chart.query[63], 100, .0001))) return false;
    if ((v.reference_session === null) !== (v.current_close === null)) return false;
    if (v.train !== null && v.validation !== null && v.train.period_end >= v.validation.period_start) return false;
    if (k.empirical_fraction === null) {
        if (k.half_fraction !== null || k.capped_fraction !== null || k.research_weight !== 0) return false;
    } else if (k.half_fraction === null || k.capped_fraction === null || !near(k.half_fraction as number, .5 * (k.empirical_fraction as number))
        || !near(k.capped_fraction as number, Math.min(.2, k.half_fraction as number) * (k.volatility_guard ? .5 : 1))) return false;
    if (v.research_status !== 'stable' && k.research_weight !== 0) return false;
    const stableMetric = (metric: ChartAnalogueKellyMetric | null) => metric !== null && metric.sample_count >= 30
        && metric.net_win_rate_pct >= 60 && metric.wilson_lower_pct >= 60 && metric.payoff_ratio !== null && metric.payoff_ratio >= 1 && metric.expectancy_pct > 0;
    if (v.research_status === 'stable' && (!stableMetric(v.train) || !stableMetric(v.validation))) return false;
    if (k.research_weight > 0 && (!v.train || !v.validation || v.chart.query.length !== 64 || v.current_close === null
        || v.train.sample_count < 30 || v.validation.sample_count < 30 || !near(k.research_weight,
            (k.capped_fraction as number) * (k.portfolio_scale as number)))) return false;
    return true;
}

/** Reject malformed/mislabelled stock, Kelly, cost and provenance evidence before plotting or allocating a scenario. */
export function validateChartAnalogueKellyReport(value: unknown): ChartAnalogueKellyReport {
    if (!record(value) || value.schema_version !== 1 || value.policy_id !== 'chart-analogue-kelly-v1' || value.mode !== 'research'
        || !['ready', 'blocked'].includes(value.status as string) || !stamp(value.as_of) || !stamp(value.generated_at)
        || !record(value.policy) || !Object.entries(policy).every(([key, expected]) => value.policy && (value.policy as Record<string, unknown>)[key] === expected)
        || !record(value.source) || !record(value.universe) || !strings(value.warnings) || !record(value.approval)
        || value.approval.status !== 'held' || value.approval.approved_exposure !== 0 || !strings(value.approval.reasons)
        || !record(value.portfolio) || !between(value.portfolio.research_exposure, 0, .6) || !between(value.portfolio.research_cash, .4, 1)
        || !near(value.portfolio.research_exposure + value.portfolio.research_cash, 1)
        || !Array.isArray(value.candidates) || value.candidates.length > 3 || !Array.isArray(value.leaderboard) || value.leaderboard.length > 100) throw new Error(message);
    const u = value.universe;
    const asOf = Date.parse(value.as_of);
    const cutoffDate = new Date(asOf + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
    if (!count(u.ranked) || u.ranked > 100 || !count(u.quality_passed) || u.quality_passed > u.ranked
        || !count(u.processed) || u.processed > u.quality_passed || !count(u.valid) || u.valid > u.processed
        || !count(u.stable) || u.stable > u.valid || !(u.as_of === null && value.status === 'blocked' || date(u.as_of) && u.as_of <= cutoffDate)
        || !count(u.reference_symbols) || u.reference_symbols > u.quality_passed
        || !(count(u.rejected) || record(u.rejected) && Object.values(u.rejected).every(count))) throw new Error(message);
    const source = value.source;
    if (value.status === 'ready' && (!text(source.source_id) || source.price_basis !== 'provider_adjusted' || !date(source.latest_session)
        || source.latest_session > cutoffDate || !stamp(source.captured_at) || Date.parse(source.captured_at) > asOf || !stamp(source.built_at))) throw new Error(message);
    const validRows = (rows: unknown[], selected: boolean) => {
        const symbols = new Set<string>(); const ranks = new Set<number>();
        return rows.every(row => {
            if (!validCandidate(row, asOf, cutoffDate, u.ranked as number, !selected && value.status === 'blocked') || symbols.has(row.symbol) || row.rank > 0 && ranks.has(row.rank)) return false;
            symbols.add(row.symbol); ranks.add(row.rank); return true;
        });
    };
    const leaderboard = value.leaderboard;
    if (value.leaderboard.length > u.quality_passed || !validRows(value.candidates, true) || !validRows(value.leaderboard, false)
        || !near(value.candidates.reduce((sum, row) => sum + row.kelly.research_weight, 0), value.portfolio.research_exposure)
        || value.candidates.some(row => !leaderboard.some(item => item.symbol === row.symbol && item.target === row.target && item.research_status === row.research_status
            && near(item.kelly.research_weight, row.kelly.research_weight)))) throw new Error(message);
    if (value.forward !== undefined) {
        const f = value.forward;
        if (!record(f) || !count(f.decision_days) || !count(f.matured_trades) || !count(f.pending_trades) || f.independent !== false
            || f.matured_trades > 0 && (!between(f.net_win_rate_pct, 0, 100) || !finite(f.expectancy_pct))
            || f.matured_trades === 0 && (f.net_win_rate_pct !== null || f.expectancy_pct !== null)) throw new Error(message);
    }
    return value as unknown as ChartAnalogueKellyReport;
}

function validateEnvelope(value: unknown): ChartAnalogueKellyEnvelope {
    if (!record(value) || !['none', 'running', 'done', 'error'].includes(value.state as string)
        || !count(value.processed) || !count(value.total) || value.total > 100 || value.processed > value.total
        || !(value.error === null || typeof value.error === 'string') || !['current', 'stale', 'missing'].includes(value.freshness as string)
        || !(value.started_at === null || stamp(value.started_at)) || value.state === 'done' && value.report === null) throw new Error(message);
    if (value.report !== null) validateChartAnalogueKellyReport(value.report);
    return value as unknown as ChartAnalogueKellyEnvelope;
}
export async function fetchChartAnalogueKelly(token?: string): Promise<ChartAnalogueKellyEnvelope> {
    return validateEnvelope(await fetchAuthAPI<unknown>('/api/admin/mirofish/chart-analogue/kelly', token));
}
export async function startChartAnalogueKelly(token?: string): Promise<ChartAnalogueKellyEnvelope> {
    return validateEnvelope(await postAuthAPI<unknown>('/api/admin/mirofish/chart-analogue/kelly', {}, token));
}
