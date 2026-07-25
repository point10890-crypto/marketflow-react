import { describe, expect, it } from 'vitest';

import {
    FRESHNESS_STALE_MS,
    FRESHNESS_WARN_MS,
    getRunFreshness,
    parseRunTimestamp,
} from '@/lib/dataFreshness';

const NOW = new Date(2026, 6, 25, 21, 30, 0); // 2026-07-25 21:30:00 local

function minutesAgo(minutes: number): string {
    const date = new Date(NOW.getTime() - minutes * 60_000);
    const pad = (value: number) => String(value).padStart(2, '0');
    return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
        `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
    );
}

describe('parseRunTimestamp', () => {
    it('reads the backend "YYYY-MM-DD HH:MM:SS" format as local time', () => {
        const parsed = parseRunTimestamp('2026-07-25 21:20:10');
        expect(parsed).not.toBeNull();
        expect(parsed!.getFullYear()).toBe(2026);
        expect(parsed!.getMonth()).toBe(6);
        expect(parsed!.getDate()).toBe(25);
        expect(parsed!.getHours()).toBe(21);
        expect(parsed!.getMinutes()).toBe(20);
    });

    it('returns null for missing or unparseable values', () => {
        expect(parseRunTimestamp(undefined)).toBeNull();
        expect(parseRunTimestamp('')).toBeNull();
        expect(parseRunTimestamp('nonsense')).toBeNull();
    });
});

describe('getRunFreshness', () => {
    it('is fresh for a run updated moments ago', () => {
        const freshness = getRunFreshness(minutesAgo(0), NOW);
        expect(freshness.level).toBe('fresh');
        expect(freshness.label).toBe('방금 갱신');
    });

    it('stays fresh through a normal cycle gap and block cool-off (25min)', () => {
        const freshness = getRunFreshness(minutesAgo(25), NOW);
        expect(freshness.level).toBe('fresh');
        expect(freshness.label).toBe('25분 전');
    });

    it('warns once the warn threshold is reached', () => {
        expect(getRunFreshness(minutesAgo(59), NOW).level).toBe('fresh');
        expect(getRunFreshness(minutesAgo(FRESHNESS_WARN_MS / 60_000), NOW).level).toBe('warn');
        expect(getRunFreshness(minutesAgo(90), NOW).label).toBe('1시간 전');
    });

    it('escalates to stale at the stale threshold', () => {
        expect(getRunFreshness(minutesAgo(FRESHNESS_STALE_MS / 60_000 - 1), NOW).level).toBe('warn');
        expect(getRunFreshness(minutesAgo(FRESHNESS_STALE_MS / 60_000), NOW).level).toBe('stale');
    });

    it('flags the 2026-07-15 style 10-day freeze', () => {
        const freshness = getRunFreshness('2026-07-15 16:10:36', NOW);
        expect(freshness.level).toBe('stale');
        expect(freshness.label).toBe('10일 전');
    });

    it('reports unknown when there is no usable timestamp', () => {
        const freshness = getRunFreshness(undefined, NOW);
        expect(freshness.level).toBe('unknown');
        expect(freshness.ageMs).toBeNull();
    });

    it('treats a future timestamp as fresh instead of negative age', () => {
        const freshness = getRunFreshness(minutesAgo(-30), NOW);
        expect(freshness.level).toBe('fresh');
        expect(freshness.ageMs).toBe(0);
    });
});
