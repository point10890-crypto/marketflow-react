'use client';

import { useEffect, useRef, useCallback } from 'react';

/**
 * 자동 데이터 갱신 훅 (Page Visibility API 기반)
 * - 탭이 보이는 상태에서만 polling
 * - 백그라운드에서 포그라운드로 돌아오면 즉시 1회 fetch
 * - 모바일(ngrok) 포함 전 플랫폼 지원
 */
export function useAutoRefresh(
    fetchFn: () => void | Promise<void>,
    intervalMs: number = 30000,
    enabled: boolean = true
) {
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
    const fetchRef = useRef(fetchFn);

    // 항상 최신 fetchFn 참조 유지
    useEffect(() => {
        fetchRef.current = fetchFn;
    }, [fetchFn]);

    const startPolling = useCallback(() => {
        if (intervalRef.current) return;
        intervalRef.current = setInterval(() => {
            fetchRef.current();
        }, intervalMs);
    }, [intervalMs]);

    const stopPolling = useCallback(() => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
    }, []);

    useEffect(() => {
        if (!enabled) {
            stopPolling();
            return;
        }

        // 페이지 가시성 변경 핸들러
        const handleVisibility = () => {
            if (document.visibilityState === 'visible') {
                // 포그라운드 복귀 → 즉시 1회 fetch + polling 재개
                fetchRef.current();
                startPolling();
            } else {
                // 백그라운드 → polling 중단
                stopPolling();
            }
        };

        // 초기 polling 시작
        startPolling();
        document.addEventListener('visibilitychange', handleVisibility);

        return () => {
            stopPolling();
            document.removeEventListener('visibilitychange', handleVisibility);
        };
    }, [enabled, startPolling, stopPolling]);
}


/**
 * data-version 기반 스마트 갱신 훅
 * - /api/data-version 엔드포인트를 경량 polling (15초)
 * - 파일 수정 시간이 변경된 경우에만 실제 데이터 refetch
 * - 로컬 + 모바일(ngrok) 동시 실시간 갱신 보장
 * - 불필요한 네트워크 트래픽 최소화
 *
 * @param fetchFn     데이터 변경 감지 시 호출할 함수
 * @param watchFiles  감시할 파일 목록 (기본: jongga_v2_latest.json)
 * @param pollMs      버전 체크 주기 (기본: 15초)
 * @param enabled     활성화 여부
 */
export function useSmartRefresh(
    fetchFn: () => void | Promise<void>,
    watchFiles: string[] = ['jongga_v2_latest.json'],
    pollMs: number = 15000,
    enabled: boolean = true
) {
    const fetchRef = useRef(fetchFn);
    const versionsRef = useRef<Record<string, number>>({});
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    useEffect(() => {
        fetchRef.current = fetchFn;
    }, [fetchFn]);

    const checkVersion = useCallback(async () => {
        try {
            const res = await fetch('/api/data-version');
            if (!res.ok) return;
            const data = await res.json();
            const newVersions: Record<string, number> = data.versions || {};

            // 감시 대상 파일 중 변경된 것이 있는지 체크
            let changed = false;
            for (const file of watchFiles) {
                const oldMtime = versionsRef.current[file] || 0;
                const newMtime = newVersions[file] || 0;
                if (oldMtime > 0 && newMtime > oldMtime) {
                    changed = true;
                }
            }

            // 버전 저장 (첫 호출 시에는 changed=false)
            versionsRef.current = newVersions;

            // 변경 감지 → 실제 데이터 refetch
            if (changed) {
                fetchRef.current();
            }
        } catch {
            // 네트워크 오류 무시 (다음 polling에서 재시도)
        }
    }, [watchFiles]);

    const startPolling = useCallback(() => {
        if (intervalRef.current) return;
        // 즉시 1회 버전 체크 (초기 버전 스냅샷)
        checkVersion();
        intervalRef.current = setInterval(checkVersion, pollMs);
    }, [checkVersion, pollMs]);

    const stopPolling = useCallback(() => {
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }
    }, []);

    useEffect(() => {
        if (!enabled) {
            stopPolling();
            return;
        }

        const handleVisibility = () => {
            if (document.visibilityState === 'visible') {
                // 포그라운드 복귀 → 즉시 버전 체크 + polling 재개
                checkVersion();
                startPolling();
            } else {
                stopPolling();
            }
        };

        startPolling();
        document.addEventListener('visibilitychange', handleVisibility);

        return () => {
            stopPolling();
            document.removeEventListener('visibilitychange', handleVisibility);
        };
    }, [enabled, checkVersion, startPolling, stopPolling]);
}
