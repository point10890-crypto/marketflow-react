import { fetchAPI, postAPI } from './api';

export interface TechnicalZone {
    index: number; low: number; high: number; volume: number; volume_pct: number; traded_value: number;
}
export type TechnicalStatus = 'ready' | 'pending' | 'insufficient_history' | 'source_unavailable' | 'price_event_review' | 'stale';
export interface TechnicalProfile {
    symbol: string; name: string; status: TechnicalStatus; reason: string | null;
    as_of: string | null; fetched_at: string | null; window_start: string | null; window_end: string | null;
    sessions_required: 20; sessions_used: number; reference_price: number | null;
    total_volume: number | null; total_traded_value: number | null;
    poc: TechnicalZone | null; support: TechnicalZone | null; resistance: TechnicalZone | null; current_zone: TechnicalZone | null;
    bins: TechnicalZone[]; method: 'daily_uniform_range_overlap_v1'; source: string | null;
    calendar_source: string | null; price_basis: string | null; limitations: string[]; fingerprint: string | null;
}
export interface TechnicalProfileView {
    schema_version: 1; agent: 'volume_profile_20d_v1'; status: string; last_run_at: string | null; items: TechnicalProfile[];
}
export interface TechnicalQueueReceipt { schema_version: 1; status: 'queued' | 'cached'; symbol: string }

const endpoint = '/api/admin/mirofish/kongming/technical-profiles';
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === 'string' && !!value.trim() && value.length <= 4000
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(value);
const nullableText = (value: unknown) => value === null || text(value);
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const nullableNumber = (value: unknown) => value === null || number(value);
const date = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const nullableDate = (value: unknown) => value === null || date(value);
const timestamp = (value: unknown) => value === null || typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && date(value.slice(0, 10)) && Number.isFinite(Date.parse(value));
export const isTechnicalSymbol = (value: string) => /^[0-9A-Z]{6}$/.test(value);
const zone = (value: unknown): value is TechnicalZone => object(value) && number(value.index) && Number.isInteger(value.index) && value.index < 24
    && number(value.low) && value.low > 0 && number(value.high) && value.high >= value.low && number(value.volume)
    && number(value.volume_pct) && value.volume_pct <= 100 && number(value.traded_value);
const nullableZone = (value: unknown) => value === null || zone(value);
const statuses: string[] = ['ready', 'pending', 'insufficient_history', 'source_unavailable', 'price_event_review', 'stale'];
export function isTechnicalProfile(value: unknown): value is TechnicalProfile {
    if (!object(value) || !text(value.symbol) || !isTechnicalSymbol(value.symbol) || !text(value.name)
        || !text(value.status) || !statuses.includes(value.status) || !nullableText(value.reason)
        || !nullableDate(value.as_of) || !timestamp(value.fetched_at) || !nullableDate(value.window_start) || !nullableDate(value.window_end)
        || value.sessions_required !== 20 || !number(value.sessions_used) || !Number.isInteger(value.sessions_used) || value.sessions_used > 20
        || !nullableNumber(value.reference_price) || value.reference_price === 0 || !nullableNumber(value.total_volume) || !nullableNumber(value.total_traded_value)
        || !nullableZone(value.poc) || !nullableZone(value.support) || !nullableZone(value.resistance) || !nullableZone(value.current_zone)
        || !Array.isArray(value.bins) || value.bins.length > 24 || !value.bins.every(zone)
        || value.method !== 'daily_uniform_range_overlap_v1' || !nullableText(value.source) || !nullableText(value.calendar_source)
        || !nullableText(value.price_basis) || !nullableText(value.fingerprint)
        || !Array.isArray(value.limitations) || value.limitations.length > 30 || !value.limitations.every(text)) return false;
    if (value.window_start && value.window_end && String(value.window_start) > String(value.window_end)) return false;
    if (new Set(value.bins.map(bin => bin.index)).size !== value.bins.length) return false;
    for (const key of ['poc', 'support', 'resistance', 'current_zone'] as const) {
        const level = value[key];
        if (level !== null && (!zone(level) || !value.bins.some(bin => Object.keys(level).every(field => bin[field as keyof TechnicalZone] === level[field as keyof TechnicalZone])))) return false;
    }
    if (value.status === 'ready' || value.status === 'stale') {
        return value.sessions_used === 20 && number(value.reference_price) && number(value.total_volume) && number(value.total_traded_value)
            && date(value.as_of) && date(value.window_start) && date(value.window_end) && [1, 24].includes(value.bins.length);
    }
    return value.bins.length === 0 && value.poc === null && value.support === null && value.resistance === null && value.current_zone === null;
}
export function validateTechnicalProfiles(value: unknown): TechnicalProfileView {
    if (!object(value) || value.schema_version !== 1 || value.agent !== 'volume_profile_20d_v1' || !text(value.status)
        || !timestamp(value.last_run_at) || !Array.isArray(value.items) || value.items.length > 500 || !value.items.every(isTechnicalProfile)
        || new Set(value.items.map(row => row.symbol)).size !== value.items.length) throw new Error('Invalid technical profile response');
    return value as unknown as TechnicalProfileView;
}
export async function fetchTechnicalProfiles(symbol?: string): Promise<TechnicalProfileView> {
    if (symbol !== undefined && !isTechnicalSymbol(symbol)) throw new Error('Invalid technical profile symbol');
    return validateTechnicalProfiles(await fetchAPI<unknown>(`${endpoint}${symbol ? `?symbol=${symbol}` : ''}`, 10000));
}
export async function queueTechnicalProfile(symbol: string): Promise<TechnicalQueueReceipt> {
    if (!isTechnicalSymbol(symbol)) throw new Error('Invalid technical profile symbol');
    const value = await postAPI<unknown>(endpoint, { symbol }, 10000);
    if (!object(value) || value.schema_version !== 1 || !['queued', 'cached'].includes(String(value.status)) || value.symbol !== symbol) {
        throw new Error('Invalid technical profile queue receipt');
    }
    return value as unknown as TechnicalQueueReceipt;
}
