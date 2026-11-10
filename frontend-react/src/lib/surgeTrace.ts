import { fetchAPI } from './api';

export interface SurgeEvidence {
    id: string; kind: 'news' | 'disclosure'; title: string; url: string | null;
    source: string | null; publisher: string | null; published_at: string | null;
    published_precision: 'timestamp' | 'date' | 'unknown'; first_received_at: string | null;
    timing: 'before_observation' | 'after_observation' | 'same_day_unknown' | 'unknown';
    discovered_after_observation: boolean | null; category: string | null;
    direction: 'positive' | 'negative' | 'neutral' | 'mixed'; verification: string | null; duplicate_count: number | null;
}
export interface SurgeCheck { source: string; status: string; checked_at: string | null; count: number | null }
export interface SurgeTrace {
    id: string; symbol: string; name: string; market: 'KOSPI' | 'KOSDAQ'; session: string;
    first_detected_at: string | null; price_observed_at: string | null;
    price: number | null; change_pct: number | null; trading_value: number | null;
    status: string; summary: string | null; evidence: SurgeEvidence[]; checks: SurgeCheck[]; limitations: string[];
}
export interface SurgeTraceView {
    schema_version: 1; status: string; generated_at: string | null; source_as_of: string | null;
    threshold: { change_pct: number; trading_value: number }; items: SurgeTrace[];
    operation: { state: string; last_run_at: string | null; source_status: string; processed: number | null; pending: number | null };
}
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && !!v.trim() && v.length <= 4000
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(v);
const nullableText = (v: unknown) => v === null || text(v);
const number = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const count = (v: unknown) => v === null || number(v) && Number.isInteger(v) && v >= 0;
const date = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
    && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const timestamp = (v: unknown): v is string => typeof v === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const time = (v: unknown) => v === null || timestamp(v);

/** Public article links only; never turn a payload into a script or local-service link. */
export function surgeSourceUrl(value: unknown): string | null {
    if (!text(value) || /[\s\\]/.test(value)) return null;
    try {
        const url = new URL(value);
        const embeddedCredentials = [url.username, url.password].some(Boolean);
        if (embeddedCredentials) return null;
        if (!['https:', 'http:'].includes(url.protocol) || url.port
            || !url.hostname.includes('.') || /^[\d.]+$/.test(url.hostname) || url.hostname.startsWith('[')
            || /(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(url.hostname)) return null;
        return value;
    } catch { return null; }
}

/** Fail closed on malformed prices, clocks and links. Unknown statuses are rendered as unverified. */
export function validateSurgeTraces(value: unknown): SurgeTraceView {
    const invalid = () => { throw new Error('저장된 급등 관측 결과를 확인하지 못했습니다.'); };
    if (!object(value) || value.schema_version !== 1 || !text(value.status) || !time(value.generated_at)
        || !(time(value.source_as_of) || date(value.source_as_of)) || !object(value.threshold)
        || !number(value.threshold.change_pct) || value.threshold.change_pct < 0
        || !number(value.threshold.trading_value) || value.threshold.trading_value < 0
        || !object(value.operation) || !text(value.operation.state) || !time(value.operation.last_run_at)
        || !text(value.operation.source_status) || !count(value.operation.processed) || !count(value.operation.pending)
        || !Array.isArray(value.items) || value.items.length > 20) return invalid();
    const evidence = (e: unknown) => object(e) && text(e.id) && ['news', 'disclosure'].includes(String(e.kind))
        && text(e.title) && (e.url === null || surgeSourceUrl(e.url) !== null) && nullableText(e.source) && nullableText(e.publisher)
        && ['timestamp', 'date', 'unknown'].includes(String(e.published_precision))
        && (e.published_at === null || (e.published_precision === 'date' ? date(e.published_at) : timestamp(e.published_at)))
        && time(e.first_received_at) && ['before_observation', 'after_observation', 'same_day_unknown', 'unknown'].includes(String(e.timing))
        && (e.discovered_after_observation === null || typeof e.discovered_after_observation === 'boolean')
        && nullableText(e.category) && ['positive', 'negative', 'neutral', 'mixed'].includes(String(e.direction))
        && nullableText(e.verification) && count(e.duplicate_count);
    const check = (c: unknown) => object(c) && text(c.source) && text(c.status) && time(c.checked_at) && count(c.count);
    for (const row of value.items) {
        if (!object(row) || !text(row.id) || typeof row.symbol !== 'string' || !/^[0-9A-Z]{6}$/.test(row.symbol)
            || !text(row.name) || !['KOSPI', 'KOSDAQ'].includes(String(row.market)) || !date(row.session)
            || !time(row.first_detected_at) || !time(row.price_observed_at)
            || !(row.price === null || number(row.price) && row.price > 0)
            || !(row.change_pct === null || number(row.change_pct) && row.change_pct >= -100)
            || !(row.trading_value === null || number(row.trading_value) && row.trading_value >= 0)
            || !text(row.status) || !nullableText(row.summary) || !Array.isArray(row.evidence) || row.evidence.length > 100
            || !row.evidence.every(evidence) || new Set(row.evidence.map(e => e.id)).size !== row.evidence.length
            || !Array.isArray(row.checks) || row.checks.length > 30 || !row.checks.every(check)
            || !Array.isArray(row.limitations) || row.limitations.length > 50 || !row.limitations.every(text)) return invalid();
    }
    if (new Set(value.items.map(row => row.id)).size !== value.items.length
        || new Set(value.items.map(row => `${row.session}:${row.symbol}`)).size !== value.items.length) return invalid();
    return value as unknown as SurgeTraceView;
}

/** Read saved results only. This does not invoke scanners, paid AI, or collection. */
export async function fetchSurgeTraces(): Promise<SurgeTraceView> {
    return validateSurgeTraces(await fetchAPI<unknown>('/api/admin/mirofish/kongming/surge-traces', 8000));
}
