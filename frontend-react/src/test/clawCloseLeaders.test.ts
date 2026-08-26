/** 마감 주도주 계약 가드 — 백엔드/모킹 응답 형태 방어 (마스터 플랜 P3) */
import { describe, expect, it } from 'vitest';
import { fmtDay, isClawCloseLeaders } from '@/lib/claw';

describe('isClawCloseLeaders', () => {
    it('계약 형태를 통과시킨다', () => {
        expect(isClawCloseLeaders({
            day: '20260826', snapshot_ts: '2026-08-26T15:29:00', market_status: 'OPEN',
            by_grade: {}, rows: [], events_count: 0, close_brief: null, error: null,
        })).toBe(true);
    });

    it('rows 배열이 없거나 객체가 아니면 거부한다', () => {
        expect(isClawCloseLeaders(null)).toBe(false);
        expect(isClawCloseLeaders({ rows: 'nope', snapshot_ts: null })).toBe(false);
        expect(isClawCloseLeaders({ loop: { state: 'idle' } })).toBe(false);
    });
});

describe('fmtDay', () => {
    it('YYYYMMDD 를 YYYY-MM-DD 로 바꾼다', () => {
        expect(fmtDay('20260826')).toBe('2026-08-26');
        expect(fmtDay(null)).toBe('-');
        expect(fmtDay('2026')).toBe('-');
    });
});
