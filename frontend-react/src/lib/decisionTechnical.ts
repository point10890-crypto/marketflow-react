import { fetchAuthAPI, postAuthAPI } from './api';
import { isTechnicalProfile, isTechnicalSymbol, type TechnicalProfile, type TechnicalStatus } from './kongmingTechnical';

export interface DecisionTechnicalAnalysis {
    schema_version: 1;
    agent: 'volume_profile_20d_v1';
    symbol: string;
    market: 'KR' | 'unsupported';
    status: TechnicalStatus | 'not_requested' | 'unsupported_market';
    profile: TechnicalProfile | null;
    summary: string;
    observations: string[];
    independent_evidence: false;
    queue_status?: 'queued' | 'cached';
}

const statuses = ['ready', 'pending', 'stale', 'insufficient_history', 'price_event_review', 'source_unavailable', 'not_requested', 'unsupported_market'];
const boundedText = (value: unknown): value is string => typeof value === 'string' && value.length <= 4000
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u202a-\u202e\u2066-\u2069]/.test(value);

export interface TechnicalProfileUsed {
    fingerprint: string; as_of: string; fetched_at: string; context_text: string;
}
const validDate = (value: unknown): value is string => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)
    && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

/** Only the immutable metadata attached to this deep result can attest to its input. */
export function readTechnicalProfileUsed(value: unknown): TechnicalProfileUsed | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    const row = value as Record<string, unknown>;
    if (typeof row.fingerprint !== 'string' || !/^[0-9a-f]{64}$/.test(row.fingerprint)
        || !validDate(row.as_of) || typeof row.fetched_at !== 'string'
        || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(row.fetched_at)
        || !validDate(row.fetched_at.slice(0, 10)) || !Number.isFinite(Date.parse(row.fetched_at))
        || !boundedText(row.context_text) || !row.context_text.trim()) return null;
    return value as TechnicalProfileUsed;
}

/** The selected brief is authoritative; never display a profile for another symbol. */
export function validateDecisionTechnical(value: unknown, symbol: string): DecisionTechnicalAnalysis {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid decision technical response');
    const row = value as Record<string, unknown>;
    if (row.schema_version !== 1 || row.agent !== 'volume_profile_20d_v1' || row.symbol !== symbol
        || !statuses.includes(String(row.status)) || !['KR', 'unsupported'].includes(String(row.market))
        || row.independent_evidence !== false || !boundedText(row.summary)
        || !Array.isArray(row.observations) || row.observations.length > 30 || !row.observations.every(boundedText)
        || (row.queue_status !== undefined && !['queued', 'cached'].includes(String(row.queue_status)))) {
        throw new Error('Invalid decision technical response');
    }
    if (row.market === 'unsupported') {
        if (row.status !== 'unsupported_market' || row.profile !== null) throw new Error('Invalid unsupported technical response');
    } else if (!isTechnicalSymbol(symbol) || row.status === 'unsupported_market') {
        throw new Error('Invalid decision technical market');
    }
    if (row.profile !== null && (!isTechnicalProfile(row.profile) || row.profile.symbol !== symbol || row.profile.status !== row.status)) {
        throw new Error('Mismatched decision technical profile');
    }
    if (['ready', 'stale'].includes(String(row.status)) && row.profile === null) throw new Error('Missing decision technical profile');
    return value as DecisionTechnicalAnalysis;
}

export function needsTechnicalRefresh(status: DecisionTechnicalAnalysis['status'] | undefined): boolean {
    return ['not_requested', 'pending', 'stale', 'source_unavailable'].includes(status ?? '');
}

function endpoint(symbol: string, token: string): string {
    if (!token || !isTechnicalSymbol(symbol)) throw new Error('Invalid decision technical request');
    return `/api/kr/decision/${encodeURIComponent(symbol)}/technical-profile`;
}
export async function fetchDecisionTechnical(symbol: string, token: string, signal?: AbortSignal): Promise<DecisionTechnicalAnalysis> {
    return validateDecisionTechnical(await fetchAuthAPI<unknown>(endpoint(symbol, token), token, 15000, signal), symbol);
}
export async function queueDecisionTechnical(symbol: string, token: string): Promise<DecisionTechnicalAnalysis> {
    const next = validateDecisionTechnical(await postAuthAPI<unknown>(endpoint(symbol, token), {}, token, 15000), symbol);
    if (!next.queue_status) throw new Error('Missing decision technical queue receipt');
    return next;
}
