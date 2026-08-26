/**
 * Claw LIVE — 타입·표시 규칙 공용 모듈.
 * 백엔드 계약: GET /api/kr/claw/overview (marketflow_claw/overview.py). 읽기전용.
 */
import { createElement, type ReactNode } from 'react';

export type ClawLoopState = 'running' | 'idle' | 'halt' | 'dead';

export interface ClawLeaderRow {
    code: string;
    name: string;
    grade: 'S' | 'A' | 'B' | string;
    score: number;
    chg: number;
    trval_eok: number;
    since_ts: string | null;
    today_event: { type: string; ts: string } | null;
}

export interface ClawEvent {
    ts: string;
    type: string;
    code: string;
    name: string;
    grade_from: string | null;
    grade_to: string | null;
    score: number | null;
    chg: number | null;
    reported_at: string | null;
}

export interface ClawBrief {
    ts: string;
    kind: string;
    digest: string;
    delivered: boolean;
    error: string | null;
    text: string;
}

export interface ClawOverview {
    generated_at: string;
    errors: Record<string, string>;
    loop: {
        state: ClawLoopState;
        market_open: boolean;
        heartbeat_age_s: number | null;
        heartbeat_state: string | null;
        last_tick_ts: string | null;
        source: string | null;
        source_age_s: number | null;
    };
    regime: {
        regime: string;
        gate_status: string | null;
        gate_score: number | null;
        gate_age_hours: number | null;
        breadth_pct: number | null;
        leader_count: number | null;
        halt: boolean;
        reasons: string[];
    };
    leaders: {
        snapshot_ts: string | null;
        market_status: string | null;
        source: string | null;
        by_grade: Record<string, number>;
        error: string | null;
        rows: ClawLeaderRow[];
    };
    events: { day: string; counts: Record<string, number>; items: ClawEvent[] };
    briefs: { items: ClawBrief[] };
    system: {
        snapshots_today: number;
        events_today: number;
        briefs_today: number;
        briefs_delivered_today: number;
        kis_calls_today: number;
        db_bytes: number;
        drop_confirm_ticks: number;
        delivery: { enabled: boolean; mode: string; token_key: string; configured: boolean };
        kill_switches: Record<string, boolean>;
    };
}

export const CLAW_OVERVIEW_ENDPOINT = '/api/kr/claw/overview';
export const CLAW_CLOSE_LEADERS_ENDPOINT = '/api/kr/claw/close-leaders';

/** 마감 기준 주도주 — GET /api/kr/claw/close-leaders (마스터 플랜 P3) */
export interface ClawCloseLeaderRow {
    code: string;
    name: string;
    grade: 'S' | 'A' | 'B' | string;
    score: number | null;
    chg: number | null;
    trval_eok: number | null;
    price: number | null;
    events: Array<{ ts: string; type: string; grade_from: string | null; grade_to: string | null }>;
}

export interface ClawCloseLeaders {
    day: string | null;
    snapshot_ts: string | null;
    market_status: string | null;
    by_grade: Record<string, number>;
    rows: ClawCloseLeaderRow[];
    events_count: number;
    close_brief: { ts: string; delivered: boolean } | null;
    error: string | null;
}

export function isClawCloseLeaders(v: unknown): v is ClawCloseLeaders {
    const o = v as Partial<ClawCloseLeaders> | null;
    return !!o && typeof o === 'object' && Array.isArray(o.rows) && 'snapshot_ts' in o;
}

/** '20260826' → '2026-08-26' */
export function fmtDay(day: string | null | undefined): string {
    if (!day || day.length !== 8) return '-';
    return `${day.slice(0, 4)}-${day.slice(4, 6)}-${day.slice(6)}`;
}

export const CLAW_SCORECARDS_ENDPOINT = '/api/kr/claw/scorecards';
export const CLAW_QUALITY_ENDPOINT = '/api/kr/claw/quality';

export type ClawOutcomeStatus = 'pending' | 'complete' | 'missing' | 'not_comparable' | string;

export interface ClawScorecards {
    schema_version: string;
    generated_at: string;
    data_as_of: string | null;
    window: { start: string | null; end: string | null };
    coverage: {
        instances: number;
        eligible_n: number;
        complete_n: number;
        pending_n: number;
        missing_n: number;
        ratio: number | null;
    };
    horizons: Array<{
        horizon_sessions: number;
        eligible_n: number;
        complete_n: number;
        pending_n: number;
        missing_n: number;
        coverage: number | null;
        avg_return_pct: number | null;
        positive_rate_pct: number | null;
        status: string;
        insufficient_reason: string | null;
    }>;
    recent_instances: Array<{
        id: number | string;
        opened_at: string;
        code: string;
        name: string;
        trigger_type: string;
        grade: string | null;
        score: number | null;
        status: string;
        structural_phase: string | null;
        live_gate_status: string | null;
        live_halt: boolean;
        outcomes: Array<{
            horizon_sessions: number;
            status: ClawOutcomeStatus;
            target_session_date: string | null;
            return_pct: number | null;
            error_code: string | null;
        }>;
    }>;
    stale: boolean;
    insufficient: boolean;
    insufficient_reason: string | null;
    errors: string[];
}

export interface ClawQuality {
    schema_version: string;
    generated_at: string;
    status: 'ok' | 'degraded' | 'unavailable' | string;
    database: { path_exists: boolean; bytes: number; foreign_keys: boolean; schema_version: number };
    ledger: {
        last_write_at: string | null;
        last_error_at: string | null;
        last_error: string | null;
        consecutive_errors: number;
        scans: number;
        contexts: number;
        instances: number;
        state_events: number;
    };
    outcomes: { pending: number; complete: number; missing: number; data_as_of: string | null };
    freshness: { last_scan_at: string | null; age_seconds: number | null; stale: boolean };
    errors: string[];
}

/** 응답이 계약 형태인지 — 테스트 모킹이나 구버전 백엔드에서 엉뚱한 객체가 와도 카드가 죽지 않게 */
export function isClawOverview(v: unknown): v is ClawOverview {
    const o = v as Partial<ClawOverview> | null;
    return !!o && typeof o === 'object' && !!o.loop && typeof o.loop.state === 'string' && !!o.leaders && Array.isArray(o.leaders.rows);
}

export function isClawScorecards(v: unknown): v is ClawScorecards {
    const o = v as Partial<ClawScorecards> | null;
    return !!o && typeof o === 'object' && !!o.coverage && Array.isArray(o.horizons) && Array.isArray(o.recent_instances);
}

export function isClawQuality(v: unknown): v is ClawQuality {
    const o = v as Partial<ClawQuality> | null;
    return !!o && typeof o === 'object' && typeof o.status === 'string' && !!o.database && !!o.ledger && !!o.outcomes;
}

/** 주도주LIVE 페이지의 GRADE_STYLE 과 동일한 색 (S rose · A amber · B blue) */
export const GRADE_CHIP: Record<string, string> = {
    S: 'border-rose-500/30 bg-rose-500/10 text-rose-400',
    A: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
    B: 'border-blue-500/30 bg-blue-500/10 text-blue-400',
};
export const GRADE_BAR: Record<string, string> = { S: 'bg-rose-400', A: 'bg-amber-400', B: 'bg-blue-400' };

/** 이벤트 칩: 글자+연한 배경(테두리 없음) — 등급 칩(테두리형)과 구분 */
export const EVENT_CHIP: Record<string, { label: string; cls: string }> = {
    LEADER_NEW: { label: 'NEW', cls: 'bg-teal-500/15 text-teal-300' },
    LEADER_UPGRADE: { label: 'UP', cls: 'bg-emerald-500/15 text-emerald-300' },
    LEADER_DROP: { label: 'DROP', cls: 'bg-blue-500/15 text-blue-300' },
    VOLUME_SURGE: { label: 'VOL', cls: 'bg-violet-500/15 text-violet-300' },
    NEW_HIGH_BREAK: { label: 'HIGH', cls: 'bg-orange-500/15 text-orange-300' },
    HALT_ENTER: { label: 'HALT', cls: 'bg-amber-500/15 text-amber-300' },
    HALT_EXIT: { label: 'HALT', cls: 'bg-amber-500/15 text-amber-300' },
};
export function eventChip(type: string): { label: string; cls: string } {
    return EVENT_CHIP[type] ?? { label: type, cls: 'bg-white/10 text-gray-300' };
}

export const REGIME_LABEL: Record<string, { label: string; cls: string }> = {
    RISK_ON: { label: 'RISK ON', cls: 'text-emerald-300' },
    NEUTRAL: { label: 'NEUTRAL', cls: 'text-white' },
    RISK_OFF: { label: 'RISK OFF', cls: 'text-blue-300' },
    UNKNOWN: { label: 'UNKNOWN', cls: 'text-gray-500' },
};

export const LOOP_LABEL: Record<ClawLoopState, { label: string; dot: string; sub: string }> = {
    running: { label: '장중', dot: 'bg-teal-400', sub: '5s 틱' },
    idle: { label: '장외', dot: 'bg-gray-600', sub: '다음 09:00' },
    halt: { label: '검출 보류', dot: 'bg-amber-400', sub: 'HALT' },
    dead: { label: '루프 응답 없음', dot: 'bg-red-500', sub: '워치독 대기' },
};

export const BRIEF_KIND_LABEL: Record<string, string> = { morning: '조간', midday: '정오', close: '마감', event: '이벤트', halt: '보류' };

/** KRX 관례: 상승 빨강 · 하락 파랑 */
export function chgClass(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return 'text-gray-500';
    return v >= 0 ? 'text-red-400' : 'text-blue-400';
}
export function fmtPct(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '-';
    return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`;
}
export function fmtEok(v: number | null | undefined): string {
    if (v == null || !Number.isFinite(v)) return '-';
    return `${Math.round(v).toLocaleString('ko-KR')}억`;
}
export function hhmm(ts: string | null | undefined): string {
    return ts ? ts.slice(11, 16) : '-';
}
export function fmtAge(s: number | null | undefined): string {
    if (s == null || !Number.isFinite(s)) return '-';
    if (s < 90) return `${Math.round(s)}s`;
    if (s < 5400) return `${Math.round(s / 60)}m`;
    return `${(s / 3600).toFixed(1)}h`;
}
/** "유지 시간" — since_ts 부터 기준 시각까지. 장외에는 표시하지 않는다(호출측 판단) */
export function fmtHeld(sinceTs: string | null, nowTs: string | null): string | null {
    if (!sinceTs || !nowTs) return null;
    const ms = Date.parse(nowTs) - Date.parse(sinceTs);
    if (!Number.isFinite(ms) || ms < 0) return null;
    const m = Math.round(ms / 60000);
    return m >= 60 ? `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}m` : `${Math.max(1, m)}m`;
}

/**
 * 텔레그램 HTML(<b> 만 사용) → React 노드. dangerouslySetInnerHTML 을 쓰지 않는다:
 * 텍스트는 React 가 이스케이프하고 <b> 토큰만 굵게 바꾼다 (BriefingPortal XSS 규칙).
 */
export function renderTelegramText(text: string): ReactNode[] {
    const parts = text.split(/(<\/?b>)/i);
    const out: ReactNode[] = [];
    let bold = false;
    parts.forEach((p, i) => {
        if (/^<b>$/i.test(p)) { bold = true; return; }
        if (/^<\/b>$/i.test(p)) { bold = false; return; }
        if (!p) return;
        out.push(bold ? createElement('b', { key: i, className: 'font-bold text-white' }, p) : createElement('span', { key: i }, p));
    });
    return out;
}
