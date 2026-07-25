/**
 * Data-freshness helpers for the manual-stock-analysis dashboard.
 *
 * The scraper loop froze on 2026-07-15 and nobody noticed for 10 days: the page
 * happily rendered the last run with no hint that it had stopped advancing. The
 * only trustworthy liveness signal is when a run last produced data, so these
 * helpers grade that timestamp rather than any in-memory "running" flag.
 */

export type FreshnessLevel = 'unknown' | 'fresh' | 'warn' | 'stale';

/**
 * A quiet gap is normal: cycles wait up to ~15min between runs and a Cloudflare
 * block cool-off adds up to ~25min. 1h is comfortably past both.
 */
export const FRESHNESS_WARN_MS = 60 * 60 * 1000;
/** Nothing healthy stays silent for 6h -- at ~18s/row a cycle writes constantly. */
export const FRESHNESS_STALE_MS = 6 * 60 * 60 * 1000;

export interface Freshness {
    level: FreshnessLevel;
    /** Milliseconds since the last update; null when there is no usable timestamp. */
    ageMs: number | null;
    /** Korean relative label, e.g. "방금 갱신", "25분 전", "10일 전". */
    label: string;
}

const BACKEND_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/;

/**
 * Parse the backend's `"YYYY-MM-DD HH:MM:SS"` timestamps as *local* time.
 *
 * `new Date(...)` on that shape is implementation-defined, and the server writes
 * wall-clock KST with no offset, so the components are applied explicitly.
 */
export function parseRunTimestamp(value?: string | null): Date | null {
    const text = (value || '').trim();
    if (!text) return null;

    const match = BACKEND_TIMESTAMP.exec(text);
    if (match) {
        const [, year, month, day, hour, minute, second] = match;
        return new Date(
            Number(year),
            Number(month) - 1,
            Number(day),
            Number(hour),
            Number(minute),
            Number(second || '0'),
        );
    }

    const parsed = new Date(text);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function relativeLabel(ageMs: number): string {
    const minutes = Math.floor(ageMs / 60_000);
    if (minutes < 1) return '방금 갱신';
    if (minutes < 60) return `${minutes}분 전`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}시간 전`;

    return `${Math.floor(hours / 24)}일 전`;
}

/** Grade how long ago a run last wrote data. */
export function getRunFreshness(value?: string | null, now: Date = new Date()): Freshness {
    const updatedAt = parseRunTimestamp(value);
    if (!updatedAt) {
        return { level: 'unknown', ageMs: null, label: '갱신 기록 없음' };
    }

    // Clock skew between the browser and the MiniPC must not read as "negative age".
    const ageMs = Math.max(0, now.getTime() - updatedAt.getTime());
    const level: FreshnessLevel =
        ageMs >= FRESHNESS_STALE_MS ? 'stale' : ageMs >= FRESHNESS_WARN_MS ? 'warn' : 'fresh';

    return { level, ageMs, label: relativeLabel(ageMs) };
}
