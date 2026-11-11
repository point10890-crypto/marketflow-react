import { API_BASE, ApiError, authHeaders, fetchWithTimeout } from './api';
import { surgeSourceUrl } from './surgeTrace';

export type OutcomeFilter = 'rising' | 'all';
export interface CatalystOutcomeQuery { filter?: OutcomeFilter; page?: number; page_size?: number; symbol?: string }
export interface CatalystHorizon {
    status: 'completed' | 'pending' | 'missing' | 'blocked' | 'revised';
    entry_date: string | null; exit_date: string | null; entry_price: number | null; exit_price: number | null;
    net_return: number | null; gross_return: number | null; mfe: number | null; mae: number | null; source_revision: boolean;
}
export interface CatalystOutcomeCase {
    id: string; symbol: string; name: string; title: string; url: string | null; source: string; event_type: string;
    published_at: string | null; first_seen_at: string | null; anchor_at: string | null;
    analysis_basis: 'received' | 'retrospective'; verification: string; exclusion?: string | null;
    horizons: Record<'5' | '10' | '20', CatalystHorizon>; price_source: string; price_fetched_at: string | null;
}
export interface CatalystCandidate {
    symbol: string; name: string; rank: number; score: number; reasons: string[]; invalidation: string[];
    price: number; price_session: string; price_fetched_at: string;
    plan: { entry_price: number; stop_price: number; target_price: number };
    historical: { matured: number; positive: number; mean_net_return: number };
    latest_event: { title: string; url: string | null; first_seen_at: string; verification: string };
}
export interface CatalystOutcomes {
    schema_version: 1; status: 'ready' | 'partial' | 'missing' | 'stale' | 'failed';
    generated_at: string | null; as_of_session: string | null;
    schedule: { timezone: 'Asia/Seoul'; times: string[]; next_run_at: string; slot: string | null };
    coverage: { events_total: number; symbols_total: number; priced_symbols: number; matured_events: number;
        positive_events: number; unpriced_events: number; excluded_events: number; source_counts: Record<string, number> };
    operation: { state: string; last_attempt_at: string | null; pending_symbols: number; error: string | null };
    candidates: CatalystCandidate[]; cases: CatalystOutcomeCase[];
    pagination: { page: number; page_size: number; total: number; pages: number }; limitations: string[];
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim() && v.length <= 4000
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(v);
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown): v is number => number(v) && Number.isSafeInteger(v) && v >= 0;
const price = (v: unknown): v is number => number(v) && v > 0;
const symbol = (v: unknown): v is string => typeof v === 'string' && /^\d{6}$/.test(v);
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
    && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const timestamp = (v: unknown): v is string => typeof v === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v)
    && date(v.slice(0, 10)) && Number.isFinite(Date.parse(v));
const nullableTime = (v: unknown) => v === null || timestamp(v);
const nullableText = (v: unknown) => v === null || text(v);
const list = (v: unknown): v is string[] => Array.isArray(v) && v.length <= 100 && v.every(text);

/** Reuse the existing public-news URL policy; never link scripts, credentials or local services. */
export const catalystOutcomeSourceUrl = surgeSourceUrl;

function horizon(value: unknown): boolean {
    if (!object(value) || !['completed', 'pending', 'missing', 'blocked', 'revised'].includes(String(value.status))
        || ![value.entry_date, value.exit_date].every(v => v === null || date(v))
        || ![value.entry_price, value.exit_price].every(v => v === null || price(v))
        || ![value.net_return, value.gross_return, value.mfe, value.mae].every(v => v === null || number(v))
        || typeof value.source_revision !== 'boolean') return false;
    if (date(value.entry_date) && date(value.exit_date) && value.entry_date > value.exit_date) return false;
    return value.status !== 'completed' || date(value.entry_date) && date(value.exit_date)
        && price(value.entry_price) && price(value.exit_price) && number(value.net_return) && number(value.gross_return);
}

/** Validate quantities and provenance before displaying financial output. Unsafe links remain plain text. */
export function validateCatalystOutcomes(value: unknown): CatalystOutcomes {
    const invalid = () => { throw new Error('저장된 상승 추적 응답을 확인하지 못했습니다.'); };
    if (!object(value) || value.schema_version !== 1 || !['ready', 'partial', 'missing', 'stale', 'failed'].includes(String(value.status))
        || !nullableTime(value.generated_at) || !(value.as_of_session === null || date(value.as_of_session))
        || !object(value.schedule) || value.schedule.timezone !== 'Asia/Seoul'
        || !Array.isArray(value.schedule.times) || value.schedule.times.join(',') !== '10:00,15:00'
        || !timestamp(value.schedule.next_run_at) || !nullableText(value.schedule.slot)
        || !object(value.coverage) || !object(value.coverage.source_counts) || !object(value.operation)
        || !text(value.operation.state) || !nullableTime(value.operation.last_attempt_at)
        || !count(value.operation.pending_symbols) || !nullableText(value.operation.error)
        || !Array.isArray(value.candidates) || value.candidates.length > 3 || !Array.isArray(value.cases) || value.cases.length > 50
        || !object(value.pagination) || !list(value.limitations)) return invalid();
    const coverage = value.coverage;
    for (const key of ['events_total', 'symbols_total', 'priced_symbols', 'matured_events', 'positive_events', 'unpriced_events', 'excluded_events']) {
        if (!count(coverage[key])) return invalid();
    }
    if (!object(coverage.source_counts) || !Object.entries(coverage.source_counts).every(([key, v]) => text(key) && count(v))
        || Number(coverage.positive_events) > Number(coverage.matured_events)
        || Number(coverage.matured_events) > Number(coverage.events_total)
        || Number(coverage.priced_symbols) > Number(coverage.symbols_total)) return invalid();
    const page = value.pagination;
    if (!count(page.page) || page.page < 1 || !count(page.page_size) || page.page_size < 1 || page.page_size > 50
        || !count(page.total) || !count(page.pages) || value.cases.length > page.page_size) return invalid();
    for (const candidate of value.candidates) {
        if (!object(candidate) || !symbol(candidate.symbol) || !text(candidate.name)
            || !count(candidate.rank) || candidate.rank < 1 || candidate.rank > 3 || !number(candidate.score)
            || !list(candidate.reasons) || !list(candidate.invalidation) || !price(candidate.price)
            || !date(candidate.price_session) || !timestamp(candidate.price_fetched_at)
            || !object(candidate.plan) || !price(candidate.plan.entry_price) || !price(candidate.plan.stop_price)
            || !price(candidate.plan.target_price) || candidate.plan.stop_price >= candidate.plan.entry_price
            || candidate.plan.target_price <= candidate.plan.entry_price || !object(candidate.historical)
            || !count(candidate.historical.matured) || !count(candidate.historical.positive)
            || candidate.historical.positive < 1 || candidate.historical.positive > candidate.historical.matured
            || !number(candidate.historical.mean_net_return) || !object(candidate.latest_event)
            || !text(candidate.latest_event.title) || !nullableText(candidate.latest_event.url)
            || !timestamp(candidate.latest_event.first_seen_at) || !text(candidate.latest_event.verification)) return invalid();
    }
    for (const row of value.cases) {
        if (!object(row) || !text(row.id) || !symbol(row.symbol) || !text(row.name) || !text(row.title)
            || !nullableText(row.url) || !text(row.source) || !text(row.event_type)
            || !(nullableTime(row.published_at) || date(row.published_at))
            || !nullableTime(row.first_seen_at) || !nullableTime(row.anchor_at)
            || !['received', 'retrospective'].includes(String(row.analysis_basis))
            || row.analysis_basis === 'received' && (!timestamp(row.first_seen_at) || !timestamp(row.anchor_at))
            || !text(row.verification) || row.exclusion !== undefined && !nullableText(row.exclusion)
            || !object(row.horizons) || !horizon(row.horizons['5']) || !horizon(row.horizons['10']) || !horizon(row.horizons['20'])
            || !text(row.price_source) || !nullableTime(row.price_fetched_at)) return invalid();
    }
    if (new Set(value.candidates.map(row => row.symbol)).size !== value.candidates.length
        || new Set(value.candidates.map(row => row.rank)).size !== value.candidates.length
        || new Set(value.cases.map(row => row.id)).size !== value.cases.length) return invalid();
    return value as unknown as CatalystOutcomes;
}

/** Saved GET only: viewing this panel never starts collection, inference or an order. */
export async function fetchCatalystOutcomes(query: CatalystOutcomeQuery = {}, token?: string, signal?: AbortSignal): Promise<CatalystOutcomes> {
    const { filter = 'rising', page = 1, page_size = 10, symbol: code } = query;
    if (!['rising', 'all'].includes(filter) || !count(page) || page < 1 || !count(page_size) || page_size < 1 || page_size > 50
        || code !== undefined && !symbol(code)) throw new Error('상승 추적 조회 조건을 확인해 주세요.');
    const params = new URLSearchParams({ filter, page: String(page), page_size: String(page_size) });
    if (code) params.set('symbol', code);
    const response = await fetchWithTimeout(`${API_BASE}/api/admin/mirofish/kongming/catalyst-outcomes?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : authHeaders(), signal, cache: 'no-store',
    }, 8000);
    if (!response.ok) throw new ApiError('저장된 상승 추적 조회 실패', response.status);
    return validateCatalystOutcomes(await response.json());
}
