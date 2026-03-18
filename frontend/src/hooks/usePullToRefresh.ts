'use client';

import { useRef, useState, useEffect, useCallback, type RefObject } from 'react';

interface PullToRefreshResult {
    pullDistance: number;
    isRefreshing: boolean;
}

export function usePullToRefresh(
    scrollRef: RefObject<HTMLDivElement | null>,
    onRefresh: (() => Promise<void>) | null,
    threshold: number = 80
): PullToRefreshResult {
    const [pullDistance, setPullDistance] = useState(0);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const startY = useRef(0);
    const pulling = useRef(false);

    const handleRefresh = useCallback(async () => {
        if (!onRefresh || isRefreshing) return;
        setIsRefreshing(true);
        try {
            await onRefresh();
        } finally {
            setIsRefreshing(false);
            setPullDistance(0);
        }
    }, [onRefresh, isRefreshing]);

    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;

        // Only enable on mobile
        if (window.innerWidth >= 768) return;

        const onTouchStart = (e: TouchEvent) => {
            if (el.scrollTop <= 0 && !isRefreshing) {
                startY.current = e.touches[0].clientY;
                pulling.current = true;
            }
        };

        const onTouchMove = (e: TouchEvent) => {
            if (!pulling.current || isRefreshing) return;
            const deltaY = e.touches[0].clientY - startY.current;
            if (deltaY > 0 && el.scrollTop <= 0) {
                // Dampen the pull distance
                const dampened = Math.min(deltaY * 0.4, threshold * 1.5);
                setPullDistance(dampened);
                if (dampened > 10) {
                    e.preventDefault();
                }
            } else {
                pulling.current = false;
                setPullDistance(0);
            }
        };

        const onTouchEnd = () => {
            if (!pulling.current) return;
            pulling.current = false;
            if (pullDistance >= threshold) {
                handleRefresh();
            } else {
                setPullDistance(0);
            }
        };

        el.addEventListener('touchstart', onTouchStart, { passive: true });
        el.addEventListener('touchmove', onTouchMove, { passive: false });
        el.addEventListener('touchend', onTouchEnd, { passive: true });

        return () => {
            el.removeEventListener('touchstart', onTouchStart);
            el.removeEventListener('touchmove', onTouchMove);
            el.removeEventListener('touchend', onTouchEnd);
        };
    }, [scrollRef, isRefreshing, pullDistance, threshold, handleRefresh]);

    return { pullDistance, isRefreshing };
}
