/**
 * 전역 브랜드 바가 쓰는 가벼운 Claw 상태 구독.
 * 모듈 단위 캐시 + 60초 폴링 하나를 모든 구독자가 공유한다 (페이지마다 요청하지 않음).
 * 실패/계약 불일치면 null — 브랜드 바는 REST 상태로 조용히 표시된다.
 */
import { useEffect, useState } from 'react';
import { fetchAuthAPI } from '@/lib/api';
import { CLAW_OVERVIEW_ENDPOINT, ClawOverview, isClawOverview } from '@/lib/claw';

const INTERVAL_MS = 60000;
let cache: ClawOverview | null = null;
let fetchedAt = 0;
let timer: ReturnType<typeof setInterval> | null = null;
const subs = new Set<(v: ClawOverview | null) => void>();
let currentToken: string | undefined;

async function refresh(): Promise<void> {
    try {
        const res = await fetchAuthAPI<unknown>(CLAW_OVERVIEW_ENDPOINT, currentToken);
        cache = isClawOverview(res) ? res : null;
    } catch {
        cache = null;
    }
    fetchedAt = Date.now();
    subs.forEach(fn => fn(cache));
}

function ensurePolling(): void {
    if (timer) return;
    timer = setInterval(() => { if (document.visibilityState === 'visible' && subs.size) void refresh(); }, INTERVAL_MS);
}

export function useClawState(token?: string | null): ClawOverview | null {
    const [state, setState] = useState<ClawOverview | null>(cache);
    useEffect(() => {
        currentToken = token ?? undefined;
        subs.add(setState);
        ensurePolling();
        if (Date.now() - fetchedAt > INTERVAL_MS / 2) void refresh(); else setState(cache);
        return () => { subs.delete(setState); };
    }, [token]);
    return state;
}

/** 테스트/수동 갱신용 */
export function _resetClawStateCache(): void {
    cache = null; fetchedAt = 0; if (timer) { clearInterval(timer); timer = null; }
}
