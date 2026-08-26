import { fetchAuthAPI } from '@/lib/api';

export const ALPHA_CORE_ENDPOINTS = {
    status: '/api/kr/alpha-core/status',
    portfolio: '/api/kr/alpha-core/portfolio',
    riskDecisions: '/api/kr/alpha-core/risk-decisions',
    hypotheses: '/api/kr/alpha-core/hypotheses',
    ledger: '/api/kr/alpha-core/ledger',
} as const;

export type AlphaCoreMode = 'SHADOW' | 'PAPER' | string;

export interface AlphaCoreStatus {
    schema_version?: string;
    ok?: boolean;
    mode?: AlphaCoreMode;
    generated_at?: string | null;
    database?: Record<string, unknown> | string | null;
    counts?: Record<string, unknown> | null;
    risk_state?: Record<string, unknown> | string | null;
    quality?: Record<string, unknown> | string | null;
    [key: string]: unknown;
}

export interface AlphaCorePortfolio {
    schema_version?: string;
    generated_at?: string | null;
    as_of?: string | null;
    portfolio?: Record<string, unknown> | null;
    cash?: number | null;
    cash_krw?: number | null;
    reserved_cash_krw?: number | null;
    nav?: number | null;
    nav_krw?: number | null;
    gross_exposure?: number | null;
    gross_exposure_krw?: number | null;
    net_exposure?: number | null;
    net_exposure_krw?: number | null;
    drawdown?: number | null;
    drawdown_pct?: number | null;
    positions?: unknown[];
    units?: Record<string, string> | null;
    [key: string]: unknown;
}

export interface AlphaCoreRiskDecision {
    id?: string | number | null;
    intent_id?: string | number | null;
    decision?: string | null;
    state?: string | null;
    reasons?: unknown;
    reject_reasons?: unknown;
    reason_codes?: unknown;
    created_at?: string | null;
    decided_at?: string | null;
    [key: string]: unknown;
}

export interface AlphaCoreRiskDecisions {
    schema_version?: string;
    generated_at?: string | null;
    items?: AlphaCoreRiskDecision[];
    decisions?: AlphaCoreRiskDecision[];
    [key: string]: unknown;
}

export interface AlphaCoreHypothesis {
    id?: string | number | null;
    hypothesis_id?: string | number | null;
    title?: string | null;
    name?: string | null;
    thesis?: string | null;
    status?: string | null;
    evidence_count?: number | null;
    updated_at?: string | null;
    created_at?: string | null;
    [key: string]: unknown;
}

export interface AlphaCoreHypotheses {
    schema_version?: string;
    generated_at?: string | null;
    items?: AlphaCoreHypothesis[];
    hypotheses?: AlphaCoreHypothesis[];
    [key: string]: unknown;
}

export interface AlphaCoreLedger {
    schema_version?: string;
    generated_at?: string | null;
    summary?: Record<string, unknown> | null;
    counts?: Record<string, unknown> | null;
    pending?: number | null;
    pending_count?: number | null;
    reconcile_required?: number | boolean | null;
    reconciliation?: Record<string, unknown> | null;
    items?: unknown[];
    [key: string]: unknown;
}

export interface AlphaCoreSnapshot {
    status: AlphaCoreStatus | null;
    portfolio: AlphaCorePortfolio | null;
    riskDecisions: AlphaCoreRiskDecisions | null;
    hypotheses: AlphaCoreHypotheses | null;
    ledger: AlphaCoreLedger | null;
    unavailable: Array<keyof typeof ALPHA_CORE_ENDPOINTS>;
}

type AlphaCoreKey = keyof typeof ALPHA_CORE_ENDPOINTS;

function isRecord(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function asSection<T extends Record<string, unknown>>(value: unknown): T | null {
    if (!isRecord(value)) return null;
    // Accept a future envelope without coupling the UI to it.
    if (isRecord(value.data)) return value.data as T;
    return value as T;
}

/**
 * Read-only aggregate for the Alpha Core operations card. One failed endpoint
 * never hides the other four; the UI can expose partial/stale state explicitly.
 */
export async function fetchAlphaCoreSnapshot(apiToken?: string): Promise<AlphaCoreSnapshot> {
    const keys = Object.keys(ALPHA_CORE_ENDPOINTS) as AlphaCoreKey[];
    const settled = await Promise.allSettled(
        keys.map(key => fetchAuthAPI<unknown>(ALPHA_CORE_ENDPOINTS[key], apiToken)),
    );

    const sections: Partial<Record<AlphaCoreKey, Record<string, unknown> | null>> = {};
    const unavailable: AlphaCoreKey[] = [];
    settled.forEach((result, index) => {
        const key = keys[index];
        if (result.status === 'fulfilled') {
            const section = asSection<Record<string, unknown>>(result.value);
            sections[key] = section;
            if (!section) unavailable.push(key);
        } else {
            sections[key] = null;
            unavailable.push(key);
        }
    });

    return {
        status: sections.status as AlphaCoreStatus | null,
        portfolio: sections.portfolio as AlphaCorePortfolio | null,
        riskDecisions: sections.riskDecisions as AlphaCoreRiskDecisions | null,
        hypotheses: sections.hypotheses as AlphaCoreHypotheses | null,
        ledger: sections.ledger as AlphaCoreLedger | null,
        unavailable,
    };
}
