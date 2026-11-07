import { fetchAuthAPI } from './api';

/** 운영 관제 센터 — GET /api/admin/control-center/* (관리자 전용, 읽기 전용). */

export type CcStatus = 'ok' | 'skipped' | 'unknown' | 'warn' | 'fail';
export type CcSeverity = 'critical' | 'standard' | 'info';
export type CcTier = 'fast' | 'standard' | 'deep';
interface CcMonitorState { status: CcStatus; detail: string; age_seconds?: number }

export interface CcCheck {
    check_id: string;
    family: string;
    target: string;
    severity: CcSeverity;
    status: CcStatus;
    detail: string;
    latency_ms: number | null;
    last_change_at: string | null;
    last_observed_at: string | null;
}

export interface CcPagePart { kind: 'endpoint' | 'data'; target: string; status: CcStatus; detail: string }
export interface CcPage { path: string; label: string; critical: boolean; status: CcStatus; parts: CcPagePart[] }

export interface CcIncident {
    id: number;
    check_id: string;
    family: string;
    target: string;
    severity: CcSeverity;
    opened_at: string;
    resolved_at: string | null;
    last_detail: string | null;
    occurrences: number;
    flapping: number;
}

export interface CcSnapshot {
    schema: string;
    generated_at?: string;
    overall: CcStatus;
    monitor: CcMonitorState & { tiers?: Record<CcTier, CcMonitorState> };
    families: Record<string, { status: CcStatus; counts: Record<string, number> }>;
    pages: CcPage[];
    failing: CcCheck[];
    warning: CcCheck[];
    open_incidents: CcIncident[];
    gate_coverage?: { observed: number; candidates: number; skipped: number } | null;
    counts: { checks?: number; fail?: number; warn?: number; unknown?: number; skipped?: number; critical_fail?: number; open_incidents?: number };
    last_runs?: Record<string, { started_at: string | null; finished_at: string | null; overall: string | null }>;
}

export interface CcHistory {
    check_id: string;
    state: (CcCheck & { tier?: string }) | null;
    history: { status: CcStatus; latency_ms: number | null; detail: string; observed_at: string }[];
}

export interface CcRouteRow {
    rule: string;
    methods: string[];
    auth: string;
    probe_mode: string;
    deep: boolean;
    mutating: boolean;
}

export interface CcRoutes {
    totals: Record<string, number>;
    routes: CcRouteRow[];
}

const STATUSES = new Set(['ok', 'skipped', 'unknown', 'warn', 'fail']);
const isRecord = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const validStatus = (v: unknown) => typeof v === 'string' && STATUSES.has(v);
const validCounts = (v: unknown) => isRecord(v) && Object.values(v).every(n => Number.isInteger(n) && Number(n) >= 0);
const validMonitor = (v: unknown) => isRecord(v) && validStatus(v.status) && typeof v.detail === 'string';
const message = '관제 응답 형식이 올바르지 않습니다. 실행기 버전을 확인해 주세요.';

function validCheck(v: unknown): boolean {
    return isRecord(v) && typeof v.check_id === 'string' && typeof v.family === 'string' && validStatus(v.status)
        && typeof v.detail === 'string';
}

function validIncident(v: unknown): boolean {
    return isRecord(v) && Number.isInteger(v.id) && typeof v.check_id === 'string'
        && (typeof v.last_detail === 'string' || v.last_detail === null) && typeof v.opened_at === 'string'
        && (typeof v.resolved_at === 'string' || v.resolved_at === null) && Number.isInteger(v.occurrences);
}

export function validateSnapshot(v: unknown): CcSnapshot {
    if (!isRecord(v) || v.schema !== 'marketflow.control_center.v1' || !validStatus(v.overall)) throw new Error(message);
    if (!isRecord(v.monitor) || !validMonitor(v.monitor)) throw new Error(message);
    const tiers = v.monitor.tiers;
    if (tiers !== undefined && (!isRecord(tiers) || !['fast', 'standard', 'deep'].every(tier => validMonitor(tiers[tier])))) throw new Error(message);
    if (!Array.isArray(v.failing) || !v.failing.every(validCheck)
        || !Array.isArray(v.warning) || !v.warning.every(validCheck)
        || !Array.isArray(v.open_incidents) || !v.open_incidents.every(validIncident)) throw new Error(message);
    if (!Array.isArray(v.pages) || !v.pages.every(p => isRecord(p) && typeof p.path === 'string' && typeof p.label === 'string'
        && validStatus(p.status) && Array.isArray(p.parts) && p.parts.every(part => isRecord(part)
            && typeof part.target === 'string' && typeof part.detail === 'string' && validStatus(part.status)))) throw new Error(message);
    if (!isRecord(v.families) || !Object.values(v.families).every(f => isRecord(f) && validStatus(f.status) && validCounts(f.counts))
        || !validCounts(v.counts)) throw new Error(message);
    const coverage = v.gate_coverage;
    if (coverage != null && (!isRecord(coverage) || !['observed', 'candidates', 'skipped'].every(k =>
        Number.isInteger(coverage[k]) && Number(coverage[k]) >= 0))) throw new Error(message);
    return v as unknown as CcSnapshot;
}

export async function fetchControlCenterSummary(token?: string, signal?: AbortSignal): Promise<CcSnapshot> {
    return validateSnapshot(await fetchAuthAPI<unknown>('/api/admin/control-center/summary', token, undefined, signal));
}

export async function fetchControlCenterHistory(checkId: string, token?: string, signal?: AbortSignal): Promise<CcHistory> {
    const data = await fetchAuthAPI<CcHistory>(`/api/admin/control-center/checks/${encodeURIComponent(checkId)}/history?hours=24`, token, undefined, signal);
    if (!isRecord(data) || data.check_id !== checkId || !Array.isArray(data.history) || !data.history.every(row => isRecord(row)
        && validStatus(row.status) && typeof row.observed_at === 'string' && typeof row.detail === 'string')) throw new Error(message);
    return data;
}

export async function fetchControlCenterIncidents(state: 'open' | 'recent', token?: string, signal?: AbortSignal): Promise<CcIncident[]> {
    const data = await fetchAuthAPI<{ incidents: CcIncident[] }>(`/api/admin/control-center/incidents?state=${state}&limit=50`, token, undefined, signal);
    if (!isRecord(data) || !Array.isArray(data.incidents) || !data.incidents.every(validIncident)) throw new Error(message);
    return data.incidents;
}

export async function fetchControlCenterRoutes(token?: string, signal?: AbortSignal): Promise<CcRoutes> {
    const data = await fetchAuthAPI<CcRoutes>('/api/admin/control-center/routes', token, undefined, signal);
    if (!isRecord(data) || !validCounts(data.totals) || !Array.isArray(data.routes) || !data.routes.every(row => isRecord(row)
        && typeof row.rule === 'string' && Array.isArray(row.methods) && row.methods.every(m => typeof m === 'string')
        && typeof row.auth === 'string' && typeof row.probe_mode === 'string')) throw new Error(message);
    return data;
}
